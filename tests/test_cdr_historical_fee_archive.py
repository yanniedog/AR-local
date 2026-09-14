"""Transport protocol tests; synthetic tar bytes are not banking acceptance."""
from __future__ import annotations

import copy
import io
import tarfile
from pathlib import Path

import pytest
import zstandard

from cdr_historical_fee_archive import Budget, inspect_archive, safe_member
from cdr_historical_fee_exact import sha


def archive(tmp_path, entries=None, *, suffix=b'', compressed_suffix=b''):
    entries = entries or [('data/export.json', b'{"protocol":true}'), ('data/ignored.sqlite', b'not a database')]
    target = io.BytesIO()
    files = []
    with tarfile.open(fileobj=target, mode='w', format=tarfile.PAX_FORMAT) as stream:
        for name, body in entries:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            stream.addfile(info, io.BytesIO(body))
            files.append({'path': name, 'size': len(body), 'type': 'file', 'sha256': sha(body)})
    body = zstandard.ZstdCompressor(write_checksum=True).compress(target.getvalue() + suffix) + compressed_suffix
    (tmp_path / 'original').mkdir(exist_ok=True)
    path = tmp_path / 'original/protocol.tar.zst'
    path.write_bytes(body)
    return path, {'bytes': len(body), 'sha256': sha(body)}, files


def read(tmp_path, entries=None, **kwargs):
    path, identity, files = archive(tmp_path, entries, **kwargs)
    return inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())


def test_regular_selected_only_and_exact_resume(tmp_path):
    path, identity, files = archive(tmp_path)
    first = inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())
    assert set(first['selected']) == {'source'} and first['regular_files'] == 2
    assert (tmp_path / 'cache/source.bin').read_bytes() == b'{"protocol":true}'
    assert not list((tmp_path / 'cache').glob('*.sqlite'))
    before = {p.name: p.read_bytes() for p in (tmp_path / 'cache').iterdir()}
    inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())
    assert before == {p.name: p.read_bytes() for p in (tmp_path / 'cache').iterdir()}


@pytest.mark.parametrize('name', ['../x', '/x', 'C:/x', 'a\\b', 'a//b', './x', 'a/../x', 'a:ads'])
def test_unsafe_member_names_refused(name):
    with pytest.raises(ValueError):
        safe_member(name)


@pytest.mark.parametrize('kind', ['duplicate', 'casefold', 'extra', 'hash', 'size'])
def test_member_inventory_or_value_tampering_refused(tmp_path, kind):
    path, identity, files = archive(tmp_path, [('data/export.json', b'{}'), ('data/EXPORT.json' if kind == 'casefold' else 'data/export.json', b'{}')]
                                    if kind in ('duplicate', 'casefold') else None)
    if kind == 'extra':
        files = files[:1]
    if kind == 'hash':
        files[0]['sha256'] = '0' * 64
    if kind == 'size':
        files[0]['size'] += 1
    with pytest.raises(ValueError):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())
    assert not (tmp_path / 'cache/receipt.json').exists()


@pytest.mark.parametrize('suffix', [b'x' * 512, b'\x00', b'\x00' * 511 + b'x'])
def test_tar_trailing_nonpadding_or_partial_record_refused(tmp_path, suffix):
    with pytest.raises(ValueError):
        read(tmp_path, suffix=suffix)


@pytest.mark.parametrize('suffix', [b'garbage', zstandard.ZstdCompressor().compress(b'')])
def test_zstd_trailing_content_or_second_frame_refused(tmp_path, suffix):
    with pytest.raises(ValueError):
        read(tmp_path, compressed_suffix=suffix)


def test_wrong_container_hash_and_deadline_preserve_unsealed_output(tmp_path):
    path, identity, files = archive(tmp_path)
    identity['sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='container'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())
    with pytest.raises(ValueError, match='deadline'):
        Budget(deadline=0).check()


def test_partial_cache_is_not_resumed_or_overwritten(tmp_path):
    path, identity, files = archive(tmp_path)
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'source.bin').write_bytes(b'unknown earlier attempt')
    with pytest.raises(ValueError, match='cache'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, cache, Budget())
    assert (cache / 'source.bin').read_bytes() == b'unknown earlier attempt'


def raw_archive(tmp_path, raw, files):
    (tmp_path / 'original').mkdir(exist_ok=True)
    path = tmp_path / 'original/transport.tar.zst'
    body = zstandard.ZstdCompressor(write_checksum=True).compress(raw)
    path.write_bytes(body)
    return path, {'bytes': len(body), 'sha256': sha(body)}, files


def tar_item(name, body=b'', *, kind=tarfile.REGTYPE, link=''):
    info = tarfile.TarInfo(name)
    info.type, info.linkname, info.size = kind, link, len(body)
    return info.tobuf(format=tarfile.USTAR_FORMAT) + body + b'\0' * (-len(body) % 512)


def pax(key, value):
    text = ' ' + key + '=' + value + '\n'
    size = len(text) + 1
    while len(str(size) + text) != size:
        size = len(str(size) + text)
    return (str(size) + text).encode()


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.GNUTYPE_SPARSE, tarfile.GNUTYPE_LONGNAME, tarfile.XGLTYPE])
def test_nonregular_or_global_override_members_refused(tmp_path, kind):
    raw = tar_item('data/export.json', kind=kind, link='../elsewhere') + b'\0' * 1024
    files = [{'path': 'data/export.json', 'size': 0, 'sha256': sha(b''), 'type': 'file'}]
    path, identity, files = raw_archive(tmp_path, raw, files)
    with pytest.raises(ValueError, match='inventory'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())


@pytest.mark.parametrize('headers,accepted', [
    (pax('mtime', '123.456'), True),
    (pax('path', 'data/export.json'), True),
    (pax('path', 'data/other.json'), False),
    (pax('mtime', '123') + pax('mtime', '456'), False),
    (pax('GNU.sparse.size', '10000'), False),
    (b'999 path=x\n', False),
])
def test_serialized_pax_scope_and_length_boundaries(tmp_path, headers, accepted):
    raw = tar_item('pax', headers, kind=tarfile.XHDTYPE) + tar_item('data/export.json', b'{}') + b'\0' * 1024
    files = [{'path': 'data/export.json', 'size': 2, 'sha256': sha(b'{}'), 'type': 'file'}]
    path, identity, files = raw_archive(tmp_path, raw, files)
    if accepted:
        assert inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())['status'] == 'MEMBER_VERIFIED'
    else:
        with pytest.raises(ValueError, match='pax'):
            inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())


@pytest.mark.parametrize('kind', ['compressed', 'decoded', 'headers', 'output'])
def test_shared_actual_work_budget_not_reset_between_phases(tmp_path, kind):
    path, identity, files = archive(tmp_path)
    budget = Budget()
    budget.limits[kind] = 1
    with pytest.raises(ValueError, match=kind + '_bound'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', budget)
    assert not (tmp_path / 'cache/receipt.json').exists()


def test_pax_metadata_limit_precedes_body_allocation(tmp_path):
    info = tarfile.TarInfo('pax')
    info.size, info.type = 1024**2 + 1, tarfile.XHDTYPE
    path, identity, files = raw_archive(tmp_path, info.tobuf() + b'\0' * 1024,
        [{'path': 'data/export.json', 'size': 0, 'sha256': sha(b''), 'type': 'file'}])
    with pytest.raises(ValueError, match='metadata_bound'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())


def test_unsafe_pax_header_name_refused(tmp_path):
    raw = tar_item('../pax', pax('mtime', '123'), kind=tarfile.XHDTYPE) + tar_item('data/export.json', b'{}') + b'\0' * 1024
    files = [{'path': 'data/export.json', 'size': 2, 'sha256': sha(b'{}'), 'type': 'file'}]
    path, identity, files = raw_archive(tmp_path, raw, files)
    with pytest.raises(ValueError, match='unsafe_archive_member_path'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())


def test_multiblock_unknown_zstd_size_like_streaming_producer(tmp_path):
    body = bytes(range(256)) * 2048
    raw = tar_item('data/export.json', body) + b'\0' * 1024
    path, _, files = raw_archive(tmp_path, raw, [{'path': 'data/export.json', 'size': len(body), 'sha256': sha(body), 'type': 'file'}])
    encoded = zstandard.ZstdCompressor(write_content_size=False, write_checksum=True).compress(raw)
    path.write_bytes(encoded)
    identity = {'bytes': len(encoded), 'sha256': sha(encoded)}
    record = inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())
    assert record['selected']['source']['sha256'] == sha(body)


def test_bad_zstd_content_checksum_never_seals_cache(tmp_path):
    path, _, files = archive(tmp_path)
    encoded = path.read_bytes()
    encoded = encoded[:-1] + bytes([encoded[-1] ^ 1])
    path.write_bytes(encoded)
    with pytest.raises(zstandard.ZstdError):
        inspect_archive(path, {'bytes': len(encoded), 'sha256': sha(encoded)}, files,
                        {'source': files[0]['path']}, tmp_path / 'cache', Budget())
    assert not (tmp_path / 'cache/receipt.json').exists()


def test_declared_source_over_256mib_refused_without_allocation(tmp_path):
    path, identity, files = archive(tmp_path)
    files[0]['size'] = 256 * 1024**2 + 1
    with pytest.raises(ValueError, match='selected_member_bound'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, tmp_path / 'cache', Budget())
    assert not (tmp_path / 'cache').exists()


def test_second_member_failure_preserves_first_unsealed_file(tmp_path):
    path, identity, files = archive(tmp_path)
    files[1]['sha256'] = 'f' * 64
    selected = {'source': files[0]['path'], 'second': files[1]['path']}
    with pytest.raises(ValueError, match='selected_member_hash'):
        inspect_archive(path, identity, files, selected, tmp_path / 'cache', Budget())
    assert (tmp_path / 'cache/source.bin').read_bytes() == b'{"protocol":true}'
    assert not (tmp_path / 'cache/receipt.json').exists()
    with pytest.raises(ValueError, match='partial_cache'):
        inspect_archive(path, identity, files, selected, tmp_path / 'cache', Budget())


@pytest.mark.parametrize('fault', ['bytes', 'unknown_file', 'receipt'])
def test_cache_resume_refuses_tampering_without_overwrite(tmp_path, fault):
    from cdr_historical_fee_exact import decode, encode
    path, identity, files = archive(tmp_path)
    cache = tmp_path / 'cache'
    inspect_archive(path, identity, files, {'source': files[0]['path']}, cache, Budget())
    if fault == 'bytes':
        (cache / 'source.bin').write_bytes(b'{"protocol":null}')
    elif fault == 'unknown_file':
        (cache / 'unrelated.txt').write_bytes(b'preserve')
    else:
        receipt = decode((cache / 'receipt.json').read_bytes())
        receipt['regular_files'] = 0
        (cache / 'receipt.json').write_bytes(encode(receipt))
    before = {p.name: p.read_bytes() for p in cache.iterdir()}
    with pytest.raises(ValueError):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, cache, Budget())
    assert before == {p.name: p.read_bytes() for p in cache.iterdir()}


@pytest.mark.parametrize('timestamp,accepted', [
    ('2026-05-21T14:00:00Z', True), ('2026-05-22T23:59:59+10:00', True),
    ('2026-05-21T13:59:59Z', False), ('2026-05-22T14:00:00Z', False),
    ('2026-05-22T12:00:00', False), ('2026-06-09T03:41:57Z', False), (None, False),
])
def test_source_hobart_observation_not_public_generation_or_import(timestamp, accepted):
    from cdr_historical_fee_archive_admission import source_generation
    source = {'sector': 'banks', 'run_date': '2026-05-22', 'generated_at': timestamp}
    if accepted:
        assert source_generation(source) == timestamp
    else:
        with pytest.raises(ValueError, match='WITHHELD_GENERATION_BINDING'):
            source_generation(source)


def test_exact_retained_fee_transform_unchanged_with_budget_callbacks():
    from cdr_historical_fee_embedded import transform
    from cdr_historical_fee_exact import decode, exact
    fixture = Path(__file__).parent / 'fixtures/historical-fees-may13/embedded-excerpt.json'
    body = fixture.read_bytes()
    assert sha(body) == '9e4bc07d29cc32e21d28db638f9298d351f252f121fd44f8c94ef0e4521f8541'
    retained = decode(body)
    before = copy.deepcopy(retained)
    original = transform(retained['source'], retained['core'], retained['details'])
    calls = []
    checked = transform(retained['source'], retained['core'], retained['details'], checkpoint=lambda: calls.append(1))
    assert len(calls) > 100
    assert exact(original, checked) and exact(before, retained)
    with pytest.raises(ValueError, match='deadline'):
        transform(retained['source'], retained['core'], retained['details'], checkpoint=Budget(deadline=0).check)
    assert exact(before, retained)


def test_output_collision_and_source_overlap_are_preserved(tmp_path):
    from cdr_historical_fee_archive_candidate import separate_output
    existing = tmp_path / 'existing'
    existing.mkdir()
    (existing / 'unrelated').write_bytes(b'keep')
    with pytest.raises(ValueError, match='collision'):
        separate_output(existing, [])
    with pytest.raises(ValueError, match='separate'):
        separate_output(existing / 'nested', [existing])
    assert (existing / 'unrelated').read_bytes() == b'keep'
    (tmp_path / 'detour').mkdir()
    with pytest.raises(ValueError, match='separate'):
        separate_output(tmp_path / 'detour/../existing/nested', [existing])


def test_read_only_file_replacement_is_detected(tmp_path):
    from cdr_historical_fee_archive import stable_file
    path = tmp_path / 'source.json'
    path.write_bytes(b'{}')
    with pytest.raises(ValueError, match='changed'):
        with stable_file(path) as stream:
            assert stream.read() == b'{}'
            path.write_bytes(b'{"changed":true}')


def test_generation_failure_writes_only_unsealed_private_disposition(tmp_path, monkeypatch):
    import cdr_historical_fee_archive_candidate as candidate
    for name in ('original', 'anchor', 'private'):
        (tmp_path / name).mkdir()
    original = tmp_path / 'original/unrelated.txt'
    original.write_bytes(b'preserve')
    def fail_load(*args):
        raise ValueError('WITHHELD_GENERATION_BINDING:protocol-injected')
    monkeypatch.setattr(candidate, 'load', fail_load)
    output = tmp_path / 'private/candidate'
    with pytest.raises(ValueError, match='WITHHELD_GENERATION_BINDING'):
        candidate.prepare(tmp_path / 'original', tmp_path / 'anchor', tmp_path / 'private/cache', output)
    assert {p.name for p in output.iterdir()} == {'01-listed.json', 'withheld.json'}
    assert original.read_bytes() == b'preserve'
    with pytest.raises(ValueError, match='collision'):
        candidate.prepare(tmp_path / 'original', tmp_path / 'anchor', tmp_path / 'private/cache', output)


def schema_protocol_value(spec):
    """Required-key transport object only; contains no bank/product/rate examples."""
    if 'const' in spec:
        return spec['const']
    if spec.get('type') == 'object':
        return {key: schema_protocol_value(value) for key, value in spec.get('properties', {}).items()}
    if spec.get('type') == 'integer':
        return 0
    if spec.get('format') == 'date-time':
        return '2026-05-22T00:00:00Z'
    if 'pattern' in spec:
        return '0' * 64 if '64' in spec['pattern'] else 'source.bin'
    if isinstance(spec.get('type'), list):
        return None
    return 'protocol'


@pytest.mark.parametrize('fault', ['none', 'unknown', 'raw', 'complete', 'parent', 'date', 'nested_extra'])
def test_strict_admission_schema_rejects_new_authority_claims(fault):
    import jsonschema
    from cdr_historical_fee_archive_candidate import validate_admission
    from cdr_historical_fee_exact import decode
    schema = decode((Path(__file__).parents[1] / 'contracts/historical-fees/archive-export-v1.schema.json').read_bytes())
    record = schema_protocol_value(schema)
    if fault == 'none':
        validate_admission(record)
        return
    if fault == 'unknown':
        record['upload_profile'] = True
    elif fault == 'raw':
        record['evidence_kind'] = 'original_http_response'
    elif fault == 'complete':
        record['calculation_completeness'] = 'COMPLETE'
    elif fault == 'parent':
        record['parent_kind'] = 'unreviewed_candidate'
    elif fault == 'date':
        record['observation_date'] = '2026-05-31'
    else:
        record['container']['archive']['raw_sha256'] = '0' * 64
    with pytest.raises(jsonschema.ValidationError):
        validate_admission(record)


def test_real_retained_payload_writer_invariance_without_archive_or_admission():
    from cdr_historical_fee_archive_candidate import _payloads
    from cdr_historical_fee_embedded import transform
    from cdr_historical_fee_exact import decode, encode, exact, gzip_bytes
    fixture = Path(__file__).parent / 'fixtures/historical-fees-may13/embedded-excerpt.json'
    retained = decode(fixture.read_bytes())
    core_bytes = gzip_bytes(encode(retained['core']))
    loaded = {'source': retained['source'], 'core': retained['core'], 'details': retained['details'], 'core_bytes': core_bytes}
    payloads, audit = _payloads(loaded, Budget())
    expected, expected_audit = transform(retained['source'], retained['core'], retained['details'])
    assert payloads['core.json.gz'] == core_bytes
    assert exact(decode(payloads['details-candidate.json.gz'], compressed=True), expected)
    assert exact(audit, expected_audit)
    assert 'admission.json' not in payloads


def protocol_candidate_writer(tmp_path, monkeypatch, budget):
    """Real output/seal protocol only; no banking admission is simulated."""
    import cdr_historical_fee_archive_candidate as candidate
    for name in ('original', 'anchor', 'private'):
        (tmp_path / name).mkdir(exist_ok=True)
    monkeypatch.setattr(candidate, 'Budget', lambda: budget)
    monkeypatch.setattr(candidate, 'load', lambda *args: {'container': {}})
    monkeypatch.setattr(candidate, '_payloads', lambda *args: ({'protocol.json': b'{}'}, {'products': []}))
    monkeypatch.setattr(candidate, '_admission', lambda *args: {'admission_id': '0' * 64, 'protocol_only': True})
    monkeypatch.setattr(candidate, 'recheck_inputs', lambda *args: None)
    output = tmp_path / 'private/output'
    return output, lambda: candidate.prepare(tmp_path / 'original', tmp_path / 'anchor', tmp_path / 'private/cache', output)


@pytest.mark.parametrize('which', ['cache', 'candidate'])
@pytest.mark.parametrize('fault', ['fsync_failure', 'fsync_deadline'])
def test_seal_fsync_failure_or_deadline_never_exposes_final_receipt(tmp_path, monkeypatch, which, fault):
    import cdr_historical_fee_archive as reader
    import cdr_historical_fee_archive_candidate as candidate
    budget = Budget()
    if which == 'candidate':
        output, operation = protocol_candidate_writer(tmp_path, monkeypatch, budget)
    else:
        path, identity, files = archive(tmp_path)
        output = tmp_path / 'cache'
        operation = lambda: inspect_archive(path, identity, files, {'source': files[0]['path']}, output, budget)
    original_write, original_sync, at_seal = reader.write_exclusive, reader.os.fsync, False

    def write(path, body, same_budget):
        nonlocal at_seal
        at_seal = path.name in ('receipt.json', 'receipt.pending.json')
        try:
            return original_write(path, body, same_budget)
        finally:
            at_seal = False

    def fsync(fd):
        original_sync(fd)
        if at_seal:
            if fault == 'fsync_failure':
                raise OSError('protocol final fsync failure')
            budget.deadline = 0

    monkeypatch.setattr(reader, 'write_exclusive', write)
    monkeypatch.setattr(candidate, 'write_exclusive', write)
    monkeypatch.setattr(reader.os, 'fsync', fsync)
    with pytest.raises((OSError, ValueError), match='fsync|deadline'):
        operation()
    assert not (output / 'receipt.json').exists()
    assert (output / 'receipt.pending.json').is_file()


@pytest.mark.parametrize('collision', ['receipt.json', 'receipt.pending.json'])
def test_seal_collision_never_replaces_or_removes_unknown_file(tmp_path, collision):
    from cdr_historical_fee_archive import seal_exclusive
    existing = tmp_path / collision
    existing.write_bytes(b'unknown prior content')
    with pytest.raises(FileExistsError):
        seal_exclusive(tmp_path / 'receipt.json', b'{"protocol":true}', Budget())
    assert existing.read_bytes() == b'unknown prior content'
    if collision == 'receipt.pending.json':
        assert not (tmp_path / 'receipt.json').exists()


def test_pending_replacement_before_link_is_refused_and_preserved(tmp_path, monkeypatch):
    import cdr_historical_fee_archive as reader
    original = reader.write_exclusive

    def replace_after_write(path, body, budget):
        identity = original(path, body, budget)
        path.rename(tmp_path / 'preserved-original.pending')
        path.write_bytes(body)  # Same bytes do not authorize a different file identity.
        return identity

    monkeypatch.setattr(reader, 'write_exclusive', replace_after_write)
    with pytest.raises(ValueError, match='pending_seal_identity_changed'):
        reader.seal_exclusive(tmp_path / 'receipt.json', b'{"protocol":true}', Budget())
    assert not (tmp_path / 'receipt.json').exists()
    assert (tmp_path / 'receipt.pending.json').read_bytes() == b'{"protocol":true}'
    assert (tmp_path / 'preserved-original.pending').read_bytes() == b'{"protocol":true}'


@pytest.mark.parametrize('name', ['receipt.json', 'receipt.pending.json'])
def test_cache_resume_requires_original_pending_and_final_hardlink(tmp_path, name):
    path, identity, files = archive(tmp_path)
    output = tmp_path / 'cache'
    inspect_archive(path, identity, files, {'source': files[0]['path']}, output, Budget())
    target = output / name
    body = target.read_bytes()
    target.rename(output / 'preserved-original')
    target.write_bytes(body)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(ValueError, match='hardlink_identity_mismatch'):
        inspect_archive(path, identity, files, {'source': files[0]['path']}, output, Budget())
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_successful_seal_retains_pending_and_visibility_is_no_replace_link(tmp_path):
    import os
    from cdr_historical_fee_archive import seal_exclusive
    final = tmp_path / 'receipt.json'
    seal_exclusive(final, b'{"protocol":true}', Budget())
    assert final.read_bytes() == b'{"protocol":true}'
    assert os.path.samefile(final, tmp_path / 'receipt.pending.json')
