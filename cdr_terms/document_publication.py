"""Read-only, exact-generation document inventory for optional publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .document_discovery_queue import discovery_inventory
from .identity import require_sha
from .store import EvidenceStore


class _ReadOnlyStore:
    """Do not construct EvidenceStore: its initializer installs schema/triggers."""

    last_success = EvidenceStore.last_success

    def __init__(self, root):
        self.root = Path(root).absolute()
        database = self.root / 'evidence.sqlite3'
        if any(path.is_symlink() for path in (self.root, *self.root.parents, database)):
            raise ValueError('Document publication refuses symlink evidence paths')
        if not database.is_file():
            raise FileNotFoundError(database)
        self.deadline = time.monotonic() + 60
        self.consumed = 0
        self.verified = {}
        self.db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=1)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA query_only=ON')
        self.db.execute('PRAGMA cache_size=-2048')
        self.db.execute('PRAGMA mmap_size=0')
        self.db.set_progress_handler(lambda: int(time.monotonic() >= self.deadline), 10000)
        self.db.execute('BEGIN')
        if (self.db.execute('PRAGMA application_id').fetchone()[0] != 0x4152544D
                or self.db.execute('PRAGMA user_version').fetchone()[0] != 1):
            self.db.close()
            raise ValueError('Document publication requires the dedicated terms archive')

    def read_blob(self, identity):
        require_sha(identity)
        if time.monotonic() >= self.deadline:
            raise ValueError('Document publication deadline exceeded')
        path = self.root / 'blobs' / identity[:2] / identity
        if any(part.is_symlink() for part in (path, path.parent, path.parent.parent)) or not path.is_file():
            raise ValueError('Missing or unsafe document evidence blob')
        size = path.stat().st_size
        if size > 16 * 1024**2 or self.consumed + size > 512 * 1024**2:
            raise ValueError('Document publication verification byte budget exceeded')
        with path.open('rb') as stream:
            body = stream.read(size + 1)
        self.consumed += len(body)
        if len(body) != size or hashlib.sha256(body).hexdigest() != identity:
            raise ValueError('Document publication evidence bytes changed')
        return body

    def verify_blob(self, identity):
        """Verify shared documents once, rechecking file identity on every use.

        Public inventory needs document hashes, not PDF bytes. Keep signatures
        rather than caching the complete corpus or rehashing one shared PDF
        separately for hundreds of product applicability records.
        """
        require_sha(identity)
        path = self.root / 'blobs' / identity[:2] / identity
        if any(part.is_symlink() for part in (path, path.parent, path.parent.parent)) or not path.is_file():
            raise ValueError('Missing or unsafe document evidence blob')
        stat = path.stat()
        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if self.verified.get(identity) == signature:
            if time.monotonic() >= self.deadline:
                raise ValueError('Document publication deadline exceeded')
            return
        self.read_blob(identity)
        after = path.stat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != signature:
            raise ValueError('Document publication evidence file changed')
        self.verified[identity] = signature


def publication_document_inventory(evidence_root, generation_id, product_keys, *, expected_contract_digest=None):
    """Return map product->descriptors only for the exact completed generation.

    Missing archives/captures and noncurrent products return empty lists. A
    present corrupt/ambiguous archive raises: optional publication must defer,
    while financial publication remains independently successful.
    """
    keys = list(product_keys)
    if (not isinstance(generation_id, str) or not generation_id or len(keys) > 20000
            or any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys)):
        raise ValueError('Document publication requires bounded exact product identities')
    result = {key: [] for key in keys}
    if not (Path(evidence_root) / 'evidence.sqlite3').is_file():
        return result
    store = _ReadOnlyStore(evidence_root)
    try:
        capture = store.db.execute('SELECT * FROM ingest_captures WHERE ingest_id=?', (generation_id,)).fetchone()
        if not capture:
            return result
        receipt = json.loads(store.read_blob(capture['receipt_sha256']))
        if (receipt.get('generation_id') != generation_id or receipt.get('status') != 'CAPTURED_AND_QUEUED'
                or receipt.get('products') != capture['products']):
            raise ValueError('Document capture receipt differs from requested generation')
        if expected_contract_digest is not None and receipt.get('export_contract_digest') != expected_contract_digest:
            raise ValueError('Document capture differs from selected export contract')
        sources = receipt.get('sources')
        if not isinstance(sources, list) or len(sources) != capture['products'] or len(sources) > 20000:
            raise ValueError('Document capture product accounting differs')
        by_key = {}
        for source in sources:
            key = source['product_key']
            if key in by_key:
                raise ValueError('Document capture has ambiguous product identities')
            by_key[key] = source
        from .observation_checks import current_observation
        total = 0
        for key in keys:
            source = by_key.get(key)
            if source is None:
                continue
            observation = current_observation(store, key)
            if observation['ingest_id'] != generation_id:
                continue
            if (observation['observation_id'] != source['observation_id']
                    or observation['source_sha256'] != source['sha256']):
                raise ValueError('Document product differs from captured source')
            documents = discovery_inventory(store, key)['documents']
            total += len(documents)
            if len(documents) > 256 or total > 50000:
                raise ValueError('Document publication inventory budget exceeded')
            result[key] = documents
        return result
    finally:
        store.db.close()
