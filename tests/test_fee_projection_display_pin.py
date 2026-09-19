"""Read-only reviewed code identity checks; no historical candidate execution."""
import ast
import hashlib
from pathlib import Path

import pytest
import cdr_historical_fee_embedded as projection


def test_current_observed_identity_and_historical_pin_remain_distinct():
    observed=projection.verify_projection()
    assert observed==projection.FEATURE_EVIDENCE_PROJECTION_SOURCES
    assert projection.SOURCE_LABEL_PROJECTION_SOURCES['app_payload_details.py']=='1840dca75863f9e094f488966bbc1261f5f5dc0dbd4959c68cc7e163e1f1d7c1'
    assert projection.PROJECTION_SOURCES['app_payload_details.py']=='6963791b2d12805d74b963124a264c4bb33075dc78a4f283f01c0a27c1650126'
    assert observed['app_payload_details.py']!=projection.PROJECTION_SOURCES['app_payload_details.py']


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
