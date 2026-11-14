"""Read-only complete lazy-package verification; a marker never substitutes bytes."""
import os
from pathlib import Path
import stat
import time
import zlib

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require
from app_payload_product_evidence_transport_contract import (
    DeliveryLimits, validate_capability, validate_index, validate_shard,
)


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_stable(path, maximum):
    require(not any(item.is_symlink() for item in (path, *path.parents)), "symlink delivery evidence")
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= maximum, "unsafe delivery evidence")
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(maximum + 1)
        require(len(raw) == info.st_size and signature(info) == signature(os.fstat(fd))
                and signature(info) == signature(path.stat()), "delivery evidence changed during read")
        return raw, signature(info)
    finally:
        os.close(fd)


def asset(root, descriptor, identities):
    path = root / descriptor['name']
    blob, identity = read_stable(path, descriptor['bytes'])
    require(len(blob) == descriptor['bytes'] and digest(blob) == descriptor['sha256'], "delivery asset digest/size mismatch")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = decoder.decompress(blob, descriptor['decoded_bytes'] + 1)
    require(len(raw) == descriptor['decoded_bytes'] and decoder.eof and not decoder.unused_data
            and not decoder.unconsumed_tail, "delivery gzip boundary mismatch")
    value = decode(raw)
    require(canonical(value) == raw, "noncanonical delivery asset")
    identities[path] = identity
    return value


def verify_assets(root, capability, *, limits=DeliveryLimits(), deadline=None):
    """Every routed page and every actual page must agree; stream one shard at a time."""
    deadline = time.monotonic() + 600 if deadline is None else deadline
    root = Path(root).absolute()
    require(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), "unsafe delivery root")
    validate_capability(capability, limits=limits)
    identities = {}
    index = asset(root, capability['index'], identities)
    validate_index(index, capability, limits=limits)
    routes, remaining, expected_counts, seen = {}, {}, {}, {}
    for product in index['products']:
        key = product['identity']['product_key']
        remaining[key], expected_counts[key] = len(product['pages']), product['facts']
        for sequence, page in enumerate(product['pages']):
            routes[page['shard'], page['page']] = product['identity'], sequence, page['facts']
    completed, facts = 0, 0
    for descriptor in capability['shards']:
        require(time.monotonic() < deadline, "delivery verification deadline exceeded")
        shard = asset(root, descriptor, identities)
        validate_shard(shard, capability)
        for position, page in enumerate(shard['pages']):
            expected = routes.pop((descriptor['sha256'], position), None)
            require(expected == (page['identity'], page['sequence'], len(page['facts'])), "unrouted/detached delivery page")
            key = page['identity']['product_key']
            ids = seen.setdefault(key, set())
            for fact in page['facts']:
                require(fact['fact_id'] not in ids, "duplicate product fact across delivery pages")
                ids.add(fact['fact_id'])
            facts += len(page['facts']); remaining[key] -= 1
            if remaining[key] == 0:
                require(len(ids) == expected_counts[key], "delivery product fact count differs")
                del seen[key]; completed += 1
    require(not routes and not seen and completed == capability['products'] and facts == capability['facts'], "incomplete delivery pages")
    require(time.monotonic() < deadline, "delivery verification deadline exceeded")
    for path, identity in identities.items():
        require(signature(path.lstat()) == identity, "delivery asset changed after verification")
    return {'products': completed, 'facts': facts, 'shards': len(capability['shards'])}


def verify_prepared(root, *, expected_binding, limits=DeliveryLimits()):
    """Completion evidence only; neither selection nor publication is authorized."""
    root = Path(root).absolute(); marker = root / 'prepared.json'
    raw, identity = read_stable(marker, limits.namespace_bytes + 1024)
    prepared = decode(raw)
    fields(prepared, ('publication_authorized', 'selection_verified', 'capability'))
    require(prepared['publication_authorized'] is False and prepared['selection_verified'] is False, "offline delivery authority invalid")
    capability = prepared['capability']
    validate_capability(capability, limits=limits)
    require(capability['binding'] == expected_binding, "delivery source binding differs")
    wanted = {'prepared.json', capability['index']['name'], *(item['name'] for item in capability['shards'])}
    require({path.name for path in root.iterdir()} == wanted, "partial or unexpected delivery files")
    totals = verify_assets(root, capability, limits=limits)
    require(signature(marker.lstat()) == identity and read_stable(marker, len(raw))[0] == raw, "completion marker changed")
    return {'publication_authorized': False, 'selection_verified': False, 'totals': totals, 'capability': capability}
