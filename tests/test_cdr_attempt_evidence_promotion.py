"""Immutable promotion contracts for sanitized raw HTTP-attempt evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cdr_attempt_evidence_promotion import (
    ARTIFACT_NAMESPACE,
    PROMOTION_MANIFEST,
    AttemptEvidencePromotionError,
    install_tree_create_once,
    promote_attempt_evidence,
)
from cdr_atomic import atomic_write_json
from cdr_export_contract import load_contract
from cdr_finalization import finalize_observation, verify_completion_marker
from cdr_raw_attempt_journal import RawAttemptJournal


DATE = "2026-08-15"
SESSION = "ingest-20260815T000000000000Z-aabbccddeeff"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _source(run_root: Path) -> tuple[RawAttemptJournal, dict]:
    journal = RawAttemptJournal(run_root / "_raw-attempt-journals-v1", SESSION)
    body = b'{"data":{"products":[]}}'
    journal.record(
        "register:1|nonce|1",
        request_url="https://register.example/holders?token=do-not-retain",
        request_headers={"Accept": "application/json", "x-v": "4"},
        started_at="2026-08-15T00:00:00.000000Z",
        completed_at="2026-08-15T00:00:01.000000Z",
        status=200,
        outcome="success",
        response_headers={"Content-Type": "application/json"},
        body=body,
        wire_bytes=len(body),
        inflated_bytes=len(body),
        wire_sha256=hashlib.sha256(body).hexdigest(),
        peer_ip="8.8.8.8",
        context={"phase": "register_discovery", "request_id": "register:1"},
    )
    summary = journal.summary()
    status = {
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
    }
    atomic_write_json(run_root / "banks" / "ingest-status.json", status)
    return journal, status


def _export(export_root: Path) -> None:
    cache = export_root / "dashboard-cache"
    cache.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        cache / "latest.json",
        {
            "run_date": DATE,
            "banks_counts": {
                "products": 1,
                "rates": 1,
                "fees": 0,
                "features": 0,
                "eligibility": 0,
                "constraints": 0,
            },
        },
    )


def test_promotes_exact_source_tree_and_rewrites_status_without_mutating_source(tmp_path):
    run_root = tmp_path / "ram" / "runs" / DATE
    export_root = tmp_path / "ram" / "exports" / DATE / "_exports"
    journal, source_status = _source(run_root)
    source_before = _tree_bytes(run_root)

    promoted = promote_attempt_evidence(run_root, export_root)

    assert promoted is not None
    artifact_path = Path(*ARTIFACT_NAMESPACE.parts) / SESSION
    destination = export_root / artifact_path
    destination_summary = RawAttemptJournal(destination.parent, SESSION).summary()
    assert destination_summary == journal.summary()
    assert _tree_bytes(run_root) == source_before
    copied_status = json.loads(
        (export_root / "ingest-status.json").read_text(encoding="utf-8")
    )
    pointer = copied_status["raw_attempt_journal"]
    assert pointer["path"] == artifact_path.as_posix()
    assert pointer["path_resolution"] == "relative_to_finalized_export_root"
    assert pointer["retention"] == "hash_bound_finalized_artifact"
    assert (export_root / pointer["path"]).is_dir()
    manifest_path = export_root / pointer["promotion_manifest_path"]
    assert _hash(manifest_path) == pointer["promotion_manifest_sha256"]
    assert "do-not-retain" not in json.dumps(copied_status)
    assert source_status["raw_attempt_journal"]["path_resolution"] == (
        "relative_to_ingest_run_root"
    )


def test_idempotent_replay_preserves_installed_bytes(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    _source(run_root)
    first = promote_attempt_evidence(run_root, export_root)
    installed_before = _tree_bytes(export_root)

    second = promote_attempt_evidence(run_root, export_root)

    assert second == first
    assert _tree_bytes(export_root) == installed_before


@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_source_verify",
        "after_first_file",
        "after_manifest",
        "before_install",
        "after_install",
        "after_status",
    ],
)
def test_every_promotion_failure_boundary_recovers_idempotently(
    tmp_path,
    failure_stage,
):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    _source(run_root)
    source_before = _tree_bytes(run_root)
    failed = False

    def inject(stage):
        nonlocal failed
        if stage == failure_stage and not failed:
            failed = True
            raise RuntimeError(f"simulated crash at {stage}")

    with pytest.raises(RuntimeError, match="simulated crash"):
        promote_attempt_evidence(
            run_root,
            export_root,
            fault_injector=inject,
        )

    promoted = promote_attempt_evidence(run_root, export_root)
    assert promoted is not None
    assert _tree_bytes(run_root) == source_before
    destination = export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION)
    assert RawAttemptJournal(destination.parent, SESSION).summary()["verified"] is True
    assert not [
        path
        for path in destination.parent.iterdir()
        if path.name.startswith(f".{SESSION}.promote-")
    ]


def test_conflicting_destination_is_rejected_without_overwrite(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    _source(run_root)
    destination = export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION)
    destination.mkdir(parents=True)
    conflict = destination / PROMOTION_MANIFEST
    conflict.write_bytes(b"preserved-conflict")

    with pytest.raises(AttemptEvidencePromotionError, match="manifest"):
        promote_attempt_evidence(run_root, export_root)

    assert conflict.read_bytes() == b"preserved-conflict"
    assert not (export_root / "ingest-status.json").exists()


def test_source_tamper_blocks_promotion_and_preserves_bytes(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    journal, _status = _source(run_root)
    event_path = next(journal.events.glob("*.json"))
    event_path.write_bytes(b"tampered")
    tampered = event_path.read_bytes()

    with pytest.raises(AttemptEvidencePromotionError, match="source verification"):
        promote_attempt_evidence(run_root, export_root)

    assert event_path.read_bytes() == tampered
    assert not export_root.exists()


def test_legacy_status_without_attempt_pointer_is_copied_byte_exact(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    status = run_root / "banks" / "ingest-status.json"
    status.parent.mkdir(parents=True)
    source_bytes = b'{"total":2,"incomplete":true}'
    status.write_bytes(source_bytes)

    assert promote_attempt_evidence(run_root, export_root) is None
    assert (export_root / "ingest-status.json").read_bytes() == source_bytes


def test_finalization_hash_binds_status_manifest_and_every_journal_file(tmp_path):
    data_root = tmp_path / "data"
    run_root = tmp_path / "ram" / "runs" / DATE
    export_root = data_root / "runs" / DATE / "_exports"
    state = data_root / "state"
    _source(run_root)
    _export(export_root)
    promoted = promote_attempt_evidence(run_root, export_root)
    assert promoted is not None

    marker = state / f"{DATE}.done.json"
    completion = finalize_observation(
        export_root,
        state,
        marker,
        observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 1}},
    )
    contract = load_contract(state / completion["export_contract_path"])
    artifacts = {item["path"]: item for item in contract["artifacts"]}
    bound_root = export_root / promoted["path"]
    expected_paths = {
        path.relative_to(export_root).as_posix()
        for path in export_root.rglob("*")
        if path.is_file()
    }
    assert set(artifacts) == expected_paths
    for relative in expected_paths:
        path = export_root / relative
        assert artifacts[relative] == {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": _hash(path),
        }
    assert bound_root.is_dir()
    assert verify_completion_marker(completion, state, DATE) is True


@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_first_export_file",
        "before_export_install",
        "after_export_install",
    ],
)
def test_create_once_export_install_recovers_at_every_failure_boundary(
    tmp_path,
    failure_stage,
):
    source = tmp_path / "staged" / "_exports"
    destination = tmp_path / "runs" / DATE / "_exports"
    (source / "nested").mkdir(parents=True)
    (source / "a.json").write_bytes(b'{"a":1}')
    (source / "nested" / "b.bin").write_bytes(b"evidence")
    source_before = _tree_bytes(source)
    failed = False

    def inject(stage):
        nonlocal failed
        if stage == failure_stage and not failed:
            failed = True
            raise RuntimeError(f"simulated crash at {stage}")

    with pytest.raises(RuntimeError, match="simulated crash"):
        install_tree_create_once(source, destination, fault_injector=inject)

    installed = install_tree_create_once(source, destination)
    assert installed is (failure_stage != "after_export_install")
    assert _tree_bytes(source) == source_before
    assert _tree_bytes(destination) == source_before
    assert install_tree_create_once(source, destination) is False


def test_create_once_export_install_refuses_conflicting_destination(tmp_path):
    source = tmp_path / "staged"
    destination = tmp_path / "final"
    source.mkdir()
    destination.mkdir()
    (source / "artifact.json").write_bytes(b"new")
    conflict = destination / "artifact.json"
    conflict.write_bytes(b"preserve-existing")

    with pytest.raises(AttemptEvidencePromotionError, match="refusing to replace"):
        install_tree_create_once(source, destination)

    assert conflict.read_bytes() == b"preserve-existing"
    assert (source / "artifact.json").read_bytes() == b"new"


def test_create_once_export_install_reverifies_source_before_rename(tmp_path):
    source = tmp_path / "staged"
    destination = tmp_path / "final"
    source.mkdir()
    artifact = source / "artifact.json"
    artifact.write_bytes(b"original")

    def mutate(stage):
        if stage == "before_export_install":
            artifact.write_bytes(b"changed")

    with pytest.raises(AttemptEvidencePromotionError, match="source changed"):
        install_tree_create_once(source, destination, fault_injector=mutate)

    assert artifact.read_bytes() == b"changed"
    assert not destination.exists()


def test_promotion_reverifies_source_before_rename(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    journal, _status = _source(run_root)
    event = next(journal.events.glob("*.json"))

    def mutate(stage):
        if stage == "before_install":
            event.write_bytes(b"changed-after-copy")

    with pytest.raises(AttemptEvidencePromotionError, match="source changed"):
        promote_attempt_evidence(run_root, export_root, fault_injector=mutate)

    assert event.read_bytes() == b"changed-after-copy"
    assert not export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION).exists()


def test_create_once_export_install_rejects_empty_source(tmp_path):
    source = tmp_path / "staged"
    source.mkdir()

    with pytest.raises(AttemptEvidencePromotionError, match="empty export"):
        install_tree_create_once(source, tmp_path / "final")
