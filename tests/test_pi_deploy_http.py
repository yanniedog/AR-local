from __future__ import annotations

import pi_deploy_http
from pi_runtime_health import STATUS_SUMMARY_FIELDS


def _status(**observation_overrides):
    providers = {field: 0 for field in STATUS_SUMMARY_FIELDS["providers"]}
    providers.update(registered=1, attempted=1, partial=1)
    products = {field: 0 for field in STATUS_SUMMARY_FIELDS["products"]}
    products.update(discovered=1, published_core_only=1, consumer_visible=1)
    issues = {field: 0 for field in STATUS_SUMMARY_FIELDS["issues"]}
    issues.update(total=1, affected_providers=1, affected_products=1)
    observation = {
        "date": "2026-09-03",
        "observed_at": "2026-09-03T01:02:03+10:00",
        "state": "degraded",
        "accounting_id": "ingest-20260903T010203Z-abcdef123456",
        "providers": providers,
        "products": products,
        "issues": issues,
        **observation_overrides,
    }
    return {
        "schema_version": 1,
        "service": "ar-local",
        "status": "degraded",
        "observation": observation,
    }


def test_deploy_status_smoke_requires_complete_readiness_contract(monkeypatch):
    monkeypatch.setattr(pi_deploy_http, "_read_json", lambda *_args, **_kwargs: _status())
    assert pi_deploy_http.status_smoke("http://pi/") == pi_deploy_http.EXIT_OK

    for missing in ("observed_at", "state", "providers", "products", "issues"):
        payload = _status()
        payload["observation"].pop(missing)
        monkeypatch.setattr(
            pi_deploy_http, "_read_json", lambda *_args, value=payload, **_kwargs: value
        )
        assert pi_deploy_http.status_smoke("http://pi/") == pi_deploy_http.EXIT_VERIFY_FAIL


def test_deploy_status_smoke_rejects_status_state_disagreement(monkeypatch):
    monkeypatch.setattr(
        pi_deploy_http, "_read_json", lambda *_args, **_kwargs: _status(state="complete")
    )
    assert pi_deploy_http.status_smoke("http://pi/") == pi_deploy_http.EXIT_VERIFY_FAIL
