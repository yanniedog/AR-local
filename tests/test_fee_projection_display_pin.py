"""Read-only reviewed code identity checks; no historical candidate execution."""
import pytest
import cdr_historical_fee_embedded as projection


def test_current_observed_identity_and_historical_pin_remain_distinct():
    observed=projection.verify_projection()
    assert observed==projection.CURRENT_PROJECTION_SOURCES
    assert projection.PROJECTION_SOURCES['app_payload_details.py']=='6963791b2d12805d74b963124a264c4bb33075dc78a4f283f01c0a27c1650126'
    assert observed['app_payload_details.py']!=projection.PROJECTION_SOURCES['app_payload_details.py']


def test_unreviewed_module_identity_still_refused(monkeypatch):
    monkeypatch.setattr(projection,'sha',lambda body:'0'*64)
    with pytest.raises(ValueError,match='requires_review'):
        projection.verify_projection()
