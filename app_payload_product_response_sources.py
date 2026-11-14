"""Reconcile original anonymous product bodies with contract-bound exported rows."""
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from urllib.parse import quote, urlsplit

from app_payload_product_evidence import Budget, no_journals, open_database, regular, source_binding
from app_payload_product_evidence_contract import Limits, canonical, decode, digest, require, validate_manifest
from app_payload_product_evidence_delivery_check import read_stable, signature
from app_payload_product_evidence_transport_contract import validate_binding
from app_payload_product_response_journal import JournalProof
from cdr_clean_export import bank_product_key, clean_value, detail_json, inner_record, official_product_links, text
from cdr_compatibility import response_shape_error
from cdr_export_contract import load_contract
from cdr_ingest_support import DATASET_TO_FOLDER, has_cdr_errors, infer_cdr_dataset
from cdr_journal_evidence import _provider_directories


def version(value):
    if type(value) is str and value.isascii() and value.isdecimal() and len(value) <= 10:
        value = int(value)
    return value if type(value) is int and 0 < value <= 2147483647 else None


def public_request(event, provider):
    try:
        actual, base = urlsplit(event['request_url']), urlsplit(provider['endpoint_url'])
        if (event['method'] != 'GET' or actual.scheme != 'https' or base.scheme != 'https'
                or actual.username or actual.password or base.username or base.password
                or actual.netloc != base.netloc or actual.fragment): return False
        expected = base.path.rstrip('/')
        if event['phase'] != 'products_index': expected += '/' + quote(event['product_id'], safe='')
        return actual.path == expected
    except (TypeError, ValueError, KeyError):
        return False


def exported_projection(payload):
    record = inner_record(payload)
    projected = clean_value(record)
    links = official_product_links(record)
    if links: projected['additionalInformation'] = links
    return projected


def projections(payload):
    return {'legacy-v1-clean-value-with-official-links': exported_projection(payload),
            'legacy-v1-detail-json-with-source-documents': decode(detail_json(inner_record(payload)))}


class ResponseSources:
    """Read-only diagnostic source, never selected-edition or publication authority."""
    def __init__(self, snapshot_root, exports, contract_path, *, expected_binding, withheld=()):
        validate_binding(expected_binding)
        self.binding = decode(canonical(expected_binding))
        self.budget = Budget(Limits())
        self.snapshot_path = Path(snapshot_root).absolute() / 'snapshot.json'
        snapshot_raw, snapshot_identity = read_stable(self.snapshot_path, Limits().index_bytes)
        self.snapshot = decode(snapshot_raw); validate_manifest(self.snapshot)
        require(digest(snapshot_raw) == expected_binding['snapshot_sha256']
                and self.snapshot['source'] == expected_binding['source'], 'response snapshot binding mismatch')
        self.contract_path = Path(contract_path).absolute()
        contract_raw, contract_identity = read_stable(self.contract_path, 16 * 1024**2)
        self.contract = load_contract(self.contract_path)
        require(digest(contract_raw) == expected_binding['source']['contract_file_sha256'], 'response contract file mismatch')
        self.database = regular(Path(exports).absolute() / 'local-cdr.sqlite')
        self.initial = {self.snapshot_path: snapshot_identity, self.contract_path: contract_identity,
                        self.database: signature(self.database.lstat())}
        no_journals(self.database)
        require(source_binding(self.database, self.contract_path, self.budget) == expected_binding['source'],
                'response database/source mismatch')
        self.proof = JournalProof(exports, self.contract, deadline=self.budget.deadline)
        directories = _provider_directories(self.contract['provider_states'])
        self.providers = {directories[row['provider_uid']]: row for row in self.contract['provider_states']}
        require(len(self.providers) == len(directories), 'response provider directory collision')
        self.withheld = set(withheld)
        require(len(self.withheld) <= 20000 and all(type(x) is str and len(x) == 64
                and all(c in '0123456789abcdef' for c in x) for x in self.withheld), 'invalid explicit withheld body digest')
        self.details, self.indexes, self.failures = defaultdict(dict), defaultdict(dict), defaultdict(set)
        self._candidates()
        self.recheck()

    def _candidates(self):
        parsed = set()
        wanted = {(p['identity']['provider'], p['identity']['product_id']) for p in self.snapshot['products']}
        for event in self.proof.events:
            self.budget.check()
            if event['phase'] not in {'products_index', 'product_detail', 'classification_detail'}: continue
            provider, pid, sha = event['provider'], event['product_id'], event['body_sha256']
            key = (provider, pid)
            if provider not in self.providers: continue
            if event['phase'] != 'products_index' and key not in wanted: continue
            if event['outcome'] != 'success' or type(event['status']) is not int or not 200 <= event['status'] < 300:
                if pid: self.failures[key].add('detail_http_unavailable')
                continue
            if not public_request(event, self.providers[provider]):
                if pid: self.failures[key].add('public_source_unverified')
                continue
            if sha in self.withheld:
                if pid: self.failures[key].add('body_withheld_unresolved')
                continue
            reference = dict(sequence=event['sequence'], event_digest=event['event_digest'], phase=event['phase'],
                             completed_at=event['completed_at'], request_version=version(event['request_version']),
                             response_version=version(event['response_version']), provider=provider,
                             provider_uid=self.providers[provider]['provider_uid'],
                             product_id=pid if event['phase'] != 'products_index' else None)
            requested = version(event['requested_version'])
            if requested is not None and reference['request_version'] is not None and requested != reference['request_version']:
                if pid: self.failures[key].add('request_version_conflict')
                continue
            reference['request_version'] = reference['request_version'] or requested
            cache_key = (provider, pid, sha, event['phase'])
            if cache_key in parsed:
                target = self.indexes if event['phase'] == 'products_index' else self.details
                for route_key, versions in target.items():
                    if route_key[0] == provider and sha in versions: versions[sha]['events'].append(reference)
                continue
            parsed.add(cache_key)
            try:
                raw = self.proof.body(sha)
                payload = decode(raw.decode('utf-8', errors='strict'))
                require(not has_cdr_errors(payload) and response_shape_error(payload, phase=event['phase'], product_id=pid or '') is None,
                        'response semantic shape invalid')
            except (ValueError, UnicodeError, RecursionError):
                if pid: self.failures[key].add('response_invalid')
                continue
            item = dict(sha256=sha, bytes=event['bytes'], events=[reference])
            if event['phase'] == 'products_index':
                rows = payload['data'].get('products') if isinstance(payload['data'], dict) else payload['data']
                for row in rows:
                    index_key = provider, row.get('productId', row.get('id'))
                    if index_key not in wanted: continue
                    previous = self.indexes[index_key].setdefault(sha, dict(item, events=[]))
                    if reference not in previous['events']: previous['events'].append(reference)
            elif type(pid) is str and pid:
                previous = self.details[key].setdefault(sha, dict(item, events=[]))
                previous['events'].append(reference)

    def products(self):
        wanted = {p['identity']['product_key']: p['identity'] for p in self.snapshot['products']}
        require(len(wanted) == len(self.snapshot['products']), 'response product key collision')
        seen = set()
        with closing(open_database(self.database, self.binding['source'], self.budget)) as connection:
            rows = connection.execute('SELECT dataset,provider,product_id,product_key,product_name,details_json '
                                      'FROM bank_products WHERE run_date=? ORDER BY product_key',
                                      (self.binding['source']['observation_date'],))
            for row in rows:
                self.budget.check()
                identity = {key: row[key] for key in ('dataset', 'provider', 'product_id', 'product_key', 'product_name')}
                require(identity['product_key'] not in seen and wanted.get(identity['product_key']) == identity,
                        'response exported/snapshot product identity mismatch')
                seen.add(identity['product_key'])
                yield self._product(identity, row['details_json'])
        require(seen == set(wanted), 'response exported product population mismatch')
        self.recheck()

    def _product(self, identity, details_json):
        provider = self.providers.get(identity['provider'])
        require(provider is not None, 'response exported provider absent from contract')
        key = identity['provider'], identity['product_id']
        versions = []
        projection_known = self.contract['normalization_version'] == 'legacy-v1'
        expected = canonical(decode(details_json)) if projection_known else None
        for sha, candidate in sorted(self.details[key].items()):
            self.budget.check()
            payload = decode(self.proof.body(sha).decode('utf-8', errors='strict')); record = inner_record(payload)
            source_key = bank_product_key(dict(provider=identity['provider'], product_id=identity['product_id'],
                                               category=text(record.get('productCategory') or record.get('category')),
                                               product_name=text(record.get('name') or record.get('productName'))))
            dataset = DATASET_TO_FOLDER.get(infer_cdr_dataset(record, allow_name_fallback=True) or '')
            variants = [name for name, value in projections(payload).items() if canonical(value) == expected] if projection_known else []
            matches = bool(variants) and source_key == identity['product_key'] and dataset == identity['dataset']
            if dataset != identity['dataset']: self.failures[key].add('dataset_unverified')
            versions.append(dict(candidate, matches_export=matches, projection_variants=variants if matches else []))
        matched = [v['sha256'] for v in versions if v['matches_export']]
        indexes = list(self.indexes[key].values())
        state = ('matched' if len(matched) == 1 else 'ambiguous' if len(matched) > 1
                 else 'projection_unverified' if versions else 'index_only' if indexes else 'missing')
        return dict(identity=identity, provider_uid=provider['provider_uid'], state=state,
                    current_body_sha256=matched[0] if len(matched) == 1 else None,
                    details=versions, indexes=indexes, reasons=sorted(self.failures[key]),
                    projection='known-exact-projections' if projection_known else 'unsupported')

    def body(self, sha):
        require(sha not in self.withheld, 'response body explicitly withheld')
        return self.proof.body(sha)

    def recheck(self):
        self.budget.check(); self.proof.recheck()
        for path, before in self.initial.items():
            require(signature(path.lstat()) == before, 'response source changed')
