"""Manual archive control boundaries; no synthetic banking observations."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import ar_local_operation_lock as locks
import pi_payload_daily_archive as archive
import pi_payload_manual_continuity as continuity

NOW = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)
DIGEST = "a" * 64


@pytest.fixture
def proof(tmp_path):
    return continuity.ManualArchiveProof(tmp_path / "preflight.json", continuity.PREFLIGHT_SHA)


@pytest.fixture
def cleared(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "data_state_root", lambda _: tmp_path / "state")
    monkeypatch.setattr(archive.time, "monotonic", lambda: 10000)
    fields = {"LoadState": "loaded", "ActiveState": "inactive", "MainPID": "0", "ControlPID": "0",
              "ControlGroup": "", "ExecMainStartTimestampMonotonic": "0",
              "ExecMainExitTimestampMonotonic": "0", "InactiveEnterTimestampMonotonic": "0"}
    run = Mock(side_effect=lambda *a, **kw: SimpleNamespace(stdout="\n".join(f"{k}={v}" for k, v in fields.items())))
    monkeypatch.setattr(archive.subprocess, "run", run)
    return fields, run


def test_postboot_refusal_default_and_explicit_proof_only(tmp_path, monkeypatch, cleared, proof):
    verify = Mock(return_value={})
    monkeypatch.setattr(continuity.ManualArchiveProof, "verify", verify)
    assert archive.ingest_clearance(tmp_path, NOW) == "current_natural_ingest_terminal_unverified"
    assert not verify.called
    assert archive.ingest_clearance(tmp_path, NOW, manual_proof=proof, archive_day=continuity.DAY) == ""
    verify.assert_called_once_with(continuity.DAY, owner=None)


@pytest.mark.parametrize("field,value", [("ActiveState", "active"), ("MainPID", "123"), ("LoadState", "not-found")])
def test_manual_proof_cannot_override_live_or_unknown_ingest(tmp_path, monkeypatch, cleared, proof, field, value):
    cleared[0][field] = value
    verify = Mock(side_effect=AssertionError("must not reach continuity"))
    monkeypatch.setattr(continuity.ManualArchiveProof, "verify", verify)
    assert archive.ingest_clearance(tmp_path, NOW, manual_proof=proof, archive_day=continuity.DAY) == "ingest_not_terminal"
    assert not verify.called


def test_manual_proof_still_checks_second_ingest_and_cgroup(tmp_path, monkeypatch, cleared, proof):
    verify = Mock(return_value={})
    monkeypatch.setattr(continuity.ManualArchiveProof, "verify", verify)
    group = tmp_path / "cgroup/system.slice" / archive.UNITS[1]
    group.mkdir(parents=True)
    (group / "cgroup.procs").write_text("123")
    assert archive.ingest_clearance(tmp_path, NOW, manual_proof=proof, archive_day=continuity.DAY,
                                   cgroup_root=tmp_path / "cgroup") == "ingest_cgroup_not_clear"
    assert not verify.called


def test_under_lock_requires_actual_owner_and_failed_proof_is_closed(tmp_path, monkeypatch, cleared, proof):
    assert archive.ingest_clearance(tmp_path, NOW, include_lock=False, manual_proof=proof) == "invalid_manual_archive_proof_context"
    monkeypatch.setattr(continuity.ManualArchiveProof, "verify", Mock(side_effect=AssertionError("changed boot")))
    assert archive.ingest_clearance(tmp_path, NOW, manual_proof=proof, archive_day=continuity.DAY) == "ingest_terminal_state_unavailable"


def test_owned_token_checks_live_descriptor_record_and_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "_current_boot_id", lambda: continuity.BOOT)
    path = tmp_path / "daily-ingest.lock"
    with locks.production_lock(path, "daily-payload-archive") as owner:
        assert owner.verified_record()["role"] == "daily-payload-archive"
        raw = path.read_text()
        path.write_text(raw.replace("daily-payload-archive", "foreign"))
        with pytest.raises(RuntimeError):
            owner.verified_record()
        path.write_text(raw)
    with pytest.raises(RuntimeError, match="no longer active"):
        owner.verified_record()


def test_old_token_rejected_after_actual_descriptor_reuse_and_reacquisition(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "_current_boot_id", lambda: continuity.BOOT)
    path = tmp_path / "daily-ingest.lock"
    with locks.production_lock(path, "daily-payload-archive") as old:
        old.verified_record()
    with locks.production_lock(path, "daily-payload-archive") as new:
        assert new.acquisition_id != old.acquisition_id
        assert new.verified_record()["role"] == old.role
        duplicated = new.descriptor != old.descriptor
        if duplicated:
            try:
                os.fstat(old.descriptor)
            except OSError:
                pass
            else:
                pytest.skip("old descriptor belongs to an unrelated test/runtime handle")
            os.dup2(new.descriptor, old.descriptor)
        try:
            assert os.fstat(old.descriptor).st_ino == os.fstat(new.descriptor).st_ino
            with pytest.raises(RuntimeError, match="no longer active"):
                old.verified_record()
        finally:
            if duplicated:
                os.close(old.descriptor)


def test_owned_lock_rejects_hardlink(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "_current_boot_id", lambda: continuity.BOOT)
    path = tmp_path / "daily-ingest.lock"
    alias = tmp_path / "alias.lock"
    with locks.production_lock(path, "daily-payload-archive") as owner:
        try:
            os.link(path, alias)
        except PermissionError:
            if os.name == "nt":
                pytest.skip("Windows denies hardlinking the held lock; Linux control remains required")
            raise
        try:
            with pytest.raises(RuntimeError, match="ownership changed"):
                owner.verified_record()
        finally:
            alias.unlink()
        owner.verified_record()


def test_owned_lock_rejects_replaced_path(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "_current_boot_id", lambda: continuity.BOOT)
    path = tmp_path / "daily-ingest.lock"
    replacement = tmp_path / "replacement.lock"
    with locks.production_lock(path, "daily-payload-archive") as owner:
        replacement.write_bytes(path.read_bytes())
        try:
            os.replace(replacement, path)
        except PermissionError:
            if os.name == "nt":
                pytest.skip("Windows denies replacing the held lock; Linux control remains required")
            raise
        with pytest.raises(RuntimeError, match="ownership changed"):
            owner.verified_record()
    assert path.exists(), "context must not delete the replacement's lock"


@pytest.mark.parametrize("args", [["--once", "--manual-proof", "proof", "--manual-proof-sha256", continuity.PREFLIGHT_SHA],
                                  ["--date", continuity.DAY, "--manual-proof", "proof"]])
def test_scheduler_and_unpaired_proof_cli_rejected(args):
    with pytest.raises(SystemExit) as error:
        archive.main(args)
    assert error.value.code == 2


def test_proof_no_arbitrary_digest_or_mutated_input(tmp_path, proof):
    proof.path.write_text("{}")
    with pytest.raises(ValueError, match="input changed"):
        proof.verify(continuity.DAY)
    with pytest.raises(ValueError, match="bound"):
        continuity.ManualArchiveProof(proof.path, "0" * 64).verify(continuity.DAY)


def test_proof_reserved_and_forwarded_before_child_then_required_in_receipt(tmp_path, monkeypatch, proof):
    state = tmp_path / "state"
    monkeypatch.setattr(archive, "data_state_root", lambda _: state)
    monkeypatch.setattr(archive, "window_reason", lambda _: "")
    monkeypatch.setattr(archive, "ingest_clearance", lambda *a, **kw: "")
    monkeypatch.setattr(archive, "selected_source", lambda *a: ({"contract_digest": DIGEST}, tmp_path))
    root = state / archive.STATE_DIRECTORY
    def child(command, **kwargs):
        reserved = json.loads((root / "attempts" / (continuity.DAY + ".json")).read_bytes())
        assert reserved["manual_terminal_proof_sha256"] == proof.sha256
        assert command[-4:] == ["--manual-proof", str(proof.path), "--manual-proof-sha256", proof.sha256]
        assert kwargs["timeout_seconds"] == 1800
        archive.atomic_write_json(root / "receipts" / (DIGEST + ".json"),
            {"status": "archived", "selected_for_app": False, "manifest_url": "https://github.com/archive"})
    monkeypatch.setattr(archive, "run_process_group", child)
    assert archive.run_once(tmp_path, day=continuity.DAY, manual_proof=proof)["status"] == "failed"
    attempt = json.loads((root / "attempts" / (continuity.DAY + ".json")).read_bytes())
    assert attempt["attempts"] == 1 and attempt["status"] == "failed"


def test_worker_rechecks_proof_under_its_owned_lease_before_source_and_upload(tmp_path, monkeypatch, cleared, proof):
    monkeypatch.setattr(archive, "window_reason", lambda _: "")
    monkeypatch.setattr(locks, "_current_boot_id", lambda: continuity.BOOT)
    calls = []
    def verify(self, day, *, owner=None):
        calls.append(owner)
        if owner is not None:
            assert isinstance(owner, locks.OwnedProductionLock)
            assert owner.verified_record()["role"] == "daily-payload-archive"
            raise ValueError("proof changed while acquiring lock")
    monkeypatch.setattr(continuity.ManualArchiveProof, "verify", verify)
    source = Mock(side_effect=AssertionError("must not select/build/upload"))
    monkeypatch.setattr(archive, "selected_source", source)
    with pytest.raises(RuntimeError, match="ingest_terminal_state_unavailable"):
        archive.archive_worker(tmp_path, continuity.DAY, DIGEST, manual_proof=proof)
    assert len(calls) == 2 and calls[0] is None
    assert not source.called
    assert not (tmp_path / "state/daily-ingest.lock").exists()
