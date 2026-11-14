"""Exact raw response transport, independent from normalized fact reconstruction."""
from copy import deepcopy
from dataclasses import replace
import gzip

import pytest

from app_payload_product_evidence_contract import canonical, decode, digest
from app_payload_product_evidence_transport_contract import DeliveryLimits
from app_payload_product_response_sources import ResponseSources
import app_payload_product_response_transport as subject
from tests.test_app_payload_product_response_sources import real_source, reader


def package(tmp_path):
    values = real_source(tmp_path); source = reader(values); output = tmp_path / 'delivery'
    result = subject.pack_responses(source, output)
    return values, source, output, result


def asset(root, descriptor): return decode(gzip.decompress((root / descriptor['name']).read_bytes()))


def test_every_original_body_is_exact_and_readback_never_claims_publication(tmp_path):
    values, source, output, prepared = package(tmp_path); cap = prepared['capability']
    proof = subject.verify_prepared(output, expected_binding=cap['binding'])
    assert proof['totals']['products'] == 3 and proof['totals']['bodies'] == 6
    assert proof['publication_authorized'] is False and proof['selection_verified'] is False
    index = asset(output, cap['index']); shards = {row['sha256']: asset(output, row) for row in cap['shards']}
    for body in index['bodies']:
        raw = ''.join(shards[c['shard']]['pages'][c['page']]['text'] for c in body['chunks']).encode('utf-8')
        assert raw == source.body(body['sha256']) and len(raw) == body['bytes']
    for raw in values[-1].values(): assert digest(raw) in {b['sha256'] for b in index['bodies']}


def test_multibyte_chunk_boundaries_and_numeric_spelling_are_not_rewritten():
    raw = ('{ "unknown":null,"array":[],"object":{},"empty":"","number":9007199254740993.000,'
           '"text":"' + 'é🙂' * 100000 + '" }\r\n').encode('utf-8')
    chunks = list(subject.utf8_chunks(raw))
    assert len(chunks) > 1 and b''.join(text.encode('utf-8') for _, text in chunks) == raw
    offset = 0
    for position, text in chunks:
        assert position == offset; offset += len(text.encode('utf-8'))
    with pytest.raises(UnicodeError): list(subject.utf8_chunks(b'bad\xff'))


@pytest.mark.parametrize('limit', ['namespace_bytes', 'index_raw_bytes', 'shard_raw_bytes', 'compressed_bytes'])
def test_failure_never_advertises_truncated_body(tmp_path, limit):
    values = real_source(tmp_path); source = reader(values); output = tmp_path / 'delivery'
    with pytest.raises(ValueError): subject.pack_responses(source, output, limits=replace(DeliveryLimits(), **{limit: 1}))
    assert not (output/'prepared.json').exists()


@pytest.mark.parametrize('fault', ['missing', 'corrupt', 'pending', 'wrong-binding'])
def test_missing_or_changed_completion_evidence_cannot_pass(tmp_path, fault):
    _, _, output, value = package(tmp_path); cap = value['capability']; binding = deepcopy(cap['binding'])
    shard = output/cap['shards'][0]['name']
    if fault == 'missing': shard.unlink()
    elif fault == 'corrupt': shard.write_bytes(b'bad')
    elif fault == 'pending': (output/'prepared.pending').write_bytes(b'partial')
    else: binding['journal']['head_digest'] = 'f'*64
    with pytest.raises((ValueError, OSError)): subject.verify_prepared(output, expected_binding=binding)


def test_hash_bound_shards_still_must_reconstruct_original_body_digest(tmp_path):
    _, _, output, value = package(tmp_path); cap = value['capability']; index = asset(output, cap['index'])
    old = cap['shards'][0]; shard = asset(output, old)
    page = shard['pages'][0]; page['text'] = ' ' + page['text'][1:]
    def install(kind, raw):
        blob = subject.compressed(raw); checksum = digest(blob); name = f'product-response-{kind}-{checksum}.json.gz'
        (output/name).write_bytes(blob)
        return dict(name=name, sha256=checksum, bytes=len(blob), decoded_bytes=len(raw))
    changed = install('shard', canonical(shard)); cap['shards'][0] = changed
    for body in index['bodies']:
        for chunk in body['chunks']:
            if chunk['shard'] == old['sha256']: chunk['shard'] = changed['sha256']
    cap['index'] = install('index', canonical(index))
    with pytest.raises(ValueError, match='original response body digest'): subject.verify_assets(output, cap)


def test_raw_index_only_has_independent_eight_mebibyte_decoded_boundary(tmp_path):
    from app_payload_product_response_contract import capability, ResponseLimits
    _, _, _, prepared = package(tmp_path); cap = deepcopy(prepared['capability'])
    cap['index']['decoded_bytes'] = 8 * 1024 * 1024
    capability(cap)
    cap['index']['decoded_bytes'] += 1
    with pytest.raises(ValueError, match='asset'): capability(cap)
    assert ResponseLimits().shard_raw_bytes == 4 * 1024 * 1024
    assert ResponseLimits().index_compressed_bytes == 1024 * 1024
    assert DeliveryLimits().index_raw_bytes == 4 * 1024 * 1024


def test_output_inventory_change_during_readback_is_rejected(tmp_path, monkeypatch):
    _, _, output, prepared = package(tmp_path)
    original = subject.read_asset
    def changed(*args):
        value = original(*args)
        (output/'late-extra').write_bytes(b'not bound')
        return value
    monkeypatch.setattr(subject, 'read_asset', changed)
    with pytest.raises(ValueError, match='inventory changed'):
        subject.verify_prepared(output, expected_binding=prepared['capability']['binding'])
