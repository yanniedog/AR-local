"""Acceptance-report, offline, and private-corpus gates."""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

import cdr_historical_acceptance as acceptance
from cdr_historical_candidate import BuiltHistory
from cdr_historical_contract import HistoricalContractError, canonical_json_bytes, sha256_bytes


TOOL_COMMIT = "b" * 40
SNAPSHOT_ID = "20260814T202526AEST-pi5-3dc9b4677"


def _dates() -> tuple[str, ...]:
    values: list[str] = []
    cursor = date(2026, 5, 13)
    while len(values) < 92:
        if cursor.isoformat() not in {"2026-05-14", "2026-06-26"}:
            values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


def _fake_history() -> BuiltHistory:
    dates = []
    candidate_number = 0
    for value in _dates():
        count = 2 if value in {"2026-05-19", "2026-05-20", "2026-05-26"} else 1
        candidates = []
        for _ in range(count):
            candidate_number += 1
            candidates.append({"candidate_id": f"candidate-{candidate_number}", "sha256": f"{candidate_number:064x}", "bytes": 1})
        dates.append({"date": value, "candidates": candidates})
    value = {
        "schema_version": 1,
        "contract": "legacy-historical-index-v1",
        "dates": dates,
        "gaps": [
            {"date": "2026-05-14", "status": "known_gap", "reason": "none"},
            {"date": "2026-06-26", "status": "unclassified_gap", "reason": "none"},
        ],
        "candidate_count": 95,
        "updates_operational_latest_complete": False,
    }
    payload = canonical_json_bytes(value)
    return BuiltHistory({}, {}, payload, sha256_bytes(payload))


def _patch_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    *,
    products: int = 230852,
    preservation_drift: bool = False,
) -> SimpleNamespace:
    critical = {str(index): SimpleNamespace(bytes=0) for index in range(1932)}
    critical["0"] = SimpleNamespace(bytes=25586769110)
    snapshot = SimpleNamespace(
        snapshot_id=SNAPSHOT_ID,
        dates=_dates(),
        critical=critical,
    )
    finding = SimpleNamespace(
        path="pi/data/runs/2026-05-23/_exports/local-cdr.sqlite-shm",
        expected_bytes=98304,
        actual_bytes=98304,
        expected_sha256="1" * 64,
        actual_sha256="2" * 64,
        source_role="sqlite_transient_sidecar",
    )
    snapshot.audit_rehash = lambda _paths, **_kwargs: SimpleNamespace(
        checked_files=1932,
        checked_bytes=25586769110,
        verified_files=1931 if preservation_drift else 1932,
        verified_bytes=25586670806 if preservation_drift else 25586769110,
        findings=(finding,) if preservation_drift else (),
    )
    monkeypatch.setattr(acceptance, "open_verified_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(acceptance, "_candidate_input_paths", lambda *_args: ())
    monkeypatch.setattr(acceptance, "build_history", lambda *_args, **_kwargs: _fake_history())
    monkeypatch.setattr(
        acceptance,
        "additions_audit",
        lambda *_args: {
            "schema_version": 1,
            "contract": "legacy-historical-additions-audit-v1",
            "changed_dates": 57,
            "original_population": {"files": 568, "bytes": 18177646221},
            "addition_population": {"files": 688, "bytes": 147127281},
            "legacy_findings_preserved": True,
        },
    )

    def fake_date(_snapshot: object, value: str, *, deep: bool) -> dict[str, object]:
        first = value == _dates()[0]
        return {
            "date": value,
            "population": {
                "products": products if first else 0,
                "rates": 1319589 if first else 0,
                "failures": 8077 if first else 0,
            },
            "dashboard_population": {"products": 1618, "rates": 10514, "failures": 68},
            "dashboard_equal": value != "2026-05-19",
            "semantic_collision_groups": 763 if first else 0,
            "semantic_collision_rows": 1876 if first else 0,
            "semantic_duplicate_same_value_groups": 95 if first else 0,
            "semantic_duplicate_same_value_rows": 190 if first else 0,
            "semantic_nonunique_rows": 2066 if first else 0,
            "semantic_collision_records": (),
            "td_terms": {
                "exact_iso": 552 if first else 0,
                "structured_range": 1564 if first else 0,
                "text_derived": 5796 if first else 0,
                "no_evidence": 460 if first else 0,
            },
        }

    monkeypatch.setattr(acceptance, "check_date", fake_date)
    return snapshot


def test_acceptance_is_deterministic_for_reversed_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_acceptance(monkeypatch)
    forward = acceptance.run_acceptance(tmp_path, tool_commit=TOOL_COMMIT)
    reverse = acceptance.run_acceptance(tmp_path, tool_commit=TOOL_COMMIT, reverse_discovery=True)
    assert canonical_json_bytes(forward) == canonical_json_bytes(reverse)
    assert forward["status"] == "unverified_partial_non_promotable"
    assert forward["history"] == {
        "retained_dates": 92,
        "gap_entries": 2,
        "candidate_count": 95,
        "legacy_ledger_records": 93,
        "legacy_ledger_role_difference_recorded": True,
    }
    assert forward["promotion_eligible"] is False


def test_full_rehash_reports_transient_drift_before_candidate_or_parity_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_acceptance(monkeypatch, preservation_drift=True)
    monkeypatch.setattr(
        acceptance,
        "build_history",
        lambda *_args, **_kwargs: pytest.fail("candidate build must not start"),
    )
    monkeypatch.setattr(
        acceptance,
        "check_date",
        lambda *_args, **_kwargs: pytest.fail("parity must not start"),
    )
    report = acceptance.run_acceptance(
        tmp_path,
        tool_commit=TOOL_COMMIT,
        deep=True,
        full_rehash=True,
    )
    assert report["status"] == "BLOCKED_PRESERVATION_DRIFT"
    assert report["source"]["rehash"]["candidate_inputs_verified"] is True
    assert report["source"]["preservation_drift"] == [
        {
            "path": "pi/data/runs/2026-05-23/_exports/local-cdr.sqlite-shm",
            "expected_bytes": 98304,
            "actual_bytes": 98304,
            "expected_sha256": "1" * 64,
            "actual_sha256": "2" * 64,
            "source_role": "sqlite_transient_sidecar",
        }
    ]
    assert report["safety"]["candidate_output_written"] is False


def test_final_rehash_discards_in_memory_candidate_if_source_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _patch_acceptance(monkeypatch)
    clean = SimpleNamespace(
        checked_files=1932,
        checked_bytes=25586769110,
        verified_files=1932,
        verified_bytes=25586769110,
        findings=(),
    )
    drift = SimpleNamespace(
        path="pi/data/runs/2026-05-13/_exports/banks-2026-05-13.json",
        expected_bytes=10,
        actual_bytes=10,
        expected_sha256="3" * 64,
        actual_sha256="4" * 64,
        source_role="immutable_candidate_input",
    )
    changed = SimpleNamespace(
        checked_files=1932,
        checked_bytes=25586769110,
        verified_files=1931,
        verified_bytes=25586769100,
        findings=(drift,),
    )
    audits = iter((clean, changed))
    snapshot.audit_rehash = lambda _paths, **_kwargs: next(audits)
    report = acceptance.run_acceptance(
        tmp_path,
        tool_commit=TOOL_COMMIT,
        full_rehash=True,
    )
    assert report["status"] == "BLOCKED_PRESERVATION_DRIFT"
    assert report["source"]["rehash"]["candidate_inputs_verified"] is False
    assert report["history"] == {
        "state": "discarded_due_to_final_preservation_drift"
    }
    assert report["safety"] == {
        "network_blocked": True,
        "candidate_build_started": True,
        "candidate_output_written": False,
    }


def test_acceptance_population_equations_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_acceptance(monkeypatch, products=230851)
    with pytest.raises(HistoricalContractError, match="row population"):
        acceptance.run_acceptance(tmp_path, tool_commit=TOOL_COMMIT)


def test_offline_guard_blocks_socket_and_http_foundations() -> None:
    with acceptance.offline_network_guard():
        with pytest.raises(HistoricalContractError, match="network access"):
            socket.socket()
        with pytest.raises(HistoricalContractError, match="network access"):
            socket.create_connection(("example.com", 443))
    test_socket = socket.socket()
    test_socket.close()


def test_acceptance_schema_rejects_complete_or_publication_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_acceptance(monkeypatch)
    report = acceptance.run_acceptance(tmp_path, tool_commit=TOOL_COMMIT)
    report["status"] = "complete"
    with pytest.raises(Exception):
        acceptance.validate_schema("acceptance_report", report)
    report.pop("status")
    report["status"] = "accepted_partial_non_promotable"
    report["publisher"] = "forbidden"
    with pytest.raises(Exception):
        acceptance.validate_schema("acceptance_report", report)


def test_historical_workflow_is_read_only_windows_linux_and_has_no_activation() -> None:
    workflow = (acceptance.ROOT / ".github" / "workflows" / "historical-candidate-ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "workflow_dispatch" not in workflow
    assert "schedule:" not in workflow
    assert "contents: write" not in workflow
    assert "release" not in workflow.casefold()
    assert "python cdr_historical_acceptance.py" not in workflow


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        ("accepted_partial_non_promotable", 0),
        ("unverified_partial_non_promotable", 2),
        ("BLOCKED_PRESERVATION_DRIFT", 2),
        ("rejected", 2),
    ],
)
def test_cli_exits_successfully_only_for_a_fully_verified_partial_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    status: str,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        acceptance,
        "run_acceptance",
        lambda *_args, **_kwargs: {"status": status},
    )
    assert acceptance.main(
        ["verify", "--snapshot", "unused", "--tool-commit", TOOL_COMMIT]
    ) == expected_exit
    assert json.loads(capsysbinary.readouterr().out) == {"status": status}


@pytest.mark.skipif(
    not os.environ.get("AR_HISTORICAL_SNAPSHOT"),
    reason="private preservation snapshot is intentionally unavailable in CI",
)
def test_private_all_92_date_corpus_gate() -> None:
    root = Path(os.environ["AR_HISTORICAL_SNAPSHOT"])
    commit = os.environ.get("AR_HISTORICAL_TOOL_COMMIT", TOOL_COMMIT)
    report = acceptance.run_acceptance(
        root,
        tool_commit=commit,
        deep=True,
        full_rehash=True,
    )
    assert report["status"] == "BLOCKED_PRESERVATION_DRIFT"
    assert report["source"]["preservation_inventory_population"] == {
        "files": 1932,
        "bytes": 25586769110,
    }
    assert report["source"]["candidate_input_population"] == {
        "files": 1495,
        "bytes": 21179877992,
    }
    assert report["source"]["rehash"]["checked_files"] == 2305
    assert report["source"]["rehash"]["checked_bytes"] == 25666542785
    assert report["source"]["rehash"]["verified_files"] == 2303
    assert report["source"]["rehash"]["verified_bytes"] == 25666346177
    assert report["source"]["rehash"]["candidate_inputs_verified"] is True
    assert [item["path"] for item in report["source"]["preservation_drift"]] == [
        "pi/data/runs/2026-05-23/_exports/local-cdr.sqlite-shm",
        "pi/data/runs/2026-05-24/_exports/local-cdr.sqlite-shm",
    ]
    assert [item["expected_sha256"] for item in report["source"]["preservation_drift"]] == [
        "404a2ce5ef441b741c2d61d115a9e2e258ec18535b96ea8baf77168d78064b96",
        "f6400fdd5f10ae1f497cae2f17c32c14f00f723a2e35cc06bc2896f606419ee2",
    ]
    assert [item["actual_sha256"] for item in report["source"]["preservation_drift"]] == [
        "92fd64bdfe923ed239609cc59f439ff94bbbe700f039205bce409681f49c0f87",
        "b098009c22153fea8a395531b53f08fedc0d884d08f1a742ce7bf63ac44a6c80",
    ]
    assert report["history"] == {"state": "not_run_due_to_preservation_drift"}
