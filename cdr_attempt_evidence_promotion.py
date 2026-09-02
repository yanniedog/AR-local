"""Create-once promotion of verified ingest-attempt evidence into exports."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Optional

from cdr_atomic import (
    ImmutablePathError,
    atomic_write_bytes,
    atomic_write_json,
    canonical_json_bytes,
)
from cdr_file_lock import FileLock
from cdr_raw_attempt_journal import RawAttemptJournal
from cdr_provider_identity_registry import REGISTRY_FILENAME


PROMOTION_SCHEMA_VERSION = 1
SOURCE_NAMESPACE = "_raw-attempt-journals-v1"
ARTIFACT_NAMESPACE = PurePosixPath(
    "attempt-evidence/raw-attempt-journals-v1"
)
PROMOTION_MANIFEST = "promotion-manifest.json"

FaultInjector = Optional[Callable[[str], None]]


class AttemptEvidencePromotionError(RuntimeError):
    """Raised when attempt evidence cannot be promoted without mutation or loss."""


def _fault(injector: FaultInjector, stage: str) -> None:
    if injector is not None:
        injector(stage)


def _is_reparse(stat_result: os.stat_result) -> bool:
    return bool(getattr(stat_result, "st_file_attributes", 0) & 0x400)


def _validate_node(path: Path, *, directory: bool) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError as error:
        raise AttemptEvidencePromotionError(
            f"attempt evidence path is unreadable: {path.name}"
        ) from error
    if stat.S_ISLNK(details.st_mode) or _is_reparse(details):
        raise AttemptEvidencePromotionError("attempt evidence cannot contain links")
    expected = stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode)
    if not expected:
        raise AttemptEvidencePromotionError("attempt evidence contains a special file")
    return details


def _ensure_directory(parent: Path, *parts: str) -> Path:
    """Create path components one at a time and reject links at every level."""
    current = parent
    for part in parts:
        current = current / part
        try:
            current.mkdir(exist_ok=True)
        except OSError as error:
            raise AttemptEvidencePromotionError(
                f"attempt evidence directory is not creatable: {current.name}"
            ) from error
        _validate_node(current, directory=True)
    return current


def _remove_empty_directory(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise AttemptEvidencePromotionError(
            "promotion temporary directory is unreadable"
        ) from error
    _validate_node(path, directory=True)
    try:
        path.rmdir()
    except OSError as error:
        raise AttemptEvidencePromotionError(
            "promotion temporary directory is not empty"
        ) from error


def _write_status(path: Path, payload: bytes | Mapping[str, Any]) -> None:
    try:
        if isinstance(payload, bytes):
            atomic_write_bytes(path, payload, create_once=True)
        else:
            atomic_write_json(path, payload, create_once=True)
    except ImmutablePathError as error:
        raise AttemptEvidencePromotionError(
            "refusing to replace an existing export ingest status"
        ) from error


def _promotion_lock_path(export_root: Path) -> Path:
    return (
        export_root.parent
        / f".{export_root.name}.attempt-evidence-promotion.lock"
    )


def _write_unpromoted_status(export_root: Path, status_bytes: bytes) -> None:
    export_root.mkdir(parents=True, exist_ok=True)
    _validate_node(export_root, directory=True)
    with FileLock(_promotion_lock_path(export_root)):
        _write_status(export_root / "ingest-status.json", status_bytes)


def _reject_other_promotion_state(
    export_root: Path,
    session_id: str,
    source_tree_sha256: str,
) -> None:
    namespace = export_root.joinpath(*ARTIFACT_NAMESPACE.parts)
    try:
        namespace.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise AttemptEvidencePromotionError(
            "attempt evidence namespace is unreadable"
        ) from error
    _validate_node(export_root, directory=True)
    _validate_node(export_root / ARTIFACT_NAMESPACE.parts[0], directory=True)
    _validate_node(namespace, directory=True)
    allowed = {
        session_id,
        f".{session_id}.promote-{source_tree_sha256[:16]}",
    }
    unexpected = sorted(
        child.name for child in namespace.iterdir() if child.name not in allowed
    )
    if unexpected:
        raise AttemptEvidencePromotionError(
            "refusing to orphan existing attempt evidence from another session"
        )


def _hash_file(path: Path) -> tuple[int, str]:
    before = _validate_node(path, directory=False)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise AttemptEvidencePromotionError(
            f"attempt evidence file is unreadable: {path.name}"
        ) from error
    after = _validate_node(path, directory=False)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AttemptEvidencePromotionError("attempt evidence changed while hashing")
    return after.st_size, digest.hexdigest()


def _inventory(root: Path, *, exclude: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    root = root.expanduser().absolute()
    _validate_node(root, directory=True)
    records: list[dict[str, Any]] = []
    for current_text, directories, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_text)
        _validate_node(current, directory=True)
        for name in list(directories):
            _validate_node(current / name, directory=True)
        for name in files:
            path = current / name
            relative = path.relative_to(root).as_posix()
            if relative in exclude:
                continue
            size, digest = _hash_file(path)
            records.append({"path": relative, "bytes": size, "sha256": digest})
    records.sort(key=lambda item: str(item["path"]))
    return records


def _tree_digest(records: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json_bytes({"files": records})).hexdigest()


def _safe_relative(value: Any) -> PurePosixPath:
    text = str(value or "")
    path = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or ":" in text
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise AttemptEvidencePromotionError("attempt journal path is not safe and relative")
    return path


def _verified_source(
    run_root: Path,
    pointer: Mapping[str, Any],
) -> tuple[RawAttemptJournal, dict[str, Any], PurePosixPath]:
    source_relative = _safe_relative(pointer.get("path"))
    session_id = str(pointer.get("session_id") or "")
    if (
        source_relative.parts != (SOURCE_NAMESPACE, session_id)
        or pointer.get("path_resolution") != "relative_to_ingest_run_root"
        or pointer.get("verified") is not True
    ):
        raise AttemptEvidencePromotionError("attempt journal source pointer is invalid")
    source_root = run_root.joinpath(*source_relative.parts)
    try:
        _validate_node(run_root, directory=True)
        _validate_node(run_root / SOURCE_NAMESPACE, directory=True)
        _validate_node(source_root, directory=True)
        lock_details = _validate_node(source_root / ".lock", directory=False)
        if lock_details.st_size != 1:
            raise AttemptEvidencePromotionError(
                "attempt journal source lock is not initialized"
            )
        journal = RawAttemptJournal(run_root / SOURCE_NAMESPACE, session_id)
        summary = journal.summary(recover=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise AttemptEvidencePromotionError("attempt journal source verification failed") from error
    for field in (
        "schema_version",
        "session_id",
        "attempts",
        "head_digest",
        "observed_at",
        "verified",
    ):
        if pointer.get(field) != summary.get(field):
            raise AttemptEvidencePromotionError(
                f"attempt journal source summary mismatch: {field}"
            )
    return journal, summary, source_relative


def _copy_record_create_once(
    source_root: Path,
    destination_root: Path,
    record: Mapping[str, Any],
) -> None:
    relative = _safe_relative(record.get("path"))
    source = source_root.joinpath(*relative.parts)
    try:
        payload = source.read_bytes()
    except OSError as error:
        raise AttemptEvidencePromotionError(
            f"attempt evidence file disappeared: {relative.as_posix()}"
        ) from error
    if (
        len(payload) != record.get("bytes")
        or hashlib.sha256(payload).hexdigest() != record.get("sha256")
    ):
        raise AttemptEvidencePromotionError("attempt evidence changed while copying")
    atomic_write_bytes(
        destination_root.joinpath(*relative.parts),
        payload,
        create_once=True,
    )


def _manifest(
    *,
    artifact_path: PurePosixPath,
    source_path: PurePosixPath,
    summary: Mapping[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "artifact_path": artifact_path.as_posix(),
        "source_journal_path": source_path.as_posix(),
        "source_tree_sha256": _tree_digest(records),
        "source_file_count": len(records),
        "source_bytes": sum(int(item["bytes"]) for item in records),
        "journal": dict(summary),
        "source_files": records,
    }


def _verify_promoted(
    destination: Path,
    session_id: str,
    expected_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    manifest_path = destination / PROMOTION_MANIFEST
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        raise AttemptEvidencePromotionError("promotion manifest is unreadable") from error
    if manifest_bytes != canonical_json_bytes(expected_manifest):
        raise AttemptEvidencePromotionError("promoted evidence manifest conflicts with source")
    expected_files = list(expected_manifest["source_files"])
    actual_files = _inventory(
        destination,
        exclude=frozenset({PROMOTION_MANIFEST}),
    )
    if actual_files != expected_files:
        raise AttemptEvidencePromotionError("promoted evidence files conflict with source")
    try:
        summary = RawAttemptJournal(destination.parent, session_id).summary(
            recover=False
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise AttemptEvidencePromotionError("promoted attempt journal verification failed") from error
    if summary != expected_manifest["journal"]:
        raise AttemptEvidencePromotionError("promoted attempt journal summary mismatch")
    return summary, _hash_file(manifest_path)[1]


def _install_journal(
    *,
    export_root: Path,
    source: RawAttemptJournal,
    source_relative: PurePosixPath,
    summary: Mapping[str, Any],
    records: list[dict[str, Any]],
    fault_injector: FaultInjector,
) -> tuple[PurePosixPath, dict[str, Any], str]:
    """Install one journal while the caller holds the export promotion lock."""
    artifact_path = ARTIFACT_NAMESPACE / source.session_id
    export_root.mkdir(parents=True, exist_ok=True)
    _validate_node(export_root, directory=True)
    namespace = _ensure_directory(export_root, *ARTIFACT_NAMESPACE.parts)
    destination = namespace / source.session_id
    manifest = _manifest(
        artifact_path=artifact_path,
        source_path=source_relative,
        summary=summary,
        records=records,
    )
    temporary_parent = namespace / (
        f".{source.session_id}.promote-{manifest['source_tree_sha256'][:16]}"
    )
    temporary = temporary_parent / source.session_id
    if destination.exists():
        verified, manifest_digest = _verify_promoted(
            destination, source.session_id, manifest
        )
        if temporary.exists():
            raise AttemptEvidencePromotionError(
                "promotion temporary tree remains beside installed evidence"
            )
        _remove_empty_directory(temporary_parent)
        return artifact_path, verified, manifest_digest
    _ensure_directory(namespace, temporary_parent.name, source.session_id)
    _inventory(temporary, exclude=frozenset({PROMOTION_MANIFEST}))
    for index, record in enumerate(records):
        _copy_record_create_once(source.root, temporary, record)
        if index == 0:
            _fault(fault_injector, "after_first_file")
    atomic_write_json(
        temporary / PROMOTION_MANIFEST,
        manifest,
        create_once=True,
    )
    _fault(fault_injector, "after_manifest")
    verified, manifest_digest = _verify_promoted(
        temporary, source.session_id, manifest
    )
    _fault(fault_injector, "before_install")
    if _inventory(source.root) != records:
        raise AttemptEvidencePromotionError(
            "attempt evidence source changed before install"
        )
    if destination.exists():
        raise AttemptEvidencePromotionError("attempt evidence destination already exists")
    try:
        temporary.rename(destination)
    except OSError as error:
        raise AttemptEvidencePromotionError(
            "attempt evidence create-once install failed"
        ) from error
    if os.name != "nt":
        descriptor = os.open(namespace, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    _remove_empty_directory(temporary_parent)
    _fault(fault_injector, "after_install")
    return artifact_path, verified, manifest_digest


def install_tree_create_once(
    source_root: Path,
    destination_root: Path,
    *,
    fault_injector: FaultInjector = None,
) -> bool:
    """Atomically install a complete tree without replacing destination bytes."""
    source_root = source_root.expanduser().absolute()
    destination_root = destination_root.expanduser().absolute()
    records = _inventory(source_root)
    if not records:
        raise AttemptEvidencePromotionError("refusing to install an empty export tree")
    source_digest = _tree_digest(records)
    destination_root.parent.mkdir(parents=True, exist_ok=True)
    _validate_node(destination_root.parent, directory=True)
    temporary = destination_root.parent / (
        f".{destination_root.name}.install-{source_digest[:16]}"
    )
    lock_path = destination_root.parent / f".{destination_root.name}.install.lock"
    with FileLock(lock_path):
        if destination_root.exists():
            if _inventory(destination_root) == records:
                return False
            raise AttemptEvidencePromotionError(
                "refusing to replace an existing finalized export tree"
            )
        _ensure_directory(destination_root.parent, temporary.name)
        _inventory(temporary)
        for index, record in enumerate(records):
            _copy_record_create_once(source_root, temporary, record)
            if index == 0:
                _fault(fault_injector, "after_first_export_file")
        if _inventory(temporary) != records:
            raise AttemptEvidencePromotionError("staged export tree failed verification")
        _fault(fault_injector, "before_export_install")
        if _inventory(source_root) != records:
            raise AttemptEvidencePromotionError(
                "staged export source changed before install"
            )
        if destination_root.exists():
            raise AttemptEvidencePromotionError("export destination appeared during install")
        try:
            temporary.rename(destination_root)
        except OSError as error:
            raise AttemptEvidencePromotionError(
                "create-once export tree install failed"
            ) from error
        if os.name != "nt":
            descriptor = os.open(destination_root.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        _fault(fault_injector, "after_export_install")
        return True


def promote_attempt_evidence(
    run_root: Path,
    export_root: Path,
    *,
    fault_injector: FaultInjector = None,
) -> Optional[dict[str, Any]]:
    """Persist ingest status and promote its journal into a finalized artifact root.

    The source journal is read-only. Replays accept only byte-identical,
    fully verified evidence at the deterministic destination.
    """
    run_root = run_root.expanduser().absolute()
    export_root = export_root.expanduser().absolute()
    source_status = run_root / "banks" / "ingest-status.json"
    if not source_status.is_file():
        return None
    try:
        status_bytes = source_status.read_bytes()
    except OSError as error:
        raise AttemptEvidencePromotionError("ingest status is unreadable") from error
    try:
        status = json.loads(status_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _write_unpromoted_status(export_root, status_bytes)
        return None
    if not isinstance(status, dict):
        _write_unpromoted_status(export_root, status_bytes)
        return None
    pointer = status.get("raw_attempt_journal")
    if pointer is None:
        _write_unpromoted_status(export_root, status_bytes)
        return None
    if not isinstance(pointer, Mapping):
        raise AttemptEvidencePromotionError("attempt journal status pointer is invalid")
    source, summary, source_relative = _verified_source(run_root, pointer)
    registry = status.get("provider_identity_registry")
    fallback_present = any(
        str(item.get("provider_uid") or "").startswith("provider-fallback:")
        for item in status.get("provider_states") or []
        if isinstance(item, Mapping)
    )
    if registry is None and fallback_present:
        raise AttemptEvidencePromotionError("provider identity registry pointer is absent")
    if registry is not None:
        if not isinstance(registry, Mapping):
            raise AttemptEvidencePromotionError("provider identity registry pointer is invalid")
        registry_relative = _safe_relative(registry.get("path"))
        registry_source = source.root / REGISTRY_FILENAME
        try:
            registry_bytes = registry_source.read_bytes()
        except OSError as error:
            raise AttemptEvidencePromotionError(
                "provider identity registry snapshot is unreadable"
            ) from error
        if (
            registry_relative.parts != (*source_relative.parts, REGISTRY_FILENAME)
            or registry.get("path_resolution") != "relative_to_ingest_run_root"
            or registry.get("retention") != "follows_ingest_run_root"
            or registry.get("verified") is not True
            or registry.get("bytes") != len(registry_bytes)
            or registry.get("sha256") != hashlib.sha256(registry_bytes).hexdigest()
        ):
            raise AttemptEvidencePromotionError(
                "provider identity registry snapshot does not match its pointer"
            )
    records = _inventory(source.root)
    source_tree_sha256 = _tree_digest(records)
    _fault(fault_injector, "after_source_verify")
    with FileLock(_promotion_lock_path(export_root)):
        _reject_other_promotion_state(
            export_root,
            source.session_id,
            source_tree_sha256,
        )
        destination = export_root.joinpath(
            *ARTIFACT_NAMESPACE.parts, source.session_id
        )
        export_status = export_root / "ingest-status.json"
        if export_status.exists() and not destination.exists():
            raise AttemptEvidencePromotionError(
                "refusing promotion beside an existing export ingest status"
            )
        artifact_path, verified, manifest_digest = _install_journal(
            export_root=export_root,
            source=source,
            source_relative=source_relative,
            summary=summary,
            records=records,
            fault_injector=fault_injector,
        )
        promoted_pointer = dict(pointer)
        promoted_pointer.update(
            {
                **verified,
                "path": artifact_path.as_posix(),
                "path_resolution": "relative_to_finalized_export_root",
                "retention": "hash_bound_finalized_artifact",
                "promotion_manifest_path": (
                    artifact_path / PROMOTION_MANIFEST
                ).as_posix(),
                "promotion_manifest_sha256": manifest_digest,
                "source_tree_sha256": source_tree_sha256,
                "source_file_count": len(records),
                "source_bytes": sum(int(item["bytes"]) for item in records),
            }
        )
        status["raw_attempt_journal"] = promoted_pointer
        if registry is not None:
            status["provider_identity_registry"] = {
                **dict(registry),
                "path": (artifact_path / REGISTRY_FILENAME).as_posix(),
                "path_resolution": "relative_to_finalized_export_root",
                "retention": "hash_bound_finalized_artifact",
            }
        _write_status(export_status, status)
        _fault(fault_injector, "after_status")
        return promoted_pointer
