"""Separate, bounded original-response namespace; no normalization authority."""
import re
from dataclasses import dataclass

from app_payload_product_evidence_contract import IDENTITY, canonical, fields, identity, require
from app_payload_product_evidence_transport_contract import DeliveryLimits, validate_binding as fact_binding
from app_payload_product_response_journal import MAX_BODY, instant

SCHEMA = 'ar-product-response-evidence-v1'
SCOPE = 'original_http_decoded_utf8_body; not_wire_bytes_or_population_completeness'
CHUNK = 256 * 1024
PROJECTIONS = {'legacy-v1-clean-value-with-official-links', 'legacy-v1-detail-json-with-source-documents'}


@dataclass(frozen=True)
class ResponseLimits(DeliveryLimits):
    # Original-body provenance is richer than normalized fact routing. The
    # measured2966-product index is4.15MB; this raw-only ceiling accommodates
    # expanded captures without changing shard/network/global inflation caps.
    index_raw_bytes: int = 8 * 1024**2

    def validate(self):
        for key, value in self.__dict__.items():
            require(type(value) is int and 0 < value <= getattr(ResponseLimits(), key), 'invalid response budget')


def integer(value, low, high): return type(value) is int and low <= value <= high
def sha(value): return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None
def text(value, maximum=512): return type(value) is str and 0 < len(value) <= maximum


def binding(value):
    fields(value, ('facts', 'journal', 'scope')); fact_binding(value['facts'])
    fields(value['journal'], ('session_id', 'head_digest', 'promotion_manifest_sha256'))
    journal = value['journal']
    require(text(journal['session_id'], 128) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]*', journal['session_id'])
            and sha(journal['head_digest']) and sha(journal['promotion_manifest_sha256']) and value['scope'] == SCOPE,
            'invalid raw response binding')


def asset(value, kind, limits):
    fields(value, ('name', 'sha256', 'bytes', 'decoded_bytes'))
    require(sha(value['sha256']) and value['name'] == f'product-response-{kind}-{value["sha256"]}.json.gz'
            and integer(value['bytes'], 1, getattr(limits, kind + '_compressed_bytes'))
            and integer(value['decoded_bytes'], 1, getattr(limits, kind + '_raw_bytes')), 'invalid response asset')


def capability(value, limits=ResponseLimits()):
    limits.validate(); fields(value, ('schema', 'binding', 'index', 'shards', 'products', 'bodies'))
    require(value['schema'] == SCHEMA, 'unsupported response capability'); binding(value['binding'])
    require(integer(value['products'], 1, 20000) and integer(value['bodies'], 0, 40000), 'invalid response population')
    asset(value['index'], 'index', limits)
    require(type(value['shards']) is list and len(value['shards']) <= limits.shards, 'response shard limit')
    names = set()
    for row in value['shards']:
        asset(row, 'shard', limits); require(row['sha256'] not in names, 'duplicate response shard'); names.add(row['sha256'])
    assets = [value['index'], *value['shards']]
    require(sum(row['bytes'] for row in assets) <= limits.compressed_bytes
            and sum(row['decoded_bytes'] for row in assets) <= limits.raw_bytes
            and len(canonical(value)) <= limits.namespace_bytes, 'response aggregate budget exceeded')


def event(value):
    fields(value, ('sequence', 'event_digest', 'phase', 'completed_at', 'request_version', 'response_version',
                   'provider', 'provider_uid', 'product_id'))
    require(integer(value['sequence'], 1, 100000) and sha(value['event_digest'])
            and value['phase'] in {'product_detail', 'classification_detail', 'products_index'}
            and text(value['provider']) and text(value['provider_uid']), 'invalid response event')
    instant(value['completed_at'])
    require(all(value[key] is None or integer(value[key], 1, 2147483647)
                for key in ('request_version', 'response_version')), 'invalid response version')
    require(value['product_id'] is None if value['phase'] == 'products_index' else text(value['product_id']),
            'response event product identity invalid')


def index(value, cap, limits=ResponseLimits()):
    fields(value, ('schema', 'binding', 'products', 'bodies'))
    require(value['schema'] == SCHEMA and value['binding'] == cap['binding'], 'detached response index')
    require(type(value['products']) is list and len(value['products']) == cap['products']
            and type(value['bodies']) is list and len(value['bodies']) == cap['bodies'], 'response index counts differ')
    shards = {row['sha256']: row for row in cap['shards']}; bodies = {}; positions = set(); event_digests = {}; sequences = {}
    for body in value['bodies']:
        fields(body, ('sha256', 'bytes', 'chunks', 'events'))
        require(sha(body['sha256']) and body['sha256'] not in bodies and integer(body['bytes'], 1, MAX_BODY), 'invalid response body')
        require(type(body['chunks']) is list and 0 < len(body['chunks']) <= 256
                and type(body['events']) is list and 0 < len(body['events']) <= 100000, 'response body routing bounds')
        events = set()
        for ref in body['events']:
            event(ref); require(ref['event_digest'] not in events, 'duplicate response event'); events.add(ref['event_digest'])
            require(event_digests.setdefault(ref['event_digest'], (ref['sequence'], body['sha256'])) == (ref['sequence'], body['sha256'])
                    and sequences.setdefault(ref['sequence'], (ref['event_digest'], body['sha256'])) == (ref['event_digest'], body['sha256']),
                    'response event reused across bodies')
        offset, selected = 0, set()
        for chunk in body['chunks']:
            fields(chunk, ('shard', 'page', 'offset', 'bytes'))
            require(chunk['shard'] in shards and integer(chunk['page'], 0, 19999)
                    and integer(chunk['offset'], 0, MAX_BODY) and chunk['offset'] == offset
                    and integer(chunk['bytes'], 1, CHUNK), 'invalid response chunk route')
            position = chunk['shard'], chunk['page']; require(position not in positions, 'duplicate response chunk route')
            positions.add(position); selected.add(chunk['shard']); offset += chunk['bytes']
        require(offset == body['bytes'], 'response body byte count differs')
        require(sum(shards[s]['bytes'] for s in selected) <= limits.product_compressed_bytes
                and sum(shards[s]['decoded_bytes'] for s in selected) <= limits.product_raw_bytes, 'response body acquisition budget')
        bodies[body['sha256']] = body
    keys, used = set(), set()
    for product in value['products']:
        _product(product, bodies, keys, used)
    require(used == set(bodies) and {p[0] for p in positions} == set(shards), 'unrouted response evidence')
    require(len(canonical(value)) <= limits.index_raw_bytes, 'response index exceeds decoded budget')


def _product(product, bodies, keys, used):
    fields(product, ('identity', 'provider_uid', 'state', 'current_body_sha256', 'details', 'indexes', 'reasons', 'projection'))
    fields(product['identity'], IDENTITY); key = identity(product['identity'])['product_key']
    require(key not in keys and text(product['provider_uid']), 'invalid response product identity'); keys.add(key)
    require(product['projection'] in {'known-exact-projections', 'unsupported'}, 'unsupported response projection')
    require(type(product['reasons']) is list and len(product['reasons']) <= 32
            and all(text(reason, 128) for reason in product['reasons'])
            and len(set(product['reasons'])) == len(product['reasons']), 'invalid response reasons')
    require(type(product['details']) is list and type(product['indexes']) is list, 'invalid response references')
    seen, matched = set(), []
    for detail in product['details']:
        fields(detail, ('sha256', 'matches_export', 'projection_variants'))
        require(type(detail['matches_export']) is bool and type(detail['projection_variants']) is list
                and len(set(detail['projection_variants'])) == len(detail['projection_variants'])
                and set(detail['projection_variants']) <= PROJECTIONS
                and bool(detail['projection_variants']) == detail['matches_export'], 'invalid response projection proof')
        if detail['matches_export']: matched.append(detail['sha256'])
        _reference(detail['sha256'], product, bodies, seen, used, detail=True)
    seen = set()
    for checksum in product['indexes']: _reference(checksum, product, bodies, seen, used, detail=False)
    expected = ('matched' if len(matched) == 1 else 'ambiguous' if len(matched) > 1 else 'projection_unverified'
                if product['details'] else 'index_only' if product['indexes'] else 'missing')
    require(product['state'] == expected and product['current_body_sha256'] == (matched[0] if len(matched) == 1 else None),
            'response current-body claim differs from evidence')
    require(product['projection'] != 'unsupported' or not matched, 'unsupported projection claims match')


def _reference(checksum, product, bodies, seen, used, *, detail):
    require(sha(checksum) and checksum in bodies and checksum not in seen, 'unknown or repeated response body')
    seen.add(checksum); used.add(checksum)
    identity = product['identity']
    require(any(e['provider'] == identity['provider'] and e['provider_uid'] == product['provider_uid']
                and ((e['phase'] in {'product_detail', 'classification_detail'} and e['product_id'] == identity['product_id'])
                     if detail else e['phase'] == 'products_index') for e in bodies[checksum]['events']),
            'response body event has another product/provider')


def shard(value, cap):
    fields(value, ('schema', 'binding', 'pages'))
    require(value['schema'] == SCHEMA and value['binding'] == cap['binding']
            and type(value['pages']) is list and 0 < len(value['pages']) <= 20000, 'invalid response shard')
    for page in value['pages']:
        fields(page, ('sha256', 'offset', 'bytes', 'text'))
        require(sha(page['sha256']) and integer(page['offset'], 0, MAX_BODY)
                and integer(page['bytes'], 1, CHUNK) and type(page['text']) is str
                and len(page['text'].encode('utf-8')) == page['bytes'], 'invalid response chunk bytes')
