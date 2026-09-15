"""Bounded selected-observation inventory. Never opens a write-capable store."""
import json
import sqlite3
import hashlib
import io

from app_payload_terms import _ReadView, MAX_BLOB, MAX_BLOB_WORK
from cdr_terms.identity import digest
from cdr_terms.observation_checks import selected_check

MAX_ROW_BYTES = 24 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
MAX_ROWS = 100000
MAX_PRODUCT_ROWS = 4096


class Cursor:
    def __init__(self, owner, cursor):
        self.owner, self.cursor = owner, cursor

    def fetchall(self):
        rows = []
        while True:
            row = self.fetchone()
            if row is None:
                return rows
            rows.append(row)
            if len(rows) > MAX_PRODUCT_ROWS:
                raise ValueError('Report terms row budget exceeded')

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            raw = json.dumps(dict(row), ensure_ascii=False).encode('utf8')
            self.owner.row_bytes += len(raw)
            self.owner.count += 1
            if self.owner.count > MAX_ROWS or self.owner.row_bytes > MAX_ROW_BYTES:
                raise ValueError('Report terms row budget exceeded')
            self.owner.identities.append(digest(dict(row)))
        return row


class Snapshot:
    def __init__(self, root):
        self.view = _ReadView(root)
        self.row_bytes = 0
        self.view.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
        self.count, self.steps, self.identities = 0, 0, []
        self.view.db.set_progress_handler(self.progress, 1000)
        self.db = self
        self.tables = {r[0] for r in self.view.db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        self.blobs = {}
        self.processed_io_bytes = 0
        self.max_read_request = 0
        self.max_materialized_blob = 0

    def progress(self):
        self.steps += 1000
        return int(self.steps > 10000000)

    def execute(self, sql, params=()):
        return Cursor(self, self.view.db.execute(sql, params))

    def read_blob(self, identity):
        # Only finalized capture/contract parsing needs bytes; never cache them.
        return self._blob(identity, materialize=True)

    def verify_blob(self, identity):
        return self._blob(identity, materialize=False)

    def _blob(self, identity, *, materialize):
        from cdr_terms.identity import require_sha
        require_sha(identity)
        path = self.view.root / 'blobs' / identity[:2] / identity
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError('Missing or unsafe retained terms blob')
        size = path.stat().st_size
        if size > MAX_BLOB or self.processed_io_bytes + size > MAX_BLOB_WORK:
            raise ValueError('Report processed blob byte budget exceeded')
        checksum, seen = hashlib.sha256(), 0
        buffer = io.BytesIO() if materialize else None
        with path.open('rb') as stream:
            while True:
                request = min(READ_CHUNK_BYTES, size + 1 - seen)
                self.max_read_request = max(self.max_read_request, request)
                chunk = stream.read(request)
                if not chunk:
                    break
                seen += len(chunk)
                self.processed_io_bytes += len(chunk)
                if seen > size or self.processed_io_bytes > MAX_BLOB_WORK:
                    raise ValueError('Report retained blob changed or byte budget exceeded')
                checksum.update(chunk)
                if buffer is not None:
                    buffer.write(chunk)
        if seen != size or checksum.hexdigest() != identity:
            raise ValueError('Retained terms blob identity changed')
        self.blobs[identity] = size
        if buffer is None:
            return size
        self.max_materialized_blob = max(self.max_materialized_blob, size)
        return buffer.getvalue()

    def close(self):
        self.view.db.close()

    def capture(self, binding):
        generation = binding['source_generation_id']
        if not generation:
            return None
        row = self.execute('SELECT * FROM ingest_captures WHERE ingest_id=?', (generation,)).fetchone()
        if row is None:
            return None
        from cdr_terms.executable_sources import finalized_capture
        receipt = finalized_capture(self, generation, binding['run_date'])
        if receipt['export_contract_digest'] != binding['export_contract_sha256']:
            raise ValueError('Report source capture differs from selected bundle')
        sources = receipt.get('sources')
        if not isinstance(sources, list) or len(sources) != row['products'] or len(sources) > 20000:
            raise ValueError('Report capture member inventory unavailable or invalid')
        members = {(r['product_key'], r['observation_id'], r['sha256']) for r in sources}
        if len(members) != len(sources):
            raise ValueError('Report duplicate capture member')
        return members

    def product(self, key, binding, members):
        if members is None:
            return {'status': 'unavailable', 'reason': 'selected finalized capture unavailable'}
        rows = self.execute('SELECT * FROM observations WHERE product_key=? AND ingest_id=?',
                            (key, binding['source_generation_id'])).fetchall()
        if not rows:
            return {'status': 'unavailable', 'reason': 'selected observation unavailable'}
        if len(rows) != 1:
            raise ValueError('Report selected observation ambiguous')
        observation = dict(rows[0])
        if (key, observation['observation_id'], observation['source_sha256']) not in members:
            raise ValueError('Report selected observation not in finalized capture')
        self.verify_blob(observation['source_sha256'])
        current = self.execute('SELECT observation_id FROM observations o WHERE product_key=? '
                              'AND EXISTS(SELECT 1 FROM ingest_captures c WHERE c.ingest_id=o.ingest_id) '
                              'ORDER BY observed_at DESC,observation_id DESC LIMIT 1', (key,)).fetchone()
        documents, references = self.documents(observation)
        interpretations = self.interpretations(observation)
        return {'status': 'reported', 'observation_id': observation['observation_id'],
                'source_sha256': observation['source_sha256'], 'observed_at': observation['observed_at'],
                'matches_current_observation': current is not None and current[0] == observation['observation_id'],
                'document_references': references, 'documents': documents,
                'graph': self.graph(observation['observation_id']), 'interpretations': interpretations,
                'executables': self.executables(observation),
                'stages': {'capture': {'observed': sum(d['latest_status'] in ('fetched', 'unchanged') for d in documents),
                                       'expected': len(documents), 'basis': 'known_referenced_documents'},
                           'complete_document_inventory': {'observed': len(documents), 'expected': None,
                                                           'basis': 'legal_completeness_unverified'},
                           'bank_approved_products': {'observed': None, 'expected': None,
                                                      'basis': 'bank_acceptance_provenance_unavailable'}}}

    def documents(self, observation):
        references = [dict(r) for r in self.execute(
            'SELECT applicability_id,document_id,relation FROM applicability '
            'WHERE observation_id=? ORDER BY applicability_id', (observation['observation_id'],)).fetchall()]
        # Omit source_path/context: these can contain local paths or private metadata.
        documents = []
        for identity in sorted({r['document_id'] for r in references}):
            latest = selected_check(self, observation, identity)
            retained = selected_check(self, observation, identity, successful_only=True)
            item = {'document_id': identity, 'latest_status': latest['status'] if latest else 'pending',
                    'latest_check_id': latest['check_id'] if latest else None,
                    'retained_version': None, 'extractions': []}
            if retained:
                version = self.execute('SELECT document_version_id,content_sha256,byte_size,observed_at '
                                       'FROM document_versions WHERE document_version_id=?',
                                       (retained['document_version_id'],)).fetchone()
                if version is None or self.verify_blob(version['content_sha256']) != version['byte_size']:
                    raise ValueError('Report retained document bytes differ')
                item['retained_version'] = dict(version)
                for row in self.execute('SELECT extraction_id,extractor_version,status,text_sha256,coverage_json '
                                        'FROM extractions WHERE document_version_id=? ORDER BY extraction_id',
                                        (version['document_version_id'],)).fetchall():
                    self.verify_blob(row['text_sha256'])
                    projected = dict(row)
                    projected['coverage_sha256'] = digest(json.loads(projected.pop('coverage_json')))
                    item['extractions'].append(projected)
            documents.append(item)
        return documents, references

    def interpretations(self, observation):
        results = []
        for row in self.execute('SELECT term_revision_id,parameter_key,unit,rule_set_id,applicability_json '
                                'FROM term_revisions WHERE observation_id=? ORDER BY term_revision_id',
                                (observation['observation_id'],)).fetchall():
            item = dict(row)
            item['applicability_sha256'] = digest(json.loads(item.pop('applicability_json')))
            review = self.execute('SELECT review_id,status,reviewer_kind,evidence_sha256 FROM reviews '
                                  'WHERE term_revision_id=? ORDER BY sequence DESC LIMIT 1', (row['term_revision_id'],)).fetchone()
            if review:
                self.verify_blob(review['evidence_sha256'])
            item['review'] = dict(review) if review else None
            item['changes'] = [dict(r) for r in self.execute(
                'SELECT term_change_id,kind,after_revision_id FROM term_changes WHERE before_revision_id=? ORDER BY term_change_id',
                (row['term_revision_id'],)).fetchall()]
            results.append(item)
        return results

    def graph(self, observation_id):
        if 'document_graph_roots' not in self.tables:
            return {'status': 'not_reported', 'completeness': 'unknown', 'nodes': [], 'edges': []}
        roots = self.execute('SELECT DISTINCT s.root_id FROM document_graph_scopes s JOIN applicability a '
                             'USING(applicability_id) WHERE a.observation_id=? ORDER BY s.root_id', (observation_id,)).fetchall()
        nodes, edges = [], []
        for root in roots:
            for node in self.execute('SELECT n.node_id,n.root_id,n.document_id,n.parent_node_id,n.depth,e.reason '
                                     'FROM document_graph_nodes n LEFT JOIN document_graph_expansions e USING(node_id) '
                                     'WHERE n.root_id=? ORDER BY n.node_id', (root[0],)).fetchall():
                nodes.append(dict(node))
                edges.extend(dict(r) for r in self.execute('SELECT edge_id,parent_node_id,child_node_id,reason '
                                                           'FROM document_graph_edges WHERE parent_node_id=? ORDER BY edge_id',
                                                           (node['node_id'],)).fetchall())
        return {'status': 'reported' if roots else 'not_reported', 'completeness': 'unknown',
                'nodes': nodes, 'edges': edges}

    def executables(self, observation):
        if 'executable_registry_subjects' not in self.tables:
            return {'status': 'not_reported', 'subjects': [], 'publications': []}
        subjects = []
        for row in self.execute('SELECT subject_id,wire_version,capability,scope_id FROM executable_registry_subjects '
                                'WHERE product_key=? AND observation_id=? ORDER BY subject_id',
                                (observation['product_key'], observation['observation_id'])).fetchall():
            version = row['wire_version']
            # All SQL identifiers are fixed by this closed dispatch, never input text.
            table, column = {1: ('executable_reviews', 'template_id'), 2: ('executable_reviews_v2', 'subject_id'),
                             3: ('executable_reviews_v3', 'subject_id')}.get(version, (None, None))
            if table is None:
                subjects.append({**dict(row), 'recorded_review': None, 'current_approval_revalidated': False,
                                 'unavailable_reason': 'unsupported registry wire version'})
                continue
            review = self.execute(f'SELECT review_id,decision,reviewed_at,evidence_sha256 FROM {table} '
                                  f'WHERE {column}=? ORDER BY sequence DESC LIMIT 1', (row['subject_id'],)).fetchone()
            if review:
                self.verify_blob(review['evidence_sha256'])
            subjects.append({**dict(row), 'recorded_review': dict(review) if review else None,
                             'current_approval_revalidated': False})
        publications = []
        for table, capability in [('executable_publications', 'fixed_td_calculation'),
                                  ('executable_publications_v2', 'eligibility_only'),
                                  ('executable_publications_v3', None)]:
            if table not in self.tables:
                continue
            columns = 'publication_id,observation_id,identity_sha256,published_at'
            if capability is None:
                columns += ',capability,state'
            for row in self.execute(f'SELECT {columns} FROM {table} WHERE product_key=? ORDER BY sequence',
                                    (observation['product_key'],)).fetchall():
                publications.append({**dict(row), **({'capability': capability, 'state': 'active'} if capability else {})})
        return {'status': 'reported', 'subjects': subjects, 'publications': publications}

    def receipt(self):
        return {'row_count': self.count, 'row_inventory_sha256': digest(sorted(self.identities)),
                'blob_sha256s': sorted(self.blobs), 'processed_io_bytes': self.processed_io_bytes,
                'row_bytes': self.row_bytes, 'row_byte_limit': MAX_ROW_BYTES,
                'processed_io_limit': MAX_BLOB_WORK, 'per_blob_limit': MAX_BLOB,
                'read_chunk_limit': READ_CHUNK_BYTES, 'max_read_request': self.max_read_request,
                'max_materialized_blob': self.max_materialized_blob, 'raw_blob_cache_bytes': 0,
                'sqlite_application_id': self.view.db.execute('PRAGMA application_id').fetchone()[0],
                'sqlite_user_version': self.view.db.execute('PRAGMA user_version').fetchone()[0]}
