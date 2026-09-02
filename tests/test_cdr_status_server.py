from __future__ import annotations

import json
from pathlib import Path

import cdr_status_server


def _observation(root: Path, state: str = "complete") -> None:
    exports = root / "2026-09-02" / "_exports"
    exports.mkdir(parents=True)
    (exports / "observation-v1.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "observation_date": "2026-09-02",
                "observed_at": "2026-09-02T05:01:02Z",
                "state": state,
                "row_counts": {"rates": 7},
                "accounting": {"accounting_id": "ingest-1"},
                "summaries": {
                    "providers": {"registered": 3, "attempted": 3},
                    "products": {"discovered": 8, "consumer_visible": 7},
                    "issues": {"total": 1},
                },
            }
        ),
        encoding="utf-8",
    )


def test_status_exposes_only_compact_observation_summary(tmp_path: Path) -> None:
    _observation(tmp_path, "degraded")
    code, value = cdr_status_server.status_payload(tmp_path)
    assert code == 200
    assert value == {
        "schema_version": 1,
        "service": "ar-local",
        "status": "degraded",
        "observation": {
            "date": "2026-09-02",
            "observed_at": "2026-09-02T05:01:02Z",
            "state": "degraded",
            "accounting_id": "ingest-1",
            "providers": {"attempted": 3, "registered": 3},
            "products": {"consumer_visible": 7, "discovered": 8},
            "issues": {"total": 1},
        },
    }


def test_status_fails_closed_without_observation(tmp_path: Path) -> None:
    code, value = cdr_status_server.status_payload(tmp_path)
    assert code == 503
    assert value["reason"] == "no_verified_observation"
