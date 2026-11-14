"""Bounded read-only selected finalized-source proof for held optional preparation."""
from pathlib import Path, PurePosixPath
import stat
import time

from app_payload_optional_assets import iter_payload_assets
from app_payload_network_budget import validate_payload_network_budget
from app_payload_product_evidence_contract import canonical, decode, digest, fields, require
from app_payload_product_evidence_delivery_check import read_stable, signature
from cdr_export_contract import hash_file, load_contract
from cdr_finalization import verify_completion_marker
from cdr_ledger_v2 import verify_ledger
from app_payload_revisions_state import RevisionError
from cdr_product_evidence_delivery_policy import source_reference, LANES, STATUS


class SourceUnavailable(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class SourceBudgetExceeded(RuntimeError):
    pass


class SourceUnsupported(SourceUnavailable):
    def __init__(self): super().__init__('unsupported_source_schema')


class ReadBudget:
    """Finite source proof: current/ancestor artifacts, not an unbounded history job."""
    def __init__(self):
        self.bytes = self.entries = 0
        self.phase = 1
        self.exceeded = False
        self.deadline = time.monotonic() + 600

    def begin_proof(self):
        # Only a whole recheck can start another phase. A failed/expired phase
        # cannot reset its exceeded bound, and the original deadline never moves.
        self()
        if self.phase >= 5:
            self.exceeded = True
            raise SourceBudgetExceeded('source proof phase count exceeded')
        self.phase += 1; self.bytes = self.entries = 0

    def __call__(self, *, size=0, entries=0, reserve_bytes=0):
        self.bytes += size; self.entries += entries
        if (self.exceeded or time.monotonic() >= self.deadline or self.bytes + reserve_bytes > 16 * 1024**3
                or self.entries > 100000):
            self.exceeded = True
            raise SourceBudgetExceeded('bounded source verification exceeded')


def safe_path(root, relative):
    require(type(relative) is str and 0 < len(relative) <= 1024 and '\\' not in relative and ':' not in relative,
            'unsafe source relative path')
    part = PurePosixPath(relative)
    require(not part.is_absolute() and part.as_posix() == relative and all(p not in ('.', '..') for p in part.parts),
            'unsafe source relative path')
    path = root.joinpath(*part.parts)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink selected evidence')
    return path


class FinalizedSource:
    """A momentary local source observation, never permission to publish or repair.

    Requires caller-pinned pointer/base hashes. Reads the same partial-vs-complete
    pointer rule as current daily publication. Rechecks cannot replace outer
    queue ownership, immutable-source admission or the final promotion fence.
    """
    def __init__(self, state_dir, base_root, *, expected_pointer_sha256, expected_manifest_sha256):
        self.state = Path(state_dir).absolute(); self.base_root = Path(base_root).absolute()
        self.budget = ReadBudget(); self.identities = {}; self.controls = {}
        self.expected_pointer = expected_pointer_sha256; self.expected_manifest = expected_manifest_sha256
        try:
            self._load()
        except SourceUnavailable:
            raise
        except FileNotFoundError as error:
            raise SourceUnavailable('source_unavailable') from error
        except (OSError, ValueError, KeyError, TypeError, RevisionError, RecursionError) as error:
            raise SourceUnavailable('source_unverified') from error

    def _read(self, path, maximum):
        self.budget(entries=1)
        raw, identity = read_stable(path, maximum); self.budget(size=len(raw))
        if (path in self.identities and self.identities[path] != identity
                or path in self.controls and self.controls[path] != digest(raw)):
            raise SourceUnavailable('source_superseded')
        self.identities[path] = identity; self.controls[path] = digest(raw)
        return raw

    def _current(self):
        root = self.state / 'observation-pointers-v2'
        observed = decode(self._read(root / 'latest-observation.json', 65536))
        require(type(observed) is dict, 'observed pointer must be an object')
        if type(observed.get('schema_version')) is not int or observed['schema_version'] != 2: raise SourceUnsupported()
        self._pointer_fields(observed)
        require(type(observed) is dict and type(observed.get('observation_state')) is str
                and observed['observation_state'] in {'partial', 'complete', 'failed'}, 'invalid observed pointer')
        path = root / ('latest-observation.json' if observed.get('observation_state') == 'partial' else 'latest-complete.json')
        raw = self._read(path, 65536)
        if digest(raw) != self.expected_pointer: raise SourceUnavailable('source_superseded')
        pointer = decode(raw)
        require(type(pointer) is dict, 'selected pointer must be an object')
        if type(pointer['schema_version']) is not int or pointer['schema_version'] != 2: raise SourceUnsupported()
        self._pointer_fields(pointer)
        require(pointer['observation_state'] == ('partial' if observed['observation_state'] == 'partial' else 'complete'),
                'selected pointer has wrong selection role')
        return pointer

    @staticmethod
    def _pointer_fields(pointer):
        fields(pointer, ('schema_version', 'observation_date', 'generation_id', 'observation_state',
                         'ledger_event_digest', 'marker_path', 'export_path'))

    def _load(self):
        self.base_raw = self._read(self.base_root / 'manifest.json', 65536)
        require(digest(self.base_raw) == self.expected_manifest, 'base manifest differs from caller pin')
        self.base = decode(self.base_raw); self.source = source_reference(self.base)
        if type(self.base.get('schema_version')) is not int or self.base['schema_version'] != 1: raise SourceUnsupported()
        if self.source['observation_state'] == 'failed': raise SourceUnavailable('source_failed')
        require(not any(key in self.base for key in (*LANES, STATUS)), 'source base already contains optional delivery')
        validate_payload_network_budget(self.base, manifest_bytes=len(self.base_raw), asset_root=self.base_root)
        self.pointer = self._current()
        require(all(self.pointer[k] == self.source[k] for k in ('generation_id', 'observation_date', 'observation_state')),
                'selected pointer and financial source differ')
        self.marker_path = safe_path(self.state, self.pointer['marker_path'])
        marker_raw = self._read(self.marker_path, 65536); self.marker = decode(marker_raw)
        self.contract_path = safe_path(self.state, self.marker['export_contract_path'])
        contract_raw = self._read(self.contract_path, 16 * 1024**2)
        contract_value = decode(contract_raw)
        require(type(contract_value) is dict, 'contract must be an object')
        if type(contract_value.get('schema_version')) is not int or contract_value['schema_version'] != 2: raise SourceUnsupported()
        self.contract = load_contract(self.contract_path, budget=self.budget)
        require(all(self.contract[k] == self.source[k] for k in self.source), 'contract and financial source differ')
        require(self.contract['completion_marker_path'] == self.pointer['marker_path']
                and self.contract['source_path'] == self.pointer['export_path']
                and self.marker['ledger_event_digest'] == self.pointer['ledger_event_digest'], 'source control paths differ')
        self.exports = safe_path(self.state.parent, self.pointer['export_path'])
        self.database = safe_path(self.exports, 'local-cdr.sqlite')
        self.selection = dict(pointer_sha256=self.expected_pointer, completion_sha256=digest(marker_raw),
                              contract_file_sha256=digest(contract_raw), ledger_event_digest=self.pointer['ledger_event_digest'])
        self._model_digest = self._binding_digest()
        self._capture_artifacts()
        self._verify()

    def _binding_digest(self):
        return digest(canonical([self.base, self.source, self.pointer, self.selection, self.contract]))

    def _capture_artifacts(self):
        from app_payload_revisions_state import validate_manifest
        validate_manifest(self.base)
        for row in self.contract['artifacts']:
            self.budget(entries=1); path = safe_path(self.exports, row['path']); info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'unsafe finalized artifact')
            self.identities[path] = signature(info)
        for _, row in iter_payload_assets(self.base):
            path = safe_path(self.base_root, row['name']); info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'unsafe financial asset')
            self.identities[path] = signature(info)
        for path in (self.state / 'ledger-v2/events').glob('*/*.json'):
            self.budget(entries=1); self._read(path, 65536)
        self._read(self.state / 'ledger-v2/head.json', 65536)

    def _verify(self):
        if not verify_completion_marker(self.marker, self.state, self.source['observation_date'], budget=self.budget):
            raise SourceUnavailable('source_unverified')
        report = verify_ledger(self.state, verify_artifacts=False, budget=self.budget)
        if not report['ok']: raise SourceUnavailable('source_unverified')
        for _, row in iter_payload_assets(self.base):
            path = safe_path(self.base_root, row['name'])
            require(path.stat().st_size == row['bytes'] and hash_file(path, budget=self.budget) == row['sha256'],
                    'base financial asset bytes differ')
        self._stable()

    def _stable(self):
        self.budget()
        if self._binding_digest() != self._model_digest: raise SourceUnavailable('source_superseded')
        if self._current() != self.pointer: raise SourceUnavailable('source_superseded')
        for path, before in list(self.identities.items()):
            self.budget(entries=1)
            if signature(path.lstat()) != before: raise SourceUnavailable('source_superseded')
        for path, checksum in list(self.controls.items()):
            if digest(self._read(path, 16 * 1024**2 if path == self.contract_path else 65536)) != checksum:
                raise SourceUnavailable('source_superseded')

    def recheck(self):
        self.budget.begin_proof()
        try:
            self._stable(); self._verify()
        except SourceUnavailable:
            raise
        except (OSError, ValueError, KeyError, TypeError, RevisionError, RecursionError) as error:
            raise SourceUnavailable('source_unverified') from error
