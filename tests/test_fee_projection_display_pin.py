"""Read-only reviewed code identity checks; no historical candidate execution."""
import ast
import hashlib
from pathlib import Path

import pytest
import cdr_historical_fee_embedded as projection


def test_current_observed_identity_and_historical_pin_remain_distinct():
    observed=projection.verify_projection()
    assert observed==projection.PUBLIC_PRICING_PROJECTION_SOURCES
    assert observed['app_payload_details.py']==projection.FEATURE_EVIDENCE_PROJECTION_SOURCES['app_payload_details.py']
    assert observed['app_payload_common.py']=='9913ae8b1a0324ad5037e542bbc7486412fa4cb273e1f82015bf4b16abae4671'
    assert projection.SOURCE_LABEL_PROJECTION_SOURCES['app_payload_details.py']=='1840dca75863f9e094f488966bbc1261f5f5dc0dbd4959c68cc7e163e1f1d7c1'
    assert projection.PROJECTION_SOURCES['app_payload_details.py']=='6963791b2d12805d74b963124a264c4bb33075dc78a4f283f01c0a27c1650126'
    assert observed['app_payload_details.py']!=projection.PROJECTION_SOURCES['app_payload_details.py']


def test_all_historical_projection_identities_remain_frozen():
    common = 'cce4a7b19b4f86c7b52cde122b8a86d68c47b29dc1eb939fc7673a8225cd942d'
    expected = (
        ('PROJECTION_SOURCES', '6963791b2d12805d74b963124a264c4bb33075dc78a4f283f01c0a27c1650126'),
        ('CURRENT_PROJECTION_SOURCES', '533ddce96c8e4bbdcaa1b011343e5643f8ea40636ba72ef79f36d82d29bc3510'),
        ('SOURCE_LABEL_PROJECTION_SOURCES', '1840dca75863f9e094f488966bbc1261f5f5dc0dbd4959c68cc7e163e1f1d7c1'),
        ('FEATURE_EVIDENCE_PROJECTION_SOURCES', '255f9358ecb0d8f7f602a32c0d5d6ebd9201107c660a20ed6243e306b80f81f0'),
    )
    for name, details in expected:
        assert getattr(projection, name) == {'app_payload_details.py': details, 'app_payload_common.py': common}


def test_opt_in_filter_is_the_only_change_to_the_frozen_default_common_source():
    source = Path(projection.__file__).with_name('app_payload_common.py').read_bytes().replace(b'\r\n', b'\n')
    signature = b'def section_filter(dataset: str, row: Dict[str, Any], *, require_absolute: bool = False) -> bool:'
    previous = b'def section_filter(dataset: str, row: Dict[str, Any]) -> bool:'
    opt_in = (b'    from cdr_public_rates_legacy import legacy_row_is_absolute\n'
              b'    if require_absolute and not legacy_row_is_absolute(row):\n        return False\n')
    assert source.count(signature) == 1 and source.count(opt_in) == 1
    restored = source.replace(signature, previous).replace(opt_in, b'')
    assert hashlib.sha256(restored).hexdigest() == projection.PROJECTION_SOURCES['app_payload_common.py']
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'section_filter')
    assert [argument.arg for argument in node.args.kwonlyargs] == ['require_absolute']
    assert len(node.args.kw_defaults) == 1 and isinstance(node.args.kw_defaults[0], ast.Constant)
    assert node.args.kw_defaults[0].value is False


@pytest.mark.parametrize('identity', ['PROJECTION_SOURCES', 'CURRENT_PROJECTION_SOURCES',
                                     'SOURCE_LABEL_PROJECTION_SOURCES', 'FEATURE_EVIDENCE_PROJECTION_SOURCES'])
def test_previously_reviewed_complete_pairs_remain_accepted(monkeypatch, identity):
    expected = getattr(projection, identity)
    values = iter(expected[name] for name in projection.PROJECTION_SOURCES)
    monkeypatch.setattr(projection, 'sha', lambda _body: next(values))  # Code-identity control only.
    assert projection.verify_projection() == expected


def test_new_common_cannot_be_combined_with_an_unreviewed_older_details_pair(monkeypatch):
    values = iter((projection.PROJECTION_SOURCES['app_payload_details.py'],
                   projection.PUBLIC_PRICING_PROJECTION_SOURCES['app_payload_common.py']))
    monkeypatch.setattr(projection, 'sha', lambda _body: next(values))
    with pytest.raises(ValueError, match='requires_review'):
        projection.verify_projection()


def test_unreviewed_module_identity_still_refused(monkeypatch):
    monkeypatch.setattr(projection,'sha',lambda body:'0'*64)
    with pytest.raises(ValueError,match='requires_review'):
        projection.verify_projection()


def test_feature_evidence_keeps_reviewed_fee_functions_unchanged():
    # Exact source from reviewed projection 1840dca7, normalized to LF. AST dump
    # serialization changes across Python versions (including empty fields).
    expected = {
        '_present': 'd0122400a68a1dd09b120ca7c63465a2bab67cd4a1c0be1041bfa0646e11fa87',
        '_fee_amount_status': '875a3c590812096ed7bc308f459edbb1706ec947c289d25977f12804068a8f4c',
        '_legacy_fee_value': '7688b747dfe7dc6b8cda25c1318b8658225ccb959be01eb1bfa0d937241e8138',
        '_fee_items': '2d821a1be1dc774ea5cf9a7545753738b248e282bfae27e8a5d66d4cc25cbc4b',
    }
    source = Path(projection.__file__).with_name('app_payload_details.py').read_text(encoding='utf-8')
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name in expected]
    assert len(functions) == len(expected)
    assert all(not node.decorator_list for node in functions)
    actual = {node.name: hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
              for node in functions}
    assert actual == expected
