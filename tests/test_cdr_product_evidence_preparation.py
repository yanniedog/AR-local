"""Trusted-writer/pinned adoption using captured facts and literal response bodies."""
from dataclasses import replace
from pathlib import Path
import pytest

from app_payload_product_evidence_contract import canonical, digest
from app_payload_product_evidence_transport import pack_snapshot
from app_payload_product_response_sources import ResponseSources
from app_payload_product_response_transport import pack_responses
from cdr_product_evidence_delivery_policy import MalformedReady, apply_status, STATUS
from cdr_product_evidence_preparation import prepare_source_snapshot, adopt_prepared, _checked_snapshot
from cdr_product_evidence_source import SourceUnavailable
from tests.product_evidence_finalized_fixture import finalized, open_source, WRITER, FACTS, RESPONSES, ENABLED


@pytest.fixture
def prepared(tmp_path):
    fixture = finalized(tmp_path); source = open_source(fixture)
    snapshot = prepare_source_snapshot(source, tmp_path / 'new-snapshot', writer_revision=WRITER)
    binding = _checked_snapshot(source, snapshot, WRITER)
    facts = tmp_path / 'facts'; raw = tmp_path / 'responses'
    pack_snapshot(snapshot.root, facts, expected_source=binding['source'], core_sha256=binding['core_sha256'],
                  details_sha256=binding['details_sha256'])
    pack_responses(ResponseSources(snapshot.root, source.exports, source.contract_path, expected_binding=binding), raw)
    packages = {lane: dict(root=root, sha256=digest((root / 'prepared.json').read_bytes()))
                for lane, root in ((FACTS, facts), (RESPONSES, raw))}
    return fixture, source, snapshot, packages


def test_real_captured_facts_and_raw_adopt_without_relabeling_diagnostics(prepared, monkeypatch):
    fixture, source, snapshot, packages = prepared
    before = {p: p.read_bytes() for p in fixture['state'].parent.rglob('*') if p.is_file()}
    markers = {p: p.read_bytes() for p in [snapshot.root / 'snapshot.json', *(Path(v['root']) / 'prepared.json' for v in packages.values())]}
    from cdr_file_lock import FileLock
    def forbidden(*args, **kwargs): pytest.fail('adoption wrote files or took write lock')
    monkeypatch.setattr(FileLock, '__enter__', forbidden); monkeypatch.setattr(Path, 'write_bytes', forbidden)
    candidate = adopt_prepared(source, snapshot, ENABLED, packages, writer_revision=WRITER, expected_preparation_sha256=snapshot.sha256)
    assert source.budget.phase == 5  # Constructor + prepare pre/post + adoption pre/post.
    value = candidate.document(); manifest = apply_status(source.base, ENABLED, value['lanes'])
    assert value['writer_revision'] == WRITER and value['publication_authorized'] is False
    assert all(manifest[STATUS]['lanes'][lane] == dict(state='available', reason='verified') for lane in ENABLED)
    assert manifest['files'] == source.base['files'] and all(lane in manifest for lane in ENABLED)
    receipt = snapshot.document()
    assert receipt['writer_revision'] == WRITER and receipt['contract_normalization'] == 'legacy-v1'
    assert receipt['fact_normalization'] and receipt['selection_verified'] is False and receipt['publication_authorized'] is False
    assert {p: p.read_bytes() for p in before} == before
    assert {p: p.read_bytes() for p in markers} == markers


def test_missing_preparation_is_explicit_pending_with_financial_assets_unchanged(prepared):
    fixture, source, snapshot, packages = prepared
    partial = adopt_prepared(source, snapshot, ENABLED, {FACTS: packages[FACTS]}, writer_revision=WRITER, expected_preparation_sha256=snapshot.sha256).document()
    assert partial['lanes'][RESPONSES] == dict(state='pending', reason='not_prepared')
    assert partial['lanes'][FACTS]['state'] == 'available'
    assert RESPONSES not in apply_status(source.base, ENABLED, partial['lanes'])
    pending = adopt_prepared(open_source(fixture), snapshot, ENABLED, {}, writer_revision=WRITER, expected_preparation_sha256=snapshot.sha256).document()
    assert all(v['state'] == 'pending' for v in pending['lanes'].values())
    assert adopt_prepared(None, None, (), {}, writer_revision=WRITER, expected_preparation_sha256=None) is None


@pytest.mark.parametrize('fault', ['pin', 'missing-marker', 'changed-shard', 'wrong-core', 'deep-json'])
def test_supplied_ready_package_corruption_is_fatal(prepared, fault):
    _, source, snapshot, packages = prepared; root = Path(packages[FACTS]['root'])
    if fault == 'pin': packages[FACTS]['sha256'] = '0'*64
    elif fault == 'missing-marker': (root / 'prepared.json').unlink()
    elif fault == 'changed-shard':
        shard = next(root.glob('*shard*.gz')); shard.write_bytes(shard.read_bytes()+b'changed')
    elif fault == 'deep-json':
        path = root / 'prepared.json'; path.write_bytes(b'['*2000+b'0'+b']'*2000)
        packages[FACTS]['sha256'] = digest(path.read_bytes())
    else:
        import json
        path = root / 'prepared.json'; marker = json.loads(path.read_bytes())
        marker['capability']['binding']['core_sha256'] = '0'*64
        path.write_bytes(canonical(marker)); packages[FACTS]['sha256'] = digest(path.read_bytes())
    with pytest.raises(MalformedReady): adopt_prepared(source, snapshot, ENABLED, packages, writer_revision=WRITER, expected_preparation_sha256=snapshot.sha256)


@pytest.mark.parametrize('fault', ['writer', 'normalization', 'snapshot', 'selection', 'authority'])
def test_preparation_receipt_cannot_be_rebound_by_new_caller(prepared, fault):
    _, source, snapshot, packages = prepared; value = snapshot.document(); writer = WRITER
    if fault == 'writer': writer = 'b'*40
    elif fault == 'normalization': value['fact_normalization'] = 'different-normalizer'
    elif fault == 'snapshot': value['snapshot_sha256'] = '0'*64
    elif fault == 'selection': value['selection']['pointer_sha256'] = '0'*64
    else: value['publication_authorized'] = True
    modified = replace(snapshot, receipt=canonical(value))
    # Rehashed technical control proves semantic binding, not only byte mismatch.
    with pytest.raises(MalformedReady): adopt_prepared(source, modified, ENABLED, packages, writer_revision=writer, expected_preparation_sha256=modified.sha256)


def test_selected_source_change_after_preparation_never_adopts(prepared):
    fixture, source, snapshot, packages = prepared
    fixture['pointer'].write_bytes(fixture['pointer'].read_bytes()+b' ')
    with pytest.raises(SourceUnavailable): adopt_prepared(source, snapshot, ENABLED, packages, writer_revision=WRITER, expected_preparation_sha256=snapshot.sha256)
    assert (snapshot.root / 'snapshot.json').is_file()


def test_resumed_receipt_needs_external_pin_and_deep_receipt_is_malformed_ready(prepared):
    _, source, snapshot, packages = prepared
    modified = replace(snapshot, receipt=snapshot.receipt+b' ')
    with pytest.raises(MalformedReady): adopt_prepared(source, modified, ENABLED, packages, writer_revision=WRITER, expected_preparation_sha256=snapshot.sha256)
    deep = replace(snapshot, receipt=b'['*2000+b'0'+b']'*2000)
    with pytest.raises(MalformedReady): adopt_prepared(source, deep, ENABLED, packages, writer_revision=WRITER, expected_preparation_sha256=deep.sha256)


def test_receipt_byte_limit_precedes_json_decoding(prepared, monkeypatch):
    import cdr_product_evidence_preparation as preparation
    _, source, snapshot, packages = prepared
    large = replace(snapshot, receipt=b' '*65537)
    monkeypatch.setattr(preparation, '_checked_snapshot', lambda *args: pytest.fail('oversize receipt reached parser'))
    with pytest.raises(MalformedReady): adopt_prepared(source, large, ENABLED, packages, writer_revision=WRITER, expected_preparation_sha256=large.sha256)


def test_source_change_during_preparation_leaves_diagnostic_but_no_receipt(tmp_path, monkeypatch):
    import cdr_product_evidence_preparation as preparation
    fixture = finalized(tmp_path); source = open_source(fixture)
    original = preparation.prepare_snapshot
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        fixture['pointer'].write_bytes(fixture['pointer'].read_bytes()+b' ')
        return result
    monkeypatch.setattr(preparation, 'prepare_snapshot', changed)
    root = tmp_path / 'new-snapshot'
    with pytest.raises(SourceUnavailable): preparation.prepare_source_snapshot(source, root, writer_revision=WRITER)
    import json
    marker = json.loads((root / 'snapshot.json').read_bytes())
    assert marker['publication_authorized'] is False and marker['selection_verified'] is False


def test_new_snapshot_cannot_overwrite_prepared_or_source_output(tmp_path):
    fixture = finalized(tmp_path); source = open_source(fixture)
    root = tmp_path / 'new-snapshot'; prepare_source_snapshot(source, root, writer_revision=WRITER)
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    for output in (root, source.exports / 'inside-source', source.state / 'inside-state'):
        with pytest.raises(ValueError, match='existing or overlapping'): prepare_source_snapshot(open_source(fixture), output, writer_revision=WRITER)
    assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
