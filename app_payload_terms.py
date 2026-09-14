"""Optional current-generation terms shards from already published projections.

All shards are ordinary manifest assets. Index references are manifest keys, so
immutable revision retagging never leaves nested URLs pointing at another release.
This module neither interprets, reviews, promotes nor uploads evidence.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from cdr_terms.identity import require_sha
from cdr_terms.observation_checks import current_observation
from cdr_terms.reporting import build_product_asset, validate_public_asset

MAX_PRODUCTS = 20000
MAX_SHARD_RAW = 512 * 1024
MAX_SNAPSHOT_RAW = 24 * 1024 * 1024
MAX_BLOB = 16 * 1024 * 1024
MAX_BLOB_WORK = 512 * 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


class _ReadView:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        database = self.root / 'evidence.sqlite3'
        if database.is_symlink() or not database.is_file():
            raise ValueError('Existing dedicated terms database required')
        self.db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA query_only=ON')
        self.db.execute('BEGIN')
        self.used = 0

    def read_blob(self, identity):
        require_sha(identity)
        path = self.root / 'blobs' / identity[:2] / identity
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError('Missing or unsafe retained terms blob')
        size = path.stat().st_size
        if size > MAX_BLOB or self.used + size > MAX_BLOB_WORK:
            raise ValueError('Terms projection verification byte budget exceeded')
        self.used += size
        with path.open('rb') as stream:
            body = stream.read(size + 1)
        if len(body) != size or hashlib.sha256(body).hexdigest() != identity:
            raise ValueError('Retained terms blob identity changed')
        return body


def load_published_terms(root, *, source_observation, run_date, product_keys):
    """Read one consistent generation; refuse stale projections, never fill history.

Missing publications stay absent. Present but stale/invalid publications fail the
optional build as a whole, rather than silently offering an older interpretation.
"""
    keys = set(product_keys)
    if len(keys) > MAX_PRODUCTS or any(type(key) is not str or not key for key in keys):
        raise ValueError('Bounded exact payload product keys required')
    if not isinstance(source_observation, dict):
        raise ValueError('Terms require exact finalized source observation')
    generation = source_observation.get('generation_id')
    contract = source_observation.get('contract_digest')
    if not isinstance(generation, str) or not generation:
        raise ValueError('Terms require exact finalized source generation')
    require_sha(contract)
    view = _ReadView(root)
    try:
        capture = view.db.execute('SELECT * FROM ingest_captures WHERE ingest_id=?', (generation,)).fetchone()
        if not capture:
            raise ValueError('Terms source capture is not complete')
        receipt = json.loads(view.read_blob(capture['receipt_sha256']))
        if (receipt.get('generation_id') != generation or receipt.get('source_run_date') != run_date
                or receipt.get('export_contract_digest') != contract):
            raise ValueError('Terms capture differs from selected payload source')
        result, total = {}, 0
        for key in sorted(keys):
            publication = view.db.execute('SELECT * FROM publications WHERE product_key=? '
                                          'ORDER BY sequence DESC LIMIT 1', (key,)).fetchone()
            if publication is None:
                continue
            observation = current_observation(view, key)
            if (observation['ingest_id'] != generation
                    or observation['observation_id'] != publication['observation_id']):
                raise ValueError('Terms publication belongs to another source observation')
            body = publication['payload_json'].encode('utf-8')
            total += len(body)
            if len(body) > MAX_SHARD_RAW or total > MAX_SNAPSHOT_RAW:
                raise ValueError('Terms snapshot exceeds lazy asset budget')
            payload = json.loads(body)
            validate_public_asset(payload)
            if (payload['product_key'] != key or payload['identity_sha256'] != publication['identity_sha256']
                    or payload != build_product_asset(view, key)):
                raise ValueError('Terms projection changed since independent publication')
            result[key] = payload
        return result
    finally:
        view.db.close()


def package_terms(snapshot, *, run_date, write_asset):
    """Return manifest entries; index v2 points only at declared bounded shards."""
    if not snapshot:
        return {}
    if len(snapshot) > MAX_PRODUCTS:
        raise ValueError('Terms product count bound exceeded')
    files, index, group, total = {}, {}, {}, 0

    def flush():
        if not group:
            return
        key = f'terms_shard_{len(files):03d}'
        shard = {'schema_version': 1, 'run_date': run_date, 'products': dict(group)}
        files[key] = write_asset(key, shard)
        index.update({product: key for product in group})
        group.clear()

    for key, payload in sorted(snapshot.items()):
        validate_public_asset(payload)
        if payload['product_key'] != key:
            raise ValueError('Terms product identity mismatch')
        singleton = {'schema_version': 1, 'run_date': run_date, 'products': {key: payload}}
        size = len(_json(singleton))
        total += size
        if size > MAX_SHARD_RAW or total > MAX_SNAPSHOT_RAW:
            raise ValueError('Terms shard/snapshot byte bound exceeded')
        proposed = {'schema_version': 1, 'run_date': run_date, 'products': {**group, key: payload}}
        if len(_json(proposed)) > MAX_SHARD_RAW:
            flush()
        group[key] = payload
    flush()
    files['terms_index'] = write_asset('terms-index', {
        'schema_version': 2, 'run_date': run_date, 'products': index})
    return files
