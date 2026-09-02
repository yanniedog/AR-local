from __future__ import annotations

from pathlib import Path

import cdr_status_server
from tests.support_observation import (
    write_finalized_observation,
    write_verified_observation,
)


def test_status_exposes_only_verified_summary(tmp_path: Path) -> None:
    observation = write_finalized_observation(tmp_path)
    code, value = cdr_status_server.status_payload(tmp_path / "runs")
    assert code == 200
    assert value["service"] == "ar-local"
    assert value["status"] == "ok"
    assert value["observation"] == {
        "date": "2026-09-02",
        "observed_at": observation["observed_at"],
        "state": "complete",
        "accounting_id": observation["accounting"]["accounting_id"],
        "providers": {
            "attempted": 1, "complete": 1, "empty": 0, "failed": 0,
            "not_attempted": 0, "partial": 0, "population_unknown": 0,
            "registered": 1,
        },
        "products": {
            "consumer_visible": 1, "discovered": 1, "omitted_valid": 0,
            "published_core_only": 0, "published_full": 1,
            "quarantined_invalid": 0,
        },
        "issues": {
            "affected_products": 0, "affected_providers": 0, "corrupt": 0,
            "total": 0, "unattributed": 0,
        },
    }


def test_status_fails_closed_without_observation(tmp_path: Path) -> None:
    code, value = cdr_status_server.status_payload(tmp_path / "runs")
    assert code == 503
    assert value["reason"] == "no_verified_observation"

    health_code, health = cdr_status_server.health_payload(tmp_path / "runs")
    assert health_code == 200
    assert health == {
        "schema_version": 1,
        "service": "ar-local",
        "status": "ok",
    }


def test_status_fails_closed_when_database_is_tampered(tmp_path: Path) -> None:
    write_finalized_observation(tmp_path)
    exports = tmp_path / "runs" / "2026-09-02" / "_exports"
    database = exports / "local-cdr.sqlite"
    database.write_bytes(database.read_bytes() + b"tamper")
    code, value = cdr_status_server.status_payload(tmp_path / "runs")
    assert code == 503
    assert value["reason"] == "no_verified_observation"


def test_status_rejects_canonical_files_without_finalization(tmp_path: Path) -> None:
    write_verified_observation(tmp_path / "runs/2026-09-02/_exports")
    code, value = cdr_status_server.status_payload(tmp_path / "runs")
    assert code == 503
    assert value["reason"] == "no_verified_observation"
