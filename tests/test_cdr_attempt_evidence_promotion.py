"""Immutable promotion contracts for sanitized raw HTTP-attempt evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import Event, Thread

import pytest

from cdr_attempt_evidence_promotion import (
    ARTIFACT_NAMESPACE,
    PROMOTION_MANIFEST,
    AttemptEvidencePromotionError,
    install_tree_create_once,
    promote_attempt_evidence,
    verify_promoted_attempt_evidence,
)
from cdr_atomic import atomic_write_json
from cdr_export_contract import load_contract
from cdr_finalization import finalize_observation, verify_completion_marker
from cdr_raw_attempt_journal import RawAttemptJournal
from tests.support_observation import write_verified_observation


DATE = "2026-08-15"
SESSION = "ingest-20260815T000000000000Z-aabbccddeeff"
SESSION_TWO = "ingest-20260815T000001000000Z-ffeeddccbbaa"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _source(
    run_root: Path,
    *,
    session_id: str = SESSION,
) -> tuple[RawAttemptJournal, dict]:
    journal = RawAttemptJournal(
        run_root / "_raw-attempt-journals-v1", session_id
    )
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
    product_body = (
        b'{"data":{"products":[{"productId":"BOMInvestmentCashAccounts",'
        b'"productCategory":"TRANS_AND_SAVINGS_ACCOUNTS"}]}}'
    )
    journal.record(
        "holder:bank-of-melbourne:page:1",
        request_url="https://bank.example/cds-au/v1/banking/products",
        started_at="2026-08-15T00:00:01.000000Z",
        completed_at="2026-08-15T00:00:02.000000Z",
        status=200,
        outcome="success",
        body=product_body,
        context={
            "phase": "products_index",
            "provider": "Bank of Melbourne",
            "page": 1,
        },
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
        "coverage_evidence_complete": True,
        "providers_registered": 0,
        "providers_attempted": 0,
        "provider_states": [],
        "raw_attempt_journal": {
            **summary,
            "path": f"_raw-attempt-journals-v1/{session_id}",
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
    assert verify_promoted_attempt_evidence(export_root, pointer).summary() == (
        journal.summary()
    )


def test_verifier_rebuilds_manifest_inventory_instead_of_trusting_its_digest(
    tmp_path,
):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    _source(run_root)
    promote_attempt_evidence(run_root, export_root)
    status_path = export_root / "ingest-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    pointer = status["raw_attempt_journal"]
    manifest_path = export_root / pointer["promotion_manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_files"] = manifest["source_files"][1:]
    manifest["source_file_count"] = len(manifest["source_files"])
    manifest["source_bytes"] = sum(item["bytes"] for item in manifest["source_files"])
    manifest["source_tree_sha256"] = hashlib.sha256(
        json.dumps(
            {"files": manifest["source_files"]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    atomic_write_json(manifest_path, manifest)
    pointer.update(
        promotion_manifest_sha256=_hash(manifest_path),
        source_tree_sha256=manifest["source_tree_sha256"],
        source_file_count=manifest["source_file_count"],
        source_bytes=manifest["source_bytes"],
    )
    atomic_write_json(status_path, status)

    with pytest.raises(AttemptEvidencePromotionError, match="manifest conflicts"):
        verify_promoted_attempt_evidence(export_root, pointer)


def test_idempotent_replay_preserves_installed_bytes(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    _source(run_root)
    first = promote_attempt_evidence(run_root, export_root)
    installed_before = _tree_bytes(export_root)

    second = promote_attempt_evidence(run_root, export_root)

    assert second == first
    assert _tree_bytes(export_root) == installed_before


def test_replay_rejects_bool_for_integer_manifest_field(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    _source(run_root)
    promote_attempt_evidence(run_root, export_root)
    manifest_path = export_root.joinpath(
        *ARTIFACT_NAMESPACE.parts, SESSION, PROMOTION_MANIFEST
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = True
    atomic_write_json(manifest_path, manifest)
    (export_root / "ingest-status.json").unlink()

    with pytest.raises(AttemptEvidencePromotionError, match="manifest conflicts"):
        promote_attempt_evidence(run_root, export_root)

    assert json.loads(manifest_path.read_text(encoding="utf-8"))[
        "schema_version"
    ] is True
    assert not (export_root / "ingest-status.json").exists()


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


def test_missing_zero_attempt_source_is_not_created_by_verification(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    missing = run_root / "_raw-attempt-journals-v1" / SESSION
    atomic_write_json(
        run_root / "banks" / "ingest-status.json",
        {
            "raw_attempt_journal": {
                "schema_version": 1,
                "session_id": SESSION,
                "attempts": 0,
                "head_digest": None,
                "verified": True,
                "path": f"_raw-attempt-journals-v1/{SESSION}",
                "path_resolution": "relative_to_ingest_run_root",
                "retention": "follows_ingest_run_root",
            }
        },
    )

    with pytest.raises(AttemptEvidencePromotionError, match="source verification"):
        promote_attempt_evidence(run_root, export_root)

    assert not missing.exists()
    assert not export_root.exists()


def test_existing_verified_zero_attempt_journal_can_be_promoted(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    journal = RawAttemptJournal(run_root / "_raw-attempt-journals-v1", SESSION)
    summary = journal.summary()
    atomic_write_json(
        run_root / "banks" / "ingest-status.json",
        {
            "raw_attempt_journal": {
                **summary,
                "path": f"_raw-attempt-journals-v1/{SESSION}",
                "path_resolution": "relative_to_ingest_run_root",
                "retention": "follows_ingest_run_root",
            }
        },
    )

    promoted = promote_attempt_evidence(run_root, export_root)

    assert promoted is not None
    assert promoted["attempts"] == 0
    destination = export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION)
    assert RawAttemptJournal(destination.parent, SESSION).summary()["attempts"] == 0


def test_source_verification_does_not_recover_or_mutate_missing_current(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    journal, _status = _source(run_root)
    journal.current_path.unlink()
    source_before = _tree_bytes(run_root)

    with pytest.raises(AttemptEvidencePromotionError, match="source verification"):
        promote_attempt_evidence(run_root, export_root)

    assert _tree_bytes(run_root) == source_before
    assert not journal.current_path.exists()
    assert not export_root.exists()


def test_replay_does_not_recover_or_mutate_installed_journal(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    _source(run_root)
    promote_attempt_evidence(run_root, export_root)
    destination = export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION)
    current = destination / "current.json"
    current.unlink()
    (export_root / "ingest-status.json").unlink()
    installed_before = _tree_bytes(destination)

    with pytest.raises(AttemptEvidencePromotionError, match="files conflict"):
        promote_attempt_evidence(run_root, export_root)

    assert _tree_bytes(destination) == installed_before
    assert not current.exists()
    assert not (export_root / "ingest-status.json").exists()


def test_legacy_status_without_attempt_pointer_is_copied_byte_exact(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    status = run_root / "banks" / "ingest-status.json"
    status.parent.mkdir(parents=True)
    source_bytes = b'{"total":2,"incomplete":true}'
    status.write_bytes(source_bytes)

    assert promote_attempt_evidence(run_root, export_root) is None
    assert (export_root / "ingest-status.json").read_bytes() == source_bytes


def test_existing_export_status_is_preserved_and_blocks_new_promotion(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    _source(run_root)
    export_root.mkdir()
    existing = export_root / "ingest-status.json"
    existing.write_bytes(b"preserve-existing-status")

    with pytest.raises(AttemptEvidencePromotionError, match="existing export"):
        promote_attempt_evidence(run_root, export_root)

    assert existing.read_bytes() == b"preserve-existing-status"
    assert not export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION).exists()


def test_export_lock_serializes_different_sessions_through_status_creation(tmp_path):
    first_run = tmp_path / "run-one"
    second_run = tmp_path / "run-two"
    export_root = tmp_path / "export"
    _source(first_run)
    _source(second_run, session_id=SESSION_TWO)
    first_installed = Event()
    release_first = Event()
    second_verified = Event()
    outcomes = {}

    def first_fault(stage):
        if stage == "after_install":
            first_installed.set()
            assert release_first.wait(5)

    def second_fault(stage):
        if stage == "after_source_verify":
            second_verified.set()

    def promote(name, run_root, injector):
        try:
            outcomes[name] = promote_attempt_evidence(
                run_root,
                export_root,
                fault_injector=injector,
            )
        except BaseException as error:
            outcomes[name] = error

    first = Thread(target=promote, args=("first", first_run, first_fault))
    second = Thread(target=promote, args=("second", second_run, second_fault))
    first.start()
    assert first_installed.wait(5)
    second.start()
    assert second_verified.wait(5)
    assert second.is_alive()
    release_first.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert isinstance(outcomes["first"], dict)
    assert isinstance(outcomes["second"], AttemptEvidencePromotionError)
    assert "another session" in str(outcomes["second"])
    status = json.loads(
        (export_root / "ingest-status.json").read_text(encoding="utf-8")
    )
    assert status["raw_attempt_journal"]["session_id"] == SESSION
    assert export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION).is_dir()
    assert not export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION_TWO).exists()


def test_different_session_cannot_orphan_installed_evidence_after_crash(tmp_path):
    first_run = tmp_path / "run-one"
    second_run = tmp_path / "run-two"
    export_root = tmp_path / "export"
    _source(first_run)
    _source(second_run, session_id=SESSION_TWO)

    def crash_after_install(stage):
        if stage == "after_install":
            raise RuntimeError("simulated crash after install")

    with pytest.raises(RuntimeError, match="simulated crash"):
        promote_attempt_evidence(
            first_run,
            export_root,
            fault_injector=crash_after_install,
        )
    assert export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION).is_dir()
    assert not (export_root / "ingest-status.json").exists()

    with pytest.raises(AttemptEvidencePromotionError, match="another session"):
        promote_attempt_evidence(second_run, export_root)

    assert not export_root.joinpath(*ARTIFACT_NAMESPACE.parts, SESSION_TWO).exists()
    promoted = promote_attempt_evidence(first_run, export_root)
    assert promoted is not None
    assert promoted["session_id"] == SESSION


def test_promotion_rejects_linked_artifact_namespace_before_copy(tmp_path):
    run_root = tmp_path / "run"
    export_root = tmp_path / "export"
    outside = tmp_path / "outside"
    _source(run_root)
    export_root.mkdir()
    outside.mkdir()
    try:
        os.symlink(
            outside,
            export_root / ARTIFACT_NAMESPACE.parts[0],
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(AttemptEvidencePromotionError, match="links"):
        promote_attempt_evidence(run_root, export_root)

    assert list(outside.iterdir()) == []


def test_finalization_hash_binds_status_manifest_and_every_journal_file(tmp_path):
    data_root = tmp_path / "data"
    run_root = tmp_path / "ram" / "runs" / DATE
    export_root = data_root / "runs" / DATE / "_exports"
    state = data_root / "state"
    journal, status = _source(run_root)
    _export(export_root)
    observation = write_verified_observation(
        export_root,
        observation_date=DATE,
        observed_at="2026-08-15T00:00:01Z",
        raw_attempt_journal_digest=str(journal.summary()["head_digest"]),
        product_evidence_id=journal.evidence_records()[1]["body_sha256"],
        accounting_id=journal.session_id,
    )
    status.update(
        providers_registered=1,
        providers_attempted=1,
        provider_states=[
            {
                "provider_uid": observation["products"][0]["provider_uid"],
                "provider_dir": "Bank of Melbourne",
                "brand_name": "Bank of Melbourne",
                "legal_entity_name": "",
                "endpoint_url": "https://bank.example/cds-au/v1/banking/products",
                "state": "complete",
                "population_known": True,
                "products_in_scope": 1,
            }
        ],
        provider_state_counts={"complete": 1},
    )
    atomic_write_json(run_root / "banks/ingest-status.json", status)
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
