from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import laptop_backup_dispatcher as dispatcher


ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(("git", "-C", str(repo), *args), check=True, capture_output=True, text=True).stdout.strip()


def fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    receiver = tmp_path / "receivers" / "candidate"
    receiver.mkdir(parents=True)
    entrypoint = receiver / "run_laptop_backup_task.ps1"
    entrypoint.write_text("exit 0\n", encoding="utf-8")
    (receiver / "laptop_backup_scheduled.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    docs = receiver / "docs"
    docs.mkdir()
    (docs / "PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md").write_bytes(
        (ROOT / "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md").read_bytes()
    )
    (docs / "PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md").write_bytes(
        (ROOT / "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md").read_bytes()
    )
    git(receiver, "init")
    git(receiver, "config", "user.email", "test@example.invalid")
    git(receiver, "config", "user.name", "Dispatcher Test")
    git(receiver, "add", ".")
    git(receiver, "commit", "-m", "candidate")
    candidate = git(receiver, "rev-parse", "HEAD")
    git(receiver, "checkout", "--detach", candidate)

    target = tmp_path / "target"
    control = target / "dispatcher-control"
    evidence = target / "evidence" / "gate.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"result":"PASS"}\n', encoding="utf-8")
    control.mkdir(parents=True)
    recovery = tmp_path / "recovery.img"
    recovery.write_bytes(b"recovery")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "sequence": 1,
        "activation_id": "1" * 32,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "previous_manifest_sha256": None,
        "plan_document_id": "ARL-OPS-001",
        "plan_version": "1.5",
        "plan_git_commit": candidate,
        "plan_sha256": "a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada",
        "authority_commit": candidate,
        "handoff_sha256": dispatcher.sha256_file(docs / "PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md"),
        "authority_repo": str(receiver),
        "authority_handoff_path": "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md",
        "candidate_code_sha": candidate,
        "protected_code_sha": "e" * 40,
        "operator": "jkoka",
        "operator_sid": "S-1-test",
        "receiver": str(receiver),
        "allowed_receiver_root": str(receiver.parent),
        "entrypoint": entrypoint.name,
        "entrypoint_sha256": dispatcher.sha256_file(entrypoint),
        "python_path": str(Path(sys.executable).resolve()),
        "python_sha256": dispatcher.sha256_file(Path(sys.executable).resolve()),
        "scheduled_plan_git_commit": "f" * 40,
        "target": str(target),
        "recovery_image": str(recovery),
        "gate_evidence_path": str(evidence),
        "gate_evidence_sha256": dispatcher.sha256_file(evidence),
    }
    return control, target, manifest


def write_manifest(path: Path, value: dict[str, object]) -> str:
    payload = dispatcher.canonical_json(value)
    path.write_bytes(payload)
    return dispatcher.sha256_bytes(payload)


def test_activate_and_limited_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control, _target, manifest = fixture(tmp_path)
    proposed = tmp_path / "manifest.json"
    digest = write_manifest(proposed, manifest)
    result = dispatcher.activate(control, proposed)
    assert result["manifest_sha256"] == digest
    monkeypatch.setenv("AR_DISPATCHER_TEST_SID", "S-1-test")
    monkeypatch.delenv("AR_DISPATCHER_TEST_ADMIN", raising=False)
    probe = dispatcher.probe(control)
    assert probe == {
        "ok": True,
        "result": "PASS",
        "mode": "PROBE",
        "is_admin": False,
        "operator_sid": "S-1-test",
        "sequence": 1,
        "candidate_code_sha": manifest["candidate_code_sha"],
        "manifest_sha256": digest,
    }


def test_probe_rejects_elevated_or_wrong_sid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control, _target, manifest = fixture(tmp_path)
    proposed = tmp_path / "manifest.json"
    write_manifest(proposed, manifest)
    dispatcher.activate(control, proposed)
    monkeypatch.setenv("AR_DISPATCHER_TEST_SID", "S-1-wrong")
    with pytest.raises(ValueError, match="token SID"):
        dispatcher.probe(control)
    monkeypatch.setenv("AR_DISPATCHER_TEST_SID", "S-1-test")
    monkeypatch.setenv("AR_DISPATCHER_TEST_ADMIN", "1")
    with pytest.raises(ValueError, match="must not run elevated"):
        dispatcher.probe(control)


def test_duplicate_and_unknown_fields_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        dispatcher.parse_json(b'{"a":1,"a":2}', "test")
    _control, _target, manifest = fixture(tmp_path)
    manifest["unexpected"] = True
    with pytest.raises(ValueError, match="fields are not exact"):
        dispatcher.validate_manifest(manifest, activation=True)


def test_entrypoint_traversal_and_dirty_receiver_are_rejected(tmp_path: Path) -> None:
    _control, _target, manifest = fixture(tmp_path)
    manifest["entrypoint"] = "../outside.ps1"
    with pytest.raises(ValueError, match="one fixed file name"):
        dispatcher.validate_manifest(manifest, activation=True)
    manifest["entrypoint"] = "run_laptop_backup_task.ps1"
    Path(str(manifest["receiver"]), "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty, attached, or not at"):
        dispatcher.validate_manifest(manifest, activation=True)


def test_failure_after_pointer_restores_old_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control, _target, manifest = fixture(tmp_path)
    proposed = tmp_path / "manifest.json"
    write_manifest(proposed, manifest)
    original = dispatcher.immutable_write

    def fail_pass(path: Path, payload: bytes) -> None:
        if path.name.endswith("-pass.json"):
            raise OSError("simulated receipt failure")
        original(path, payload)

    monkeypatch.setattr(dispatcher, "immutable_write", fail_pass)
    with pytest.raises(OSError, match="simulated"):
        dispatcher.activate(control, proposed)
    assert not (control / "active-runner.json").exists()
    assert len(list((control / "activation-receipts").glob("*-rolled_back.json"))) == 1


def test_reconcile_finishes_crash_after_pointer_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control, _target, manifest = fixture(tmp_path)
    paths = dispatcher.layout(control)
    raw = dispatcher.canonical_json(manifest)
    digest = dispatcher.sha256_bytes(raw)
    dispatcher.immutable_write(paths["manifests"] / f"{digest}.json", raw)
    pending = {
        "schema_version": 1,
        "sequence": 1,
        "activation_id": manifest["activation_id"],
        "manifest_sha256": digest,
        "previous_manifest_sha256": None,
        "status": "PENDING",
    }
    dispatcher.immutable_write(
        dispatcher.receipt_path(paths, manifest, "PENDING"), dispatcher.canonical_json(pending)
    )
    dispatcher.atomic_replace(
        paths["pointer"],
        dispatcher.canonical_json({
            "schema_version": 1,
            "sequence": 1,
            "activation_id": manifest["activation_id"],
            "manifest_sha256": digest,
        }),
    )
    monkeypatch.setenv("AR_DISPATCHER_TEST_SID", "S-1-test")
    dispatcher.probe(control)
    assert dispatcher.receipt_path(paths, manifest, "PASS").exists()


def test_sequence_and_activation_replay_are_rejected(tmp_path: Path) -> None:
    control, _target, manifest = fixture(tmp_path)
    proposed = tmp_path / "manifest.json"
    first_digest = write_manifest(proposed, manifest)
    dispatcher.activate(control, proposed)
    replay = dict(manifest)
    replay["sequence"] = 2
    replay["previous_manifest_sha256"] = first_digest
    replay_path = tmp_path / "replay.json"
    write_manifest(replay_path, replay)
    with pytest.raises(ValueError, match="activation ID is a replay"):
        dispatcher.activate(control, replay_path)
