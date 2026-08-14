"""Append-only ledger enforcement in cdr_daily.resolve_ledger_target.

Encodes the Permanent CDR Ledger Invariant at the one code path that can reach
finalized ledger bytes: the daily ingest's write target. Every existing
observation is immutable; a retry creates a revision, including on the same day.
"""

import json
from datetime import datetime

import pytest

import cdr_daily

TODAY = "2026-06-16"


def _finalize(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "local-cdr.sqlite").write_bytes(b"finalized")
    return root


def _write_legacy_observation(runs, state, date):
    export = runs / date / "_exports"
    cache = export / "dashboard-cache"
    cache.mkdir(parents=True)
    manifest = {"run_date": date, "banks_counts": {"rates": 5}}
    (cache / "latest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (export / "local-cdr.sqlite").write_bytes(b"legacy")
    state.mkdir(parents=True, exist_ok=True)
    marker = state / f"{date}.done.json"
    marker.write_text(json.dumps(manifest), encoding="utf-8")
    return export, marker


@pytest.mark.parametrize("force", [False, True])
def test_today_writes_primary(tmp_path, force):
    # An empty current-day target receives the create-once primary generation.
    primary = tmp_path / TODAY / "_exports"
    target, is_revision = cdr_daily.resolve_ledger_target(primary, TODAY, TODAY, force=force)
    assert target == primary
    assert is_revision is False


def test_existing_marker_routes_empty_today_to_revision(tmp_path):
    primary = tmp_path / TODAY / "_exports"
    when = datetime(2026, 6, 16, 9, 30, 0)
    target, is_revision = cdr_daily.resolve_ledger_target(
        primary,
        TODAY,
        TODAY,
        force=False,
        now=when,
        marker_evidence=True,
    )
    assert is_revision is True
    assert target == primary.parent / "_revisions" / "20260616T093000_000000" / "_exports"


@pytest.mark.parametrize("force", [False, True])
def test_existing_today_observation_always_appends_revision(tmp_path, force):
    primary = _finalize(tmp_path / TODAY / "_exports")
    when = datetime(2026, 6, 16, 9, 30, 0)
    target, is_revision = cdr_daily.resolve_ledger_target(
        primary, TODAY, TODAY, force=force, now=when
    )
    assert is_revision is True
    assert target == primary.parent / "_revisions" / "20260616T093000_000000" / "_exports"
    assert (primary / "local-cdr.sqlite").read_bytes() == b"finalized"


@pytest.mark.parametrize("force", [False, True])
def test_future_date_writes_primary(tmp_path, force):
    primary = tmp_path / "2026-12-31" / "_exports"
    target, is_revision = cdr_daily.resolve_ledger_target(primary, "2026-12-31", TODAY, force=force)
    assert target == primary and is_revision is False


@pytest.mark.parametrize("force", [False, True])
def test_finalized_past_day_refuses_live_ingest_even_with_force(tmp_path, force):
    primary = _finalize(tmp_path / "2026-05-13" / "_exports")
    with pytest.raises(cdr_daily.LedgerImmutabilityError, match="live ingest for finalized ledger day"):
        cdr_daily.resolve_ledger_target(primary, "2026-05-13", TODAY, force=force)
    # The original bytes are untouched by the (refused) call.
    assert (primary / "local-cdr.sqlite").read_bytes() == b"finalized"


def test_missing_past_day_is_never_fabricated(tmp_path):
    # The 2026-05-14 gap: no primary content. Live data must not be written here,
    # with or without --force.
    primary = tmp_path / "2026-05-14" / "_exports"
    for force in (False, True):
        with pytest.raises(cdr_daily.LedgerImmutabilityError, match="gap must remain a gap"):
            cdr_daily.resolve_ledger_target(primary, "2026-05-14", TODAY, force=force)
    assert not primary.exists()


def test_empty_past_export_dir_counts_as_gap(tmp_path):
    # An empty (but existing) _exports dir is not a finalized day.
    primary = (tmp_path / "2026-05-14" / "_exports")
    primary.mkdir(parents=True)
    with pytest.raises(cdr_daily.LedgerImmutabilityError, match="gap must remain a gap"):
        cdr_daily.resolve_ledger_target(primary, "2026-05-14", TODAY, force=True)


def test_revision_root_for_structure(tmp_path):
    primary = tmp_path / "2026-05-13" / "_exports"
    rev = cdr_daily.revision_root_for(primary, datetime(2026, 6, 16, 1, 2, 3, 456789))
    assert rev == primary.parent / "_revisions" / "20260616T010203_456789" / "_exports"


def test_revision_stamp_is_unique_within_a_second(tmp_path):
    # Sub-second precision keeps two forced ingests in the same second distinct.
    primary = tmp_path / "2026-05-13" / "_exports"
    a = cdr_daily.revision_root_for(primary, datetime(2026, 6, 16, 1, 2, 3, 1))
    b = cdr_daily.revision_root_for(primary, datetime(2026, 6, 16, 1, 2, 3, 2))
    assert a != b


def test_run_once_missing_past_day_never_writes(tmp_path, monkeypatch):
    """Integration guard: run_once must preserve a gap day — exit 2, write nothing."""
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: TODAY)
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    for force in (False, True):
        argv = ["--date", "2026-05-14", "--runs", str(runs), "--state", str(state), "--no-ram-stage"]
        if force:
            argv.append("--force")
        args = cdr_daily.parse_args(argv)
        # Refusal happens before any ingest/subprocess, so no live fetch occurs.
        assert cdr_daily.run_once(args) == 2
    # The gap day got no export bytes and no completion/revision markers.
    assert not (runs / "2026-05-14").exists()
    assert list(state.glob("2026-05-14*.json")) == []


@pytest.mark.parametrize(
    ("date", "message"),
    [
        (TODAY, "legacy observation"),
        ("2026-06-15", "live ingest for finalized ledger day"),
    ],
)
def test_run_once_refuses_unsupported_revision_before_ingest(
    tmp_path, monkeypatch, capsys, date, message
):
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: TODAY)
    calls = []
    monkeypatch.setattr(cdr_daily, "run_ingest", lambda *a, **k: calls.append(True))
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    export, marker = _write_legacy_observation(runs, state, date)
    original_marker = marker.read_bytes()

    args = cdr_daily.parse_args(
        [
            "--date",
            date,
            "--runs",
            str(runs),
            "--state",
            str(state),
            "--force",
            "--no-ram-stage",
        ]
    )
    assert cdr_daily.run_once(args) == 2
    assert message in capsys.readouterr().err
    assert calls == []
    assert marker.read_bytes() == original_marker
    assert not (export.parent / "_revisions").exists()


def test_run_once_rejects_nonportable_layout_before_ingest(tmp_path, monkeypatch):
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: TODAY)
    called = []
    monkeypatch.setattr(cdr_daily, "run_ingest", lambda *a, **k: called.append(True))
    runs = tmp_path / "data-a" / "runs"
    state = tmp_path / "data-b" / "state"
    args = cdr_daily.parse_args(
        [
            "--date",
            TODAY,
            "--runs",
            str(runs),
            "--state",
            str(state),
            "--no-ram-stage",
        ]
    )
    assert cdr_daily.run_once(args) == 2
    assert called == []
    assert not state.exists()


def test_run_once_self_heals_missing_integrity_manifest(tmp_path, monkeypatch):
    """A finalized day whose integrity manifest never landed gets it on the next run.

    Guards the Codex P2 case: once the completion marker is trusted, run_once returns
    early, so that path must also (re)emit a missing manifest.
    """
    import json

    import cdr_ledger_integrity as li

    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: TODAY)
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    state.mkdir(parents=True)
    export_root = runs / TODAY / "_exports"
    (export_root / "dashboard-cache").mkdir(parents=True)
    finalized = {"run_date": TODAY, "banks_counts": {"rates": 5}}
    (export_root / "dashboard-cache" / "latest.json").write_text(json.dumps(finalized), encoding="utf-8")
    (export_root / "local-cdr.sqlite").write_bytes(b"db")
    # Trustworthy completion marker, but the integrity manifest is missing.
    cdr_daily.marker_path(state, TODAY).write_text(json.dumps(finalized), encoding="utf-8")
    assert not li.manifest_path(state, TODAY).is_file()

    rc = cdr_daily.run_once(
        cdr_daily.parse_args(["--date", TODAY, "--runs", str(runs), "--state", str(state), "--no-ram-stage"])
    )
    assert rc == 0  # already finalized -> skipped
    assert li.manifest_path(state, TODAY).is_file()  # ...but the manifest self-healed


def test_ram_staged_run_passes_persistent_previous_day_to_output_builder(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: TODAY)
    monkeypatch.setattr(cdr_daily, "is_raspberry_pi", lambda: True)
    monkeypatch.setattr(cdr_daily, "run_ingest", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "persist_ingest_status", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "copytree_atomic", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "write_sanity_report", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "_emit_day_manifest", lambda *a, **k: None)
    monkeypatch.setattr(
        cdr_daily,
        "finalize_observation",
        lambda _export, _state, _marker, **kwargs: {
            **kwargs["result"],
            "observation_state": "complete",
        },
    )

    runs = tmp_path / "runs"
    previous = runs / "2026-06-15"
    export = previous / "_exports"
    export.mkdir(parents=True)
    (export / "banks-2026-06-15.json").write_text(json.dumps({
        "product_facts": [],
        "product_change_summary": {"normalization_version": "cdr-product-facts-2"},
    }), encoding="utf-8")
    (export / "banks-2026-06-15.xlsx").write_bytes(b"complete")
    (export / "local-cdr.sqlite").write_bytes(b"complete")
    cache = export / "dashboard-cache"
    cache.mkdir()
    (cache / "latest.json").write_text(json.dumps({
        "run_date": "2026-06-15",
        "files": {
            "banks_json": "banks-2026-06-15.json",
            "banks_xlsx": "banks-2026-06-15.xlsx",
            "db": "local-cdr.sqlite",
        },
    }), encoding="utf-8")
    captured = {}

    def fake_build(run_root, out_dir, db_path, *, previous_run_root=None):
        captured["previous"] = previous_run_root
        return {"run_date": TODAY, "out_dir": str(out_dir), "banks": {"rates": 1}}

    monkeypatch.setattr(cdr_daily, "build_outputs", fake_build)
    args = cdr_daily.parse_args([
        "--date", TODAY, "--runs", str(runs), "--state", str(tmp_path / "state"),
        "--ram-stage", "--ram-root", str(tmp_path / "ram"), "--keep-ram-stage",
    ])
    assert cdr_daily.run_once(args) == 1
    assert captured["previous"] == previous


def test_stale_marker_is_preserved_and_rerun_gets_new_revision_marker(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: TODAY)
    monkeypatch.setattr(cdr_daily, "run_ingest", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "persist_ingest_status", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "copytree_atomic", lambda *a, **k: None)
    monkeypatch.setattr(cdr_daily, "write_sanity_report", lambda *a, **k: None)
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    state.mkdir()
    stale_marker = state / f"{TODAY}.done.json"
    stale_bytes = b'{"stale":true}'
    stale_marker.write_bytes(stale_bytes)
    captured = {}

    def fake_build(_run_root, out_dir, _db_path, *, previous_run_root=None):
        return {"run_date": TODAY, "out_dir": str(out_dir), "banks": {"rates": 1}}

    def fake_finalize(export, _state, marker, **kwargs):
        captured.update(
            export=export,
            marker=marker,
            parent=kwargs.get("parent_generation_id"),
        )
        return {**kwargs["result"], "observation_state": "complete"}

    monkeypatch.setattr(cdr_daily, "build_outputs", fake_build)
    monkeypatch.setattr(cdr_daily, "finalize_observation", fake_finalize)
    args = cdr_daily.parse_args(
        [
            "--date",
            TODAY,
            "--runs",
            str(runs),
            "--state",
            str(state),
            "--ram-stage",
            "--ram-root",
            str(tmp_path / "ram"),
            "--keep-ram-stage",
        ]
    )

    assert cdr_daily.run_once(args) == 1
    assert stale_marker.read_bytes() == stale_bytes
    assert captured["marker"] != stale_marker
    assert "_revisions" in captured["export"].parts
    assert captured["parent"] is None
