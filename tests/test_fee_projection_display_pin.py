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
    # Independent AST identities from reviewed source-label projection 1840dca7.
    expected = {
        '_present': '9a54f870f7c20f14a0bcc086753d0fb19f340aa6761ea2b9b3422cc57507344c',
        '_fee_amount_status': 'e826ce7754c74e12153383a257ed2ed31adf8ea21c58b30535909fb1fb4406c4',
        '_legacy_fee_value': 'a4b713020b920616feeac3fe0e3411092c50bca72bb0c3ba67f68f8db3e882cd',
        '_fee_items': 'eb45f944637613765e2f473bb88c0353c6a1b192ff520bd18971b8014f63640e',
    }
    tree = ast.parse(Path(projection.__file__).with_name('app_payload_details.py').read_bytes())
    actual = {node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
              for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in expected}
    assert actual == expected
