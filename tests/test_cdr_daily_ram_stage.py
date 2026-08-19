"""RAM-stage integration for hash-bound raw-attempt evidence promotion."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import cdr_daily
import cdr_outputs
from cdr_atomic import atomic_write_json
from cdr_finalization import verify_completion_marker
from cdr_raw_attempt_journal import RawAttemptJournal


DATE = "2026-08-15"
SESSION = "ingest-20260815T010000000000Z-112233445566"


def _write_ingest(run_root):
    journal = RawAttemptJournal(run_root / "_raw-attempt-journals-v1", SESSION)
    body = b'{"data":{"products":[]}}'
    journal.record(
        "register:1|nonce|1",
        request_url="https://register.example/holders",
        status=200,
        outcome="success",
        body=body,
        started_at="2026-08-15T01:00:00.000000Z",
        completed_at="2026-08-15T01:00:01.000000Z",
        wire_bytes=len(body),
        inflated_bytes=len(body),
        wire_sha256=hashlib.sha256(body).hexdigest(),
        peer_ip="8.8.8.8",
        context={"phase": "register_discovery"},
    )
    summary = journal.summary()
    atomic_write_json(
        run_root / "banks" / "ingest-status.json",
        {
            "total": 0,
            "corrupt_records": 0,
            "unattributed_records": 0,
            "failure_provenance_complete": True,
            "incomplete": False,
            "by_phase": {},
            "by_status": {},
            "by_provider": {},
            "register_provenance_complete": True,
            "register_attempts": [
                {
                    "source_url": "https://register.example/holders",
                    "mode": "plain",
                    "ok": True,
                    "status": 200,
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            ],
            "providers_registered": 1,
            "providers_attempted": 1,
            "provider_states": [
                {
                    "provider_uid": "legacy-prd:" + "a" * 64,
                    "state": "complete",
                    "failure_records": 0,
                }
            ],
            "raw_attempt_journal": {
                **summary,
                "path": f"_raw-attempt-journals-v1/{SESSION}",
                "path_resolution": "relative_to_ingest_run_root",
                "retention": "follows_ingest_run_root",
            },
        },
    )


def _configure(tmp_path, monkeypatch, *, rates=1):
    data = tmp_path / "data"
    runs = data / "runs"
    state = data / "state"
    ram = tmp_path / "ram"
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *_args: None)
    monkeypatch.setattr(cdr_daily, "local_date", lambda: DATE)
    monkeypatch.setattr(cdr_daily, "write_sanity_report", lambda *_args: None)
    monkeypatch.setattr(cdr_daily, "_emit_day_manifest", lambda *_args: None)

    def ingest(_script_dir, out_dir, date, _extra):
        assert date == DATE
        _write_ingest(out_dir / date)

    def build(_run_root, export_root, _db, *, previous_run_root=None):
        assert previous_run_root is None
        cache = export_root / "dashboard-cache"
        cache.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            cache / "latest.json",
            {
                "run_date": DATE,
                "banks_counts": {
                    "products": 1 if rates else 0,
                    "rates": rates,
                    "fees": 0,
                    "features": 0,
                    "eligibility": 0,
                    "constraints": 0,
                },
            },
        )
        (export_root / "banks.json").write_text('{"rates":[]}', encoding="utf-8")
        return {"run_date": DATE, "banks_counts": {"rates": rates}}

    monkeypatch.setattr(cdr_daily, "run_ingest", ingest)
    monkeypatch.setattr(cdr_daily, "build_outputs", build)
    args = cdr_daily.parse_args(
        [
            "--date",
            DATE,
            "--runs",
            str(runs),
            "--state",
            str(state),
            "--ram-stage",
            "--ram-root",
            str(ram),
        ]
    )
    return args, runs, state, ram


def _failed_stage_paths(tmp_path):
    runs = tmp_path / "data" / "runs"
    ram = tmp_path / "ram"
    raw = ram / "runs" / DATE
    derived = ram / "exports" / DATE
    (raw / "_raw-attempt-journals-v1" / SESSION).mkdir(parents=True)
    (derived / "_exports" / "attempt-evidence" / SESSION).mkdir(parents=True)
    (raw / "_raw-attempt-journals-v1" / SESSION / "attempt.json").write_bytes(
        b'{"status":406,"wire_sha256":"preserved"}\n'
    )
    (derived / "_exports" / "attempt-evidence" / SESSION / "summary.json").write_bytes(
        b'{"verified":true,"attempts":1}\n'
    )
    return runs, ram, raw, derived


def test_successful_ram_stage_finalizes_evidence_before_source_cleanup(
    tmp_path,
    monkeypatch,
):
    args, runs, state, ram = _configure(tmp_path, monkeypatch)

    assert cdr_daily.run_once(args) == 1

    export_root = runs / DATE / "_exports"
    status = json.loads(
        (export_root / "ingest-status.json").read_text(encoding="utf-8")
    )
    pointer = status["raw_attempt_journal"]
    assert pointer["path_resolution"] == "relative_to_finalized_export_root"
    destination = export_root / pointer["path"]
    assert destination.is_dir()
    assert RawAttemptJournal(destination.parent, SESSION).summary()["verified"] is True
    marker_path = state / f"{DATE}.done.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert verify_completion_marker(marker, state, DATE) is True
    assert not (ram / "runs" / DATE).exists()
    assert not (ram / "exports" / DATE).exists()


def test_automatic_pi_stage_keeps_large_exports_off_tmpfs(tmp_path, monkeypatch):
    args, runs, state, ram = _configure(tmp_path, monkeypatch)
    args.ram_stage = False
    monkeypatch.setattr(cdr_daily, "is_raspberry_pi", lambda: True)
    expected_stage = runs.parent / ".daily-export-stage" / DATE / "_exports"
    configured_ingest = cdr_daily.run_ingest

    def ingest(script_dir, out_dir, date, extra):
        configured_ingest(script_dir, out_dir, date, extra)
        detail = out_dir / date / "banks" / "Mortgage" / "Example Bank" / "loan-1"
        detail.mkdir(parents=True)
        (detail / "product-detail.json").write_text(
            json.dumps({
                "data": {
                    "productId": "loan-1",
                    "name": "Example variable home loan",
                    "brand": "Example Bank",
                    "features": [],
                    "eligibility": [],
                    "constraints": [],
                    "fees": [],
                    "lendingRates": [{
                        "lendingRateType": "VARIABLE",
                        "rate": "5.50",
                        "comparisonRate": "5.70",
                    }],
                },
            }),
            encoding="utf-8",
        )

    monkeypatch.setattr(cdr_daily, "run_ingest", ingest)

    def build(run_root, export_root, db_path, *, previous_run_root=None):
        assert export_root == expected_stage
        assert not str(export_root).startswith(str(ram))
        return cdr_outputs.build_outputs(
            run_root,
            export_root,
            db_path,
            previous_run_root=previous_run_root,
        )

    monkeypatch.setattr(cdr_daily, "build_outputs", build)

    assert cdr_daily.run_once(args) == 1

    exported = json.loads(
        (runs / DATE / "_exports" / f"banks-{DATE}.json").read_text(encoding="utf-8")
    )
    assert len(exported["rates"]) == 1
    assert not (ram / "runs" / DATE).exists()
    assert not (ram / "exports").exists()
    assert not expected_stage.exists()
    assert (state / f"{DATE}.done.json").is_file()


def test_completed_pi_run_retries_failed_persistent_stage_cleanup(tmp_path, monkeypatch):
    args, runs, _state, _ram = _configure(tmp_path, monkeypatch)
    args.ram_stage = False
    monkeypatch.setattr(cdr_daily, "is_raspberry_pi", lambda: True)
    staged_date = runs.parent / ".daily-export-stage" / DATE
    real_rmtree = cdr_daily.shutil.rmtree
    blocked_once = False

    def flaky_rmtree(path, *call_args, **call_kwargs):
        nonlocal blocked_once
        if Path(path) == staged_date and not blocked_once:
            blocked_once = True
            return None
        return real_rmtree(path, *call_args, **call_kwargs)

    monkeypatch.setattr(cdr_daily.shutil, "rmtree", flaky_rmtree)

    assert cdr_daily.run_once(args) == 1
    assert staged_date.is_dir()
    assert cdr_daily.run_once(args) == 0
    assert not staged_date.exists()


def test_zero_rate_ram_stage_preserves_source_and_never_installs_target(
    tmp_path,
    monkeypatch,
):
    args, runs, _state, ram = _configure(tmp_path, monkeypatch, rates=0)

    assert cdr_daily.run_once(args) == 2

    assert (ram / "runs" / DATE / "_raw-attempt-journals-v1" / SESSION).is_dir()
    assert (ram / "exports" / DATE / "_exports" / "attempt-evidence").is_dir()
    assert not (runs / DATE / "_exports").exists()

    source_before = {
        path.relative_to(ram).as_posix(): path.read_bytes()
        for path in ram.rglob("*")
        if path.is_file()
    }
    with pytest.raises(RuntimeError, match="preserved RAM-stage evidence"):
        cdr_daily.run_once(args)
    assert {
        path.relative_to(ram).as_posix(): path.read_bytes()
        for path in ram.rglob("*")
        if path.is_file()
    } == source_before


def test_failed_ram_stage_is_archived_create_once_before_retry(tmp_path, monkeypatch):
    runs, _ram, raw, derived = _failed_stage_paths(tmp_path)
    raw_before = {
        path.relative_to(raw).as_posix(): path.read_bytes()
        for path in raw.rglob("*") if path.is_file()
    }
    derived_before = {
        path.relative_to(derived).as_posix(): path.read_bytes()
        for path in derived.rglob("*") if path.is_file()
    }

    archive = cdr_daily.archive_failed_ram_stage(raw, derived, runs / DATE)
    assert archive is not None
    assert not raw.exists() and not derived.exists()
    assert {
        path.relative_to(archive / "runs").as_posix(): path.read_bytes()
        for path in (archive / "runs").rglob("*") if path.is_file()
    } == raw_before
    assert {
        path.relative_to(archive / "exports").as_posix(): path.read_bytes()
        for path in (archive / "exports").rglob("*") if path.is_file()
    } == derived_before


def test_failed_ram_archive_ignores_and_cleans_directory_only_export_stage(tmp_path):
    runs, _ram, raw, derived = _failed_stage_paths(tmp_path)
    for path in sorted(derived.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()

    archive = cdr_daily.archive_failed_ram_stage(raw, derived, runs / DATE)

    assert archive is not None
    assert (archive / "runs" / "_raw-attempt-journals-v1" / SESSION / "attempt.json").is_file()
    assert not (archive / "exports").exists()
    assert not raw.exists() and not derived.exists()


def test_failed_ram_archive_recovers_old_transaction_with_empty_export_stage(tmp_path):
    runs, _ram, raw, derived = _failed_stage_paths(tmp_path)
    for path in sorted(derived.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
    archive_parent = runs / DATE / "_failed_attempts"
    transaction = {
        "schema_version": 1,
        "archive_name": "ram-123",
        "source_names": ["runs", "exports"],
        "state": "copying",
    }
    cdr_daily.atomic_write_json(
        archive_parent / ".ram-stage-archive.json",
        transaction,
        create_once=True,
    )

    archive = cdr_daily.archive_failed_ram_stage(raw, derived, runs / DATE)

    assert archive == archive_parent / "ram-123"
    assert (archive / "runs" / "_raw-attempt-journals-v1" / SESSION / "attempt.json").is_file()
    assert not (archive / "exports").exists()
    assert not raw.exists() and not derived.exists()
    assert not (archive_parent / ".ram-stage-archive.json").exists()


def test_failed_ram_archive_recovers_after_crash_during_source_cleanup(
    tmp_path,
    monkeypatch,
):
    runs, _ram, raw, derived = _failed_stage_paths(tmp_path)
    original_rmtree = cdr_daily.shutil.rmtree
    crashed = False

    def crash_mid_cleanup(path):
        nonlocal crashed
        if not crashed:
            crashed = True
            first_file = next(item for item in path.rglob("*") if item.is_file())
            first_file.unlink()
            raise OSError("simulated power loss during cleanup")
        return original_rmtree(path)

    monkeypatch.setattr(cdr_daily.shutil, "rmtree", crash_mid_cleanup)
    with pytest.raises(OSError, match="power loss"):
        cdr_daily.archive_failed_ram_stage(raw, derived, runs / DATE)

    transaction = runs / DATE / "_failed_attempts" / ".ram-stage-archive.json"
    assert transaction.is_file()
    monkeypatch.setattr(cdr_daily.shutil, "rmtree", original_rmtree)
    archive = cdr_daily.archive_failed_ram_stage(raw, derived, runs / DATE)

    assert archive is not None
    assert not raw.exists() and not derived.exists()
    assert not transaction.exists()
    assert (archive / "runs").is_dir()
    assert (archive / "exports").is_dir()


def test_finalizer_failure_preserves_staged_and_installed_evidence(
    tmp_path,
    monkeypatch,
):
    args, runs, state, ram = _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cdr_daily,
        "finalize_observation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated finalizer crash")
        ),
    )

    with pytest.raises(RuntimeError, match="finalizer crash"):
        cdr_daily.run_once(args)

    assert (ram / "runs" / DATE / "_raw-attempt-journals-v1" / SESSION).is_dir()
    assert (ram / "exports" / DATE / "_exports" / "attempt-evidence").is_dir()
    installed = runs / DATE / "_exports"
    assert (installed / "attempt-evidence").is_dir()
    assert not (state / f"{DATE}.done.json").exists()


def test_unverified_completion_never_triggers_ram_cleanup(tmp_path, monkeypatch):
    args, _runs, state, ram = _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cdr_daily,
        "finalize_observation",
        lambda *_args, **_kwargs: {
            "run_date": DATE,
            "banks_counts": {"rates": 1},
            "finalization_schema_version": 2,
        },
    )

    with pytest.raises(RuntimeError, match="completion marker verifies"):
        cdr_daily.run_once(args)

    assert (ram / "runs" / DATE / "_raw-attempt-journals-v1" / SESSION).is_dir()
    assert (ram / "exports" / DATE / "_exports" / "attempt-evidence").is_dir()
    assert not (state / f"{DATE}.done.json").exists()


def test_same_day_revision_gets_its_own_hash_bound_evidence_without_mutating_primary(
    tmp_path,
    monkeypatch,
):
    args, runs, state, _ram = _configure(tmp_path, monkeypatch)
    assert cdr_daily.run_once(args) == 1
    primary = runs / DATE / "_exports"
    primary_before = {
        path.relative_to(primary).as_posix(): path.read_bytes()
        for path in primary.rglob("*")
        if path.is_file()
    }
    primary_marker_before = (state / f"{DATE}.done.json").read_bytes()

    args.force = True
    assert cdr_daily.run_once(args) == 1

    revisions = list((runs / DATE / "_revisions").glob("*/_exports"))
    assert len(revisions) == 1
    revision = revisions[0]
    revision_status = json.loads(
        (revision / "ingest-status.json").read_text(encoding="utf-8")
    )
    pointer = revision_status["raw_attempt_journal"]
    assert pointer["path_resolution"] == "relative_to_finalized_export_root"
    evidence = revision / pointer["path"]
    assert RawAttemptJournal(evidence.parent, SESSION).summary()["verified"] is True
    revision_marker_path = state / f"{DATE}.revision.{revision.parent.name}.json"
    revision_marker = json.loads(revision_marker_path.read_text(encoding="utf-8"))
    assert verify_completion_marker(revision_marker, state, DATE) is True
    assert (state / f"{DATE}.done.json").read_bytes() == primary_marker_before
    assert {
        path.relative_to(primary).as_posix(): path.read_bytes()
        for path in primary.rglob("*")
        if path.is_file()
    } == primary_before


def _staged_evidence(ram: Path) -> Path:
    return (
        ram
        / "exports"
        / DATE
        / "_exports"
        / "attempt-evidence"
        / "raw-attempt-journals-v1"
        / SESSION
    )


def test_export_build_failure_still_preserves_captured_attempt_evidence(
    tmp_path, monkeypatch
):
    """A crash after the last fetch must not take the night's wire evidence with it."""
    args, _runs, _state, ram = _configure(tmp_path, monkeypatch)

    def exploding_build(*_args, **_kwargs):
        raise MemoryError("export build ran out of memory")

    monkeypatch.setattr(cdr_daily, "build_outputs", exploding_build)

    with pytest.raises(MemoryError):
        cdr_daily.run_once(args)

    assert _staged_evidence(ram).is_dir()


def test_nonzero_ingest_exit_still_preserves_captured_attempt_evidence(
    tmp_path, monkeypatch
):
    """cdr_full_ingest publishes its status on early exits; keep that evidence."""
    args, _runs, _state, ram = _configure(tmp_path, monkeypatch)

    def failing_ingest(_script_dir, out_dir, date, _extra):
        _write_ingest(out_dir / date)
        raise subprocess.CalledProcessError(2, "cdr_full_ingest.py")

    monkeypatch.setattr(cdr_daily, "run_ingest", failing_ingest)

    with pytest.raises(subprocess.CalledProcessError):
        cdr_daily.run_once(args)

    assert _staged_evidence(ram).is_dir()


def test_preserving_evidence_never_raises(tmp_path, monkeypatch, capsys):
    """Best-effort by design: preservation must never be why an ingest fails."""

    def exploding_promotion(_run_dir, _export_root):
        raise RuntimeError("promotion unavailable")

    monkeypatch.setattr(cdr_daily, "persist_ingest_status", exploding_promotion)

    cdr_daily.preserve_attempt_evidence(tmp_path / "run", tmp_path / "_exports")

    assert "could not preserve raw attempt evidence" in capsys.readouterr().err
