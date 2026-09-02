"""One publication policy, and one provider accounting, across every payload path."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app_payload_build  # noqa: E402
import app_payload_observation_gate as gate  # noqa: E402
import pi_daily_sync  # noqa: E402


def _load_backfill():
    """Import the backfill script by path; it is not an importable module name."""
    spec = importlib.util.spec_from_file_location(
        "backfill_app_payload", ROOT / "scripts" / "backfill_app_payload.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract(**coverage: object) -> dict:
    base = {
        "failure_records": 17,
        "corrupt_failure_records": 0,
        "unattributed_failure_records": 0,
        "products_discovered": 3027,
        "providers_registered": 118,
        "providers_attempted": 118,
        "providers_partial": 7,
        "providers_failed": 0,
        "register_sources_attempted": 1,
        "register_sources_complete": 1,
        "register_provenance_complete": True,
        "failure_provenance_complete": True,
    }
    base.update(coverage)
    return {"observation_state": "partial", "coverage": base}


def test_publication_allowed_matches_the_daily_path() -> None:
    allowed, reason = gate.publication_allowed(_contract())
    assert (allowed, reason) == (True, "bounded_partial")
    allowed, reason = gate.publication_allowed({"observation_state": "complete"})
    assert (allowed, reason) == (True, "complete")


def test_reconciled_partial_with_valid_omissions_can_publish() -> None:
    allowed, reason = gate.publication_allowed(
        _contract(failure_records=0, providers_partial=1)
    )
    assert (allowed, reason) == (True, "bounded_partial")


def test_publication_refuses_the_broken_day_and_the_unknown_day() -> None:
    # 2026-08-15: 1,195 failure records over 1,864 products, 34 of 118 partial.
    broken = _contract(failure_records=1195, products_discovered=1864, providers_partial=34)
    assert gate.publication_allowed(broken) == (False, "outside_bounded_v1_policy")
    # A date with no contract at all is exactly the case the backfill used to
    # publish blind, so it must refuse rather than default open.
    assert gate.publication_allowed(None) == (False, "missing_export_contract")
    assert gate.publication_allowed({}) == (False, "missing_export_contract")
    assert gate.publication_allowed({"observation_state": "failed"}) == (
        False,
        "observation_state=failed",
    )


def test_pi_daily_sync_delegates_to_the_shared_gate() -> None:
    """The daily path must not keep a second copy of the policy."""
    assert pi_daily_sync._bounded_partial_v1_allowed(_contract()) is True
    assert pi_daily_sync.PARTIAL_V1_MAX_FAILURE_RECORDS == gate.PARTIAL_V1_MAX_FAILURE_RECORDS
    assert pi_daily_sync.PARTIAL_V1_MAX_FAILURE_RATIO == gate.PARTIAL_V1_MAX_FAILURE_RATIO


def test_contract_for_run_date_prefers_the_newest_generation(tmp_path: Path) -> None:
    directory = tmp_path / gate.CONTRACT_DIRNAME / "2026-08-17"
    directory.mkdir(parents=True)
    (directory / "aaa.json").write_text(
        json.dumps({"generated_at": "2026-08-16T15:00:00Z", "observation_state": "partial"}),
        encoding="utf-8",
    )
    (directory / "zzz.json").write_text(
        json.dumps({"generated_at": "2026-08-16T09:00:00Z", "observation_state": "complete"}),
        encoding="utf-8",
    )
    newest = gate.contract_for_run_date(tmp_path, "2026-08-17")
    assert newest is not None and newest["observation_state"] == "partial"
    assert gate.contract_for_run_date(tmp_path, "2026-08-18") is None


def _banks_with_coverage() -> dict:
    """A day whose exported rows disagree with the ingest's own provider states."""
    return {
        "coverage": {
            "schema_version": 1,
            "observed_on": "2026-08-17",
            "counts": {
                "brands_observed": 108,
                "products": 3035,
                "rates": 17150,
                "failure_records": 16,
                # Row-derived: "had a failure record and produced no rows".
                "providers_failed": 2,
                "providers_partial": 4,
                "providers_attempted": 118,
                "providers_succeeded": 116,
            },
            "sections": {},
            "provider_failures": [],
            "providers_attempted": 118,
            "providers_succeeded": 116,
        }
    }


def test_contract_coverage_overrides_row_derived_provider_counts() -> None:
    """The app must be told what the ingest certified, not a second opinion.

    The live 2026-08-17 payload advertised 2 failed providers for a run whose
    contract had to report 0 failed for publication to be permitted at all.
    """
    coverage = app_payload_build._stable_payload_coverage(
        _banks_with_coverage(),
        {},
        "2026-08-17",
        contract_coverage=_contract()["coverage"],
    )
    counts = coverage["counts"]
    assert counts["providers_failed"] == 0
    assert counts["providers_partial"] == 7
    assert counts["providers_attempted"] == 118
    assert counts["providers_registered"] == 118
    # Succeeded still means "yielded usable data", so partials are included.
    assert counts["providers_succeeded"] == 118
    assert counts["provider_counts_source"] == "export_contract_v2"
    # The aliases clean_export already wrote must follow, not win.
    assert coverage["providers_succeeded"] == 118
    # Row-derived totals describe the export and are left alone.
    assert counts["products"] == 3035
    assert counts["failure_records"] == 16


def test_row_derived_counts_survive_when_no_contract_is_available() -> None:
    coverage = app_payload_build._stable_payload_coverage(
        _banks_with_coverage(), {}, "2026-08-17"
    )
    assert coverage["counts"]["providers_failed"] == 2
    assert "provider_counts_source" not in coverage["counts"]


def test_pending_marker_records_the_observation_that_failed(tmp_path: Path, monkeypatch) -> None:
    """A reason-only marker cannot retry the right day; that is the 08-15 stall."""
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    pointer = {
        "observation_date": "2026-08-15",
        "observation_state": "complete",
        "export_path": "runs/2026-08-15/_exports",
        "marker_path": "2026-08-15.done.json",
    }
    pi_daily_sync.mark_payload_publication_pending(ROOT, "publish_failed", pointer)
    assert pi_daily_sync.read_payload_publication_pending(ROOT)["run_date"] == "2026-08-15"
    assert pi_daily_sync.pending_publication_pointer(ROOT) == pointer


def test_pending_marker_without_a_pointer_falls_back(tmp_path: Path, monkeypatch) -> None:
    """Markers written before this change must not break the retry."""
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    pi_daily_sync.mark_payload_publication_pending(ROOT, "publish_failed")
    assert pi_daily_sync.payload_publication_pending(ROOT)
    assert pi_daily_sync.pending_publication_pointer(ROOT) is None


@pytest.mark.parametrize(
    "contents",
    [
        "this is not valid json {",
        json.dumps(["not", "a", "dict"]),
        json.dumps("not-a-dict"),
        "",
    ],
)
def test_corrupt_pending_marker_does_not_break_the_retry(
    tmp_path: Path, monkeypatch, contents: str
) -> None:
    """A hand-edited or truncated marker must degrade to the fallback, not raise.

    The marker is written on the Pi during a failed publish, so a power loss can
    truncate it — and an operator may well open it while diagnosing a stall.
    """
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    pi_daily_sync.payload_publication_pending_path(ROOT).write_text(
        contents, encoding="utf-8"
    )
    assert pi_daily_sync.payload_publication_pending(ROOT)
    assert pi_daily_sync.read_payload_publication_pending(ROOT) == {}
    assert pi_daily_sync.pending_publication_pointer(ROOT) is None


def test_retry_republishes_the_recorded_day_not_the_current_one(
    tmp_path: Path, monkeypatch
) -> None:
    """The retry must go back for the failed day even when today is withheld."""
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path)
    monkeypatch.setattr(pi_daily_sync, "ensure_runtime_data_writable", lambda _repo: None)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    pointer = {
        "observation_date": "2026-08-15",
        "observation_state": "complete",
        "export_path": "runs/2026-08-15/_exports",
        "marker_path": "2026-08-15.done.json",
    }
    pi_daily_sync.mark_payload_publication_pending(ROOT, "publish_failed", pointer)
    with mock.patch.object(
        pi_daily_sync,
        "maybe_publish_app_payload",
        return_value=pi_daily_sync.PUBLISH_PUBLISHED,
    ) as publish:
        assert pi_daily_sync.main(["--publish-existing-payload"]) == 0
    publish.assert_called_once_with(pi_daily_sync.REPO_ROOT, pointer)
    assert not pi_daily_sync.payload_publication_pending(ROOT)


def test_backfill_refuses_an_ungated_date_unless_forced(tmp_path: Path) -> None:
    """The path that published the broken 2026-08-15 day now shares the policy."""
    backfill = _load_backfill()
    allowed, reason, _ = backfill.observation_gate(tmp_path, "2026-08-15", force=False)
    assert (allowed, reason) == (False, "missing_export_contract")
    allowed, reason, _ = backfill.observation_gate(tmp_path, "2026-08-15", force=True)
    assert allowed and reason == "forced_over_missing_export_contract"


def test_backfill_admits_a_contract_the_daily_path_would_publish(tmp_path: Path) -> None:
    backfill = _load_backfill()
    directory = tmp_path / gate.CONTRACT_DIRNAME / "2026-08-17"
    directory.mkdir(parents=True)
    (directory / "gen.json").write_text(json.dumps(_contract()), encoding="utf-8")
    allowed, reason, contract = backfill.observation_gate(
        tmp_path, "2026-08-17", force=False
    )
    assert (allowed, reason) == (True, "bounded_partial")
    assert gate.contract_coverage(contract)["providers_failed"] == 0


def test_backfill_state_root_sits_beside_runs(tmp_path: Path) -> None:
    backfill = _load_backfill()
    assert backfill.resolve_state_root(tmp_path / "runs") == tmp_path / "state"
