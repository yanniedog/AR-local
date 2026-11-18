"""Prepare and verify immutable original-body chunks; no publication side effects."""
import hashlib
import os
from pathlib import Path

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require
from app_payload_product_evidence_delivery_check import asset as read_asset, read_stable, signature
from app_payload_product_evidence_transport import Packer, compressed, durable_create
import app_payload_product_response_contract as contract
from cdr_atomic import _fsync_directory


def utf8_chunks(raw, maximum=contract.CHUNK):
    require(type(maximum) is int and 4 <= maximum <= contract.CHUNK, 'invalid response chunk budget')
    offset = 0
    while offset < len(raw):
        end = min(offset + maximum, len(raw))
        while end < len(raw) and raw[end] & 0xC0 == 0x80: end -= 1
        require(end > offset, 'invalid response UTF-8 boundary')
        piece = raw[offset:end]
        yield offset, piece.decode('utf-8', errors='strict')
        offset = end


class ResponsePacker(Packer):
    def envelope(self, pages): return dict(schema=contract.SCHEMA, binding=self.binding, pages=pages)

    def asset(self, kind, raw, blob=None):
        self.check()
        require(len(raw) <= getattr(self.limits, kind + '_raw_bytes'), 'response decoded asset budget')
        blob = compressed(raw) if blob is None else blob
        require(len(blob) <= getattr(self.limits, kind + '_compressed_bytes'), 'response compressed asset budget')
        self.raw_bytes += len(raw); self.compressed_bytes += len(blob)
        require(self.raw_bytes <= self.limits.raw_bytes and self.compressed_bytes <= self.limits.compressed_bytes,
                'response aggregate asset budget')
        checksum = digest(blob); name = f'product-response-{kind}-{checksum}.json.gz'
        durable_create(self.output / name, blob)
        return dict(name=name, sha256=checksum, bytes=len(blob), decoded_bytes=len(raw))

    def flush_group(self, pages, routes):
        self.check(); value = self.envelope(pages); raw = canonical(value); blob = compressed(raw)
        if len(blob) > self.limits.shard_compressed_bytes:
            require(len(pages) > 1, 'single response chunk exceeds compressed budget')
            middle = len(pages) // 2
            self.flush_group(pages[:middle], routes[:middle]); self.flush_group(pages[middle:], routes[middle:]); return
        require(len(self.shards) < self.limits.shards, 'response shard count exceeded')
        contract.shard(value, {'binding': self.binding}); descriptor = self.asset('shard', raw, blob)
        self.shards.append(descriptor)
        for position, (route, page) in enumerate(zip(routes, pages)):
            route['chunks'].append(dict(shard=descriptor['sha256'], page=position, offset=page['offset'], bytes=page['bytes']))


def routes(source):
    products, bodies = [], {}
    for item in source.products():
        source.budget.check()
        for value in [*item['details'], *item['indexes']]:
            body = bodies.setdefault(value['sha256'], dict(sha256=value['sha256'], bytes=value['bytes'], chunks=[], events={}))
            require(body['bytes'] == value['bytes'], 'conflicting original body length')
            for event in value['events']:
                previous = body['events'].setdefault(event['event_digest'], event)
                require(previous == event, 'conflicting original response event')
        products.append({**item, 'details': [{key: value[key] for key in ('sha256', 'matches_export', 'projection_variants')}
                                           for value in item['details']], 'indexes': [value['sha256'] for value in item['indexes']]})
        require(len(products) <= 20000 and len(bodies) <= 40000, 'response route population budget')
    for body in bodies.values(): body['events'] = sorted(body['events'].values(), key=lambda e: (e['sequence'], e['event_digest']))
    return products, [bodies[key] for key in sorted(bodies)]


def pack_responses(source, output, *, limits=contract.ResponseLimits()):
    """Source is already verified/read-only. A failed candidate never replaces output."""
    limits.validate(); output = Path(output).absolute()
    require(not output.exists() and not any(p.is_symlink() for p in (output, *output.parents)), 'unsafe response output')
    inputs = [source.proof.exports, source.snapshot_path.parent, source.contract_path.parent]
    require(all(output != p and p not in output.parents and output not in p.parents for p in inputs), 'overlapping response output')
    binding = dict(facts=source.binding, journal={key: source.proof.pointer[key]
                   for key in ('session_id', 'head_digest', 'promotion_manifest_sha256')}, scope=contract.SCOPE)
    contract.binding(binding)
    products, bodies = routes(source)
    output.mkdir(parents=True, exist_ok=False)
    writer = ResponsePacker(output, binding, limits); writer.deadline = source.budget.deadline
    for body in bodies:
        writer.check(); raw = source.body(body['sha256'])
        require(len(raw) == body['bytes'] and digest(raw) == body['sha256'], 'response source body changed')
        for offset, text in utf8_chunks(raw):
            writer.append(body, dict(sha256=body['sha256'], offset=offset, bytes=len(text.encode('utf-8')), text=text))
    writer.flush()
    index = dict(schema=contract.SCHEMA, binding=binding, products=products, bodies=bodies)
    cap = dict(schema=contract.SCHEMA, binding=binding, index=writer.asset('index', canonical(index)), shards=writer.shards,
               products=len(products), bodies=len(bodies))
    contract.capability(cap, limits); contract.index(index, cap, limits)
    verify_assets(output, cap, limits=limits, check=writer.check)
    source.recheck(); writer.check()
    result = dict(publication_authorized=False, selection_verified=False, capability=cap)
    pending = output / 'prepared.pending'; durable_create(pending, canonical(result) + b'\n'); _fsync_directory(output)
    os.link(pending, output / 'prepared.json'); _fsync_directory(output); pending.unlink(); _fsync_directory(output)
    return result


def verify_assets(root, cap, *, limits=contract.ResponseLimits(), check=None):
    import time
    deadline = time.monotonic() + 600
    if check is None: check = lambda: require(time.monotonic() < deadline, 'response readback deadline exceeded')
    contract.capability(cap, limits); root = Path(root).absolute(); identities = {}
    index = read_asset(root, cap['index'], identities); contract.index(index, cap, limits)
    positions = {}; expected = {}
    for body in index['bodies']:
        expected[body['sha256']] = body['bytes']
        for chunk in body['chunks']: positions[chunk['shard'], chunk['page']] = (body['sha256'], chunk['offset'], chunk['bytes'])
    hashes, offsets, completed = {}, {}, set()
    for descriptor in cap['shards']:
        check(); shard = read_asset(root, descriptor, identities); contract.shard(shard, cap)
        for position, chunk in enumerate(shard['pages']):
            check(); sha = chunk['sha256']; raw = chunk['text'].encode('utf-8')
            require(positions.pop((descriptor['sha256'], position), None) == (sha, chunk['offset'], len(raw)),
                    'unrouted or detached response chunk')
            require(sha not in completed and offsets.get(sha, 0) == chunk['offset'], 'response body chunks out of order')
            hashes.setdefault(sha, hashlib.sha256()).update(raw); offsets[sha] = chunk['offset'] + len(raw)
            if offsets[sha] == expected[sha]:
                require(hashes.pop(sha).hexdigest() == sha, 'original response body digest mismatch')
                completed.add(sha); del offsets[sha]
    require(not positions and not hashes and not offsets and completed == set(expected), 'incomplete response bodies')
    for path, before in identities.items(): require(signature(path.lstat()) == before, 'response asset changed after readback')
    check()
    return dict(products=len(index['products']), bodies=len(completed), body_bytes=sum(expected.values()))


def verify_prepared(root, *, expected_binding, limits=contract.ResponseLimits()):
    root = Path(root).absolute(); marker = root / 'prepared.json'
    raw, before = read_stable(marker, limits.namespace_bytes + 1024); value = decode(raw)
    fields(value, ('publication_authorized', 'selection_verified', 'capability'))
    require(value['publication_authorized'] is False and value['selection_verified'] is False, 'invalid response authority')
    cap = value['capability']; contract.capability(cap, limits)
    require(cap['binding'] == expected_binding, 'response binding differs')
    expected_files = {'prepared.json', cap['index']['name'], *(a['name'] for a in cap['shards'])}
    require({p.name for p in root.iterdir()} == expected_files,
            'partial or unexpected response output')
    totals = verify_assets(root, cap, limits=limits)
    require({p.name for p in root.iterdir()} == expected_files, 'response output inventory changed')
    require(signature(marker.lstat()) == before and read_stable(marker, len(raw))[0] == raw, 'response marker changed')
    return dict(publication_authorized=False, selection_verified=False, totals=totals, capability=cap)
