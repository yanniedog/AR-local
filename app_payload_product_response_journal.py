"""Read-only complete promoted-journal proof, without recovery or writable locks."""
from datetime import datetime
import os
from pathlib import Path, PurePosixPath
import stat
import time

from app_payload_product_evidence_contract import decode, digest, require
from app_payload_product_evidence_delivery_check import read_stable, signature
from cdr_atomic import canonical_json_bytes
from cdr_raw_attempt_journal import RawAttemptJournal

MAX_BODY = 32 * 1024**2


def relative(value):
    require(type(value) is str and value and '\\' not in value, 'invalid response evidence path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in {'', '.', '..'} for p in value.split('/'))
            and ':' not in value, 'unsafe response evidence path')
    return path


class JournalProof:
    def __init__(self, exports, contract, *, deadline=None):
        self.exports = Path(exports).absolute()
        self.deadline = time.monotonic() + 600 if deadline is None else deadline
        self.identities, self.inventory = {}, {}
        for row in contract['artifacts']:
            name = relative(row['path']).as_posix()
            require(name not in self.inventory, 'duplicate contract artifact')
            self.inventory[name] = row
        self.pointer = decode(self.read('ingest-status.json', 8 * 1024**2))['raw_attempt_journal']
        self.base = relative(self.pointer['path']).as_posix()
        self.session = self.pointer['session_id']
        require(self.base == 'attempt-evidence/raw-attempt-journals-v1/' + self.session
                and self.pointer.get('verified') is True
                and self.pointer.get('path_resolution') == 'relative_to_finalized_export_root'
                and self.pointer.get('retention') == 'hash_bound_finalized_artifact', 'unpromoted response journal')
        self.manifest = self._inventory()
        self.journal = RawAttemptJournal((self.exports / self.base).parent, self.session)
        self.current = decode(self.read(self.base + '/current.json', 65536))
        require(self.current.get('schema_version') == 1 and self.current.get('session_id') == self.session
                and type(self.current.get('sequence')) is int and 0 < self.current['sequence'] <= 100000,
                'invalid response journal current pointer')
        self.events = self._chain()
        self.recheck()

    def check(self):
        require(time.monotonic() < self.deadline, 'response evidence deadline exceeded')

    def read(self, name, maximum=MAX_BODY):
        self.check(); relative(name)
        require(name in self.inventory, 'response evidence absent from contract')
        record = self.inventory[name]
        require(type(record['bytes']) is int and 0 <= record['bytes'] <= maximum, 'response evidence exceeds budget')
        path = self.exports / name
        raw, identity = read_stable(path, record['bytes'])
        require(len(raw) == record['bytes'] and digest(raw) == record['sha256'], 'response artifact mismatch')
        previous = self.identities.setdefault(path, identity)
        require(previous == identity, 'response evidence changed between reads')
        self.check()
        return raw

    def _inventory(self):
        name = self.base + '/promotion-manifest.json'
        require(self.pointer['promotion_manifest_path'] == name, 'response manifest path mismatch')
        raw = self.read(name, 16 * 1024**2); manifest = decode(raw)
        require(digest(raw) == self.pointer['promotion_manifest_sha256'], 'response manifest digest mismatch')
        records = []
        for path, record in sorted(self.inventory.items()):
            if not path.startswith(self.base + '/') or path == name: continue
            records.append(dict(path=path[len(self.base) + 1:], bytes=record['bytes'], sha256=record['sha256']))
        require(0 < len(records) <= 100000 and sum(r['bytes'] for r in records) <= 1024**3,
                'response journal aggregate budget exceeded')
        expected = dict(schema_version=1, artifact_path=self.base,
                        source_journal_path='_raw-attempt-journals-v1/' + self.session,
                        source_tree_sha256=digest(canonical_json_bytes({'files': records})),
                        source_file_count=len(records), source_bytes=sum(r['bytes'] for r in records),
                        journal=manifest.get('journal'), source_files=records)
        require(raw == canonical_json_bytes(expected), 'response promotion inventory mismatch')
        for field in ('source_tree_sha256', 'source_file_count', 'source_bytes'):
            require(type(self.pointer.get(field)) is type(expected[field]) and self.pointer[field] == expected[field],
                    'response promotion pointer mismatch')
        self.expected_files = {r['path'] for r in records} | {'promotion-manifest.json'}
        require(self._files() == self.expected_files, 'response journal inventory incomplete')
        for row in records: self.read(self.base + '/' + row['path'])
        require(self.inventory[self.base + '/.lock']['bytes'] == 1, 'response journal lock uninitialized')
        return manifest

    def _files(self):
        actual = set(); root = self.exports / self.base
        for directory, dirs, files in os.walk(root, followlinks=False):
            self.check()
            for child in [Path(directory), *(Path(directory) / item for item in dirs)]:
                require(stat.S_ISDIR(child.lstat().st_mode) and not child.is_symlink(), 'unsafe response directory')
            actual.update((Path(directory) / item).relative_to(root).as_posix() for item in files)
            require(len(actual) <= 100001, 'response journal file budget exceeded')
        return actual

    def _chain(self):
        names = sorted(p for p in self.inventory if p.startswith(self.base + '/events/'))
        keys = {p for p in self.inventory if p.startswith(self.base + '/keys/')}
        require(len(names) == len(keys) == self.current['sequence'], 'response journal sequence count mismatch')
        previous = None; completed_head = None; observed = None; events = []
        for sequence, name in enumerate(names, 1):
            self.check(); path = self.exports / name
            # Pure validator only: never summary/evidence_records/FileLock/recovery.
            event = self.journal._validate_event(path, sequence=sequence, previous_digest=previous)
            require(decode(self.read(name, 65536)) == event, 'response event changed')
            key = self.base + '/keys/' + event['attempt_key_hash'] + '.json'
            require(key in keys and decode(self.read(key, 65536)) == self.journal._pointer_for(event, path.name),
                    'response attempt pointer mismatch')
            keys.remove(key)
            response = event['response']; body = self.base + '/' + event['body_path']
            require(event['body_path'] == 'bodies/' + response['body_sha256'] + '.body'
                    and body in self.inventory and self.inventory[body]['bytes'] == response['body_bytes']
                    and self.inventory[body]['sha256'] == response['body_sha256'], 'response body binding mismatch')
            started = instant(event['request']['started_at']); completed = instant(response['completed_at'])
            require(completed >= started, 'response timestamps reversed')
            observed = max(observed, completed) if observed else completed
            completed_head = response['completed_at']; previous = event['event_digest']
            events.append(event_projection(event))
        require(not keys and self.current['head_digest'] == previous and self.current['updated_at'] == completed_head,
                'response journal head mismatch')
        summary = dict(schema_version=1, session_id=self.session, attempts=len(events), head_digest=previous, verified=True)
        # Historic original pointers/manifests omit observed_at together; never rewrite them.
        if 'observed_at' in self.pointer or 'observed_at' in self.manifest['journal']:
            summary['observed_at'] = observed.isoformat().replace('+00:00', 'Z')
        require(summary == self.manifest['journal'] and all(type(self.pointer.get(k)) is type(v)
                and self.pointer[k] == v for k, v in summary.items()), 'response journal summary mismatch')
        return events

    def body(self, sha):
        return self.read(self.base + '/bodies/' + sha + '.body')

    def recheck(self):
        self.check()
        require(self._files() == self.expected_files, 'response journal inventory changed')
        for path, before in self.identities.items():
            require(signature(path.lstat()) == before, 'response source changed after verification')


def instant(value):
    require(type(value) is str, 'response timestamp missing')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None and result.utcoffset() is not None, 'response timestamp lacks timezone')
    return result


def event_projection(event):
    """Retain bounded source routing metadata, never HTTP header collections."""
    context, request, response = event['context'], event['request'], event['response']
    return dict(sequence=event['sequence'], event_digest=event['event_digest'],
                phase=context.get('phase'), provider=context.get('provider'), product_id=context.get('product_id'),
                request_version=context.get('cdr_version'), response_version=(response.get('headers') or {}).get('x-v'),
                request_url=request.get('url'), method=request.get('method'),
                requested_version=(request.get('headers') or {}).get('x-v'),
                completed_at=response.get('completed_at'), status=response.get('status'), outcome=response.get('outcome'),
                body_sha256=response.get('body_sha256'), bytes=response.get('body_bytes'))
