"""Report integrity and hostile-text boundaries; not product acceptance fixtures."""
import csv
import gzip
import json
from pathlib import Path

import pytest

from cdr_product_report import digest, generate, leaves, present, read_bundle, write_csv
from cdr_product_report_html import write_html
from cdr_public_history_audit import decode


def test_zero_false_and_explicit_empty_values_remain_distinct():
    assert present(0) and present(False)
    assert not present(None)
    assert dict(leaves({'a/b': {'~key': [0, False, None]}})) == {
        '/a~1b/~0key/0': 0, '/a~1b/~0key/1': False, '/a~1b/~0key/2': None}
    assert dict(leaves({'fees': [], 'metadata': {}})) == {'/fees': [], '/metadata': {}}


def test_csv_cannot_execute_source_formulas_and_keeps_zero(tmp_path):
    target = tmp_path / 'parameters.csv'
    assert write_csv(target, [{'formula': '=1+1', 'zero': 0, 'unknown': None}]) == 1
    with target.open(encoding='utf-8-sig', newline='') as stream:
        assert next(csv.DictReader(stream)) == {'formula': "'=1+1", 'zero': '0', 'unknown': ''}


def test_large_history_export_has_a_lossless_compressed_csv_form(tmp_path):
    path = tmp_path / 'parameters.csv.gz'
    assert write_csv(path, [{'value': '0.0000001', 'unknown': None}]) == 1
    with gzip.open(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == [{'value': '0.0000001', 'unknown': ''}]


def test_source_text_cannot_escape_embedded_json(tmp_path):
    target = tmp_path / 'report.html'
    hostile = '</script><script>alert(1)</script>'
    write_html(target, {'hostile': hostile}, [])
    document = target.read_text(encoding='utf-8')
    assert hostile not in document
    raw = document.split('id="data">', 1)[1].split('</script>', 1)[0]
    assert json.loads(raw)['report']['hostile'] == hostile


def test_output_cannot_replace_or_enter_source_tree(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for output in (source, source / 'report', tmp_path):
        with pytest.raises(ValueError, match='separate'):
            generate(source, output)
    assert list(source.iterdir()) == []


def protocol_bundle(tmp_path, asset_name='core.json.gz'):
    payload = gzip.compress(json.dumps({'run_date': '2026-09-14'}).encode())
    manifest = {'run_date': '2026-09-14', 'files': {'core': {
        'name': asset_name, 'bytes': len(payload), 'sha256': digest(payload), 'url': 'https://example.org/core'}}}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return payload


@pytest.mark.parametrize('name', ['../core.json.gz', 'nested/core.json.gz', 'nested\\core.json.gz'])
def test_manifest_traversal_is_rejected_before_read(tmp_path, name):
    protocol_bundle(tmp_path, name)
    with pytest.raises(ValueError, match='unsafe'):
        read_bundle(tmp_path)


def test_asset_corruption_is_not_counted_as_valid_data(tmp_path):
    payload = protocol_bundle(tmp_path)
    (tmp_path / 'core.json.gz').write_bytes(payload + b'corruption')
    with pytest.raises(ValueError, match='mismatch'):
        read_bundle(tmp_path)


def test_expanded_history_response_is_bounded(monkeypatch):
    import cdr_public_history_audit as history

    monkeypatch.setattr(history, 'MAX_PLAIN', 1024)
    with pytest.raises(ValueError, match='exceeds bound'):
        decode(gzip.compress(b' ' * 2048))


def test_history_changes_distinguish_absence_null_zero_false_and_gap():
    from cdr_historical_parameters import changed_parameters

    delta = {item['source_pointer']: item for item in changed_parameters(
        {'zero': 0, 'flag': False, 'null': None}, {'zero': 0, 'flag': 0}, baseline=False)}
    assert '/zero' not in delta
    assert delta['/flag']['before_json'] == 'false'
    assert delta['/flag']['after_json'] == '0'
    assert delta['/null']['before_state'] == 'reported'
    assert delta['/null']['after_state'] == 'unreported'
    baseline = list(changed_parameters({'zero': 0}, {'zero': 0}, baseline=True))
    assert baseline[0]['event'] == 'baseline_observation'
    assert baseline[0]['before_state'] == 'not_compared'
    removed = list(changed_parameters({'zero': 0}, {}, baseline=False, after_present=False))
    assert len(removed) == 1
    assert removed[0]['source_pointer'] == '/zero'
    assert removed[0]['after_state'] == 'unreported'
