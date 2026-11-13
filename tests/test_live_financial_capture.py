"""One-off authorization controls and isolated live-capture fault cases."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pi_cdr_quality_window as window
import pi_cdr_quality_activate as activate
import pi_cdr_quality_resources as resources
import pi_live_financial_capture as live
from pi_live_financial_worker import reconcile_register

TARGET = "a" * 40
NOW = datetime(2026, 11, 13, 23, 0, tzinfo=window.TZ)


def authorization(operation):
    return {"schema": window.SCHEMA, "target_commit": TARGET,
            "timezone": "Australia/Hobart", "reason": "explicit one-off operator instruction",
            "issued_at": NOW.isoformat(), "not_before": NOW.isoformat(),
            "expires_at": "2026-11-14T00:30:00+11:00",
            "operation_roots": [str(operation)], "stages": sorted(window.STAGES)}


def validate(value, operation, now=NOW, stage="quality-canary"):
    return window.validate(value, now=now, target=TARGET, operation=operation, stage=stage)


def test_scoped_window_crosses_midnight_but_never_quiet_cutoff(tmp_path):
    value = authorization(tmp_path)
    assert validate(value, tmp_path).hour == 0
    for stage in window.STAGES:
        validate(value, tmp_path, datetime(2026, 11, 14, 0, 29, tzinfo=window.TZ), stage)
        with pytest.raises(ValueError):
            validate(value, tmp_path, datetime(2026, 11, 14, 0, 30, tzinfo=window.TZ), stage)
    value["expires_at"] = "2026-11-14T00:30:01+11:00"
    with pytest.raises(ValueError, match="quiet"):
        validate(value, tmp_path)


@pytest.mark.parametrize("field,value", [
    ("operation_roots", "substring must never authorize"), ("operation_roots", {}),
    ("operation_roots", [1]), ("operation_roots", ["relative"]),
    ("stages", "quality-canary"), ("stages", {}), ("stages", ["other"]),
    ("target_commit", "b" * 40), ("timezone", "UTC"), ("reason", ""),
    ("issued_at", "2026-11-13T18:00:00+11:00"),
    ("not_before", "2026-11-14T00:00:00+11:00"),
    ("expires_at", "2026-11-13T23:00:00+11:00"),
])
def test_window_rejects_ambiguous_or_out_of_scope_authority(tmp_path, field, value):
    receipt = authorization(tmp_path)
    receipt[field] = value
    with pytest.raises(ValueError):
        validate(receipt, tmp_path)


def test_window_is_exact_path_and_hash_bound(tmp_path):
    receipt = authorization(tmp_path)
    with pytest.raises(ValueError, match="cover"):
        validate(receipt, tmp_path / "child")
    path = tmp_path / "authorization.json"
    raw = json.dumps(receipt).encode()
    path.write_bytes(raw)
    ref = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    window.load(ref, now=NOW, target=TARGET, operation=tmp_path, stage="quality-seal")
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="changed"):
        window.load(ref, now=NOW, target=TARGET, operation=tmp_path, stage="quality-activate")


def test_legacy_guard_keeps_default_and_extension_is_revalidated(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(activate, "guard", lambda *a, **kw: seen.append((a, kw)))
    assert activate.operation_guard(tmp_path, tmp_path, None, TARGET, tmp_path, "quality-canary") is None
    assert seen == [((tmp_path, tmp_path), {})]
    monkeypatch.setattr(window, "load", lambda *a, **kw: NOW + timedelta(hours=1))
    activate.operation_guard(tmp_path, tmp_path, {}, TARGET, tmp_path, "quality-seal")
    assert seen[-1][1] == {"approved_deadline": NOW + timedelta(hours=1)}
    def expired(*a, **kw):
        raise ValueError("expired")
    monkeypatch.setattr(window, "load", expired)
    with pytest.raises(ValueError, match="expired"):
        activate.operation_guard(tmp_path, tmp_path, {}, TARGET, tmp_path, "quality-activate")
    assert len(seen) == 2


def test_launch_contains_writes_and_parent_lifetime(tmp_path):
    args = SimpleNamespace(source=tmp_path / "source", operation=tmp_path / "operation")
    properties = live.launch_properties(args, "unused", "ar-local-shared-task-parent.service", 900)
    assert "CPUQuota=200%" in properties
    assert "MemoryMax=3G" in properties and "MemorySwapMax=0" in properties
    assert "BindsTo=ar-local-shared-task-parent.service" in properties
    assert "KillMode=control-group" in properties and "RuntimeMaxSec=930s" in properties
    writes = [p for p in properties if p.startswith("ReadWritePaths=")]
    assert writes == [f"ReadWritePaths={args.operation}", f"ReadWritePaths={live.ram_root(args)}"]
    env = live.environment(args)
    assert env[:2] == ["/usr/bin/env", "-i"]
    assert f"RCLONE_CONFIG={args.operation / 'config/rclone.conf'}" in env


@pytest.mark.parametrize("unit,allowed", [
    ("ar-local-live-capture-a0b1c2d3e4f5.service", True),
    ("ar-local-live-capture-123.service", False),
    ("ar-local-live-capture-abcdefabcdefx.service", False),
    ("ar-local-live-capture-ABCDEFABCDEF.service", False),
    ("other.service", False),
])
def test_resource_supervisor_only_accepts_owned_live_unit_pattern(unit, allowed):
    assert bool(resources.UNIT.fullmatch(unit)) is allowed


def test_failure_preservation_keeps_original_bytes_and_refuses_expired_copy(tmp_path):
    source, destination = tmp_path / "ram", tmp_path / "disk"
    source.mkdir()
    (source / "evidence").write_bytes(b"retained bytes")
    result = live.preserve_failed_stage(source, destination, datetime.now(timezone.utc) + timedelta(minutes=2))
    assert result["result"] == "COPIED" and result["source_deleted"] is False
    assert (source / "evidence").read_bytes() == (destination / "evidence").read_bytes()
    with pytest.raises(TimeoutError):
        live.preserve_failed_stage(source, tmp_path / "late", datetime.now(timezone.utc))
    assert (source / "evidence").read_bytes() == b"retained bytes"


def promoted_control(tmp_path, monkeypatch):
    from tests.test_cdr_attempt_evidence_promotion import _source
    from cdr_attempt_evidence_promotion import promote_attempt_evidence
    import cdr_ingest_support
    run, exports = tmp_path / "run", tmp_path / "exports"
    _, status = _source(run)
    row = {"endpoint_url": "https://holder.example", "brand_name": "Control", "legal_entity_name": "Control"}
    status["provider_states"][0].update(row)
    (run / "banks/ingest-status.json").write_text(json.dumps(status))
    promote_attempt_evidence(run, exports)
    status = json.loads((exports / "ingest-status.json").read_text())
    monkeypatch.setattr(cdr_ingest_support, "iter_banking_brands_from_payload", lambda _: iter([row]))
    return exports, status


def test_register_reconciliation_requires_entire_promoted_committed_inventory(tmp_path, monkeypatch):
    exports, status = promoted_control(tmp_path, monkeypatch)
    before = {str(p): p.read_bytes() for p in exports.rglob("*") if p.is_file()}
    assert reconcile_register(exports, status)["registered"] == 1
    assert before == {str(p): p.read_bytes() for p in exports.rglob("*") if p.is_file()}
    root = exports / status["raw_attempt_journal"]["path"]
    (root / "events/uncommitted.json").write_text("{}")
    from cdr_attempt_evidence_promotion import AttemptEvidencePromotionError
    with pytest.raises(AttemptEvidencePromotionError):
        reconcile_register(exports, status)


def test_register_reconciliation_rejects_wrong_head_or_missing_provider(tmp_path, monkeypatch):
    exports, status = promoted_control(tmp_path, monkeypatch)
    status["providers_attempted"] = 0
    with pytest.raises(ValueError, match="every discovered"):
        reconcile_register(exports, status)
    status["providers_attempted"] = 1
    status["raw_attempt_journal"]["head_digest"] = "0" * 64
    from cdr_attempt_evidence_promotion import AttemptEvidencePromotionError
    with pytest.raises(AttemptEvidencePromotionError):
        reconcile_register(exports, status)


def test_ingest_uses_production_automatic_ram_and_detail_defaults(tmp_path):
    from pi_live_financial_worker import ingest_command
    from ar_local_launcher_constants import DAILY_WORKER_COUNT
    args = SimpleNamespace(python=Path("python"), source=tmp_path / "source", operation=tmp_path / "op")
    command = ingest_command(args, "2026-11-13", DAILY_WORKER_COUNT)
    assert command[command.index("--workers") + 1] == str(DAILY_WORKER_COUNT)
    assert "--detail-workers" not in command
    assert "--ram-stage" not in command and "--no-ram-stage" not in command
    assert command[command.index("--ram-root") + 1] == live.ram_root(args)
    from cdr_daily import parse_args
    parsed = parse_args([str(item) for item in command[3:]])
    production = parse_args(["--workers", str(DAILY_WORKER_COUNT), "--archive-failed-ram-stage", "--banks-only"])
    assert (parsed.ram_stage, parsed.no_ram_stage, parsed.ingest_arg) == (
        production.ram_stage, production.no_ram_stage, production.ingest_arg)
    assert not parsed.ram_stage and not parsed.no_ram_stage
