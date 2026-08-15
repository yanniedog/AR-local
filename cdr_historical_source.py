"""Read-only, fail-closed access to the verified preservation snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import quote

from cdr_historical_contract import (
    CORPUS_LOCK_PATH,
    HistoricalContractError,
    SQLITE_TRANSIENT_SUFFIXES,
    load_strict_json,
    portable_path,
    sha256_file,
    strict_json_bytes,
    unique_portable_paths,
    validate_contract_tree,
)


ROOT = Path(__file__).resolve().parent
EVIDENCE_PATH = ROOT / "docs" / "preservation" / "PRESERVATION_EVIDENCE_V1.json"
REPARSE_ATTRIBUTE = 0x400


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    kind: str
    bytes: int
    sha256: str | None


@dataclass(frozen=True)
class CriticalEntry:
    source_path: str
    snapshot_path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class RehashFinding:
    path: str
    expected_bytes: int
    actual_bytes: int
    expected_sha256: str
    actual_sha256: str
    source_role: str


@dataclass(frozen=True)
class RehashAudit:
    checked_files: int
    checked_bytes: int
    verified_files: int
    verified_bytes: int
    findings: tuple[RehashFinding, ...]


@dataclass
class VerifiedSnapshot:
    root: Path
    snapshot_id: str
    inventory: Mapping[str, InventoryEntry]
    critical: Mapping[str, CriticalEntry]
    dates: tuple[str, ...]
    legacy_ledger_findings: tuple[Mapping[str, Any], ...]

    def path(self, relative: str) -> Path:
        relative = portable_path(relative)
        target = self.root.joinpath(*relative.split("/"))
        _assert_contained_regular(self.root, target)
        return target

    def read_bytes(self, relative: str, *, verify: bool = True) -> bytes:
        target = self.path(relative)
        payload = target.read_bytes()
        entry = self.inventory.get(portable_path(relative))
        if entry is None or entry.kind != "file":
            raise HistoricalContractError(f"source is not inventoried as a file: {relative}")
        if len(payload) != entry.bytes:
            raise HistoricalContractError(f"source byte count changed: {relative}")
        if verify and entry.sha256 is not None:
            from cdr_historical_contract import sha256_bytes

            if sha256_bytes(payload) != entry.sha256:
                raise HistoricalContractError(f"source digest changed: {relative}")
        return payload

    def read_json(self, relative: str) -> Any:
        return strict_json_bytes(self.read_bytes(relative), source=relative)

    def rehash(self, relative_paths: Iterable[str]) -> tuple[int, int]:
        audit = self.audit_rehash(relative_paths)
        if audit.findings:
            raise HistoricalContractError(
                f"source mutation detected: {audit.findings[0].path}"
            )
        return audit.checked_files, audit.checked_bytes

    def audit_rehash(
        self,
        relative_paths: Iterable[str],
        *,
        candidate_inputs: Iterable[str] = (),
    ) -> RehashAudit:
        checked_files = checked_bytes = verified_files = verified_bytes = 0
        findings: list[RehashFinding] = []
        candidate_paths = {portable_path(path) for path in candidate_inputs}
        for relative in sorted(set(relative_paths)):
            entry = self.inventory.get(portable_path(relative))
            if entry is None or entry.kind != "file" or entry.sha256 is None:
                raise HistoricalContractError(f"source lacks immutable inventory hash: {relative}")
            path = self.path(relative)
            actual_bytes = path.stat().st_size
            actual_sha256 = sha256_file(path)
            checked_files += 1
            checked_bytes += actual_bytes
            if actual_bytes == entry.bytes and actual_sha256 == entry.sha256:
                verified_files += 1
                verified_bytes += entry.bytes
            else:
                findings.append(
                    RehashFinding(
                        path=relative,
                        expected_bytes=entry.bytes,
                        actual_bytes=actual_bytes,
                        expected_sha256=entry.sha256,
                        actual_sha256=actual_sha256,
                        source_role=(
                            "sqlite_transient_sidecar"
                            if is_sqlite_transient(relative)
                            else "immutable_candidate_input"
                            if relative in candidate_paths
                            else "immutable_preservation_evidence"
                        ),
                    )
                )
        return RehashAudit(
            checked_files,
            checked_bytes,
            verified_files,
            verified_bytes,
            tuple(findings),
        )

    def connect_sqlite(self, relative: str) -> sqlite3.Connection:
        path = self.path(relative)
        uri = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("PRAGMA query_only").fetchone() != (1,):
                raise HistoricalContractError("SQLite query_only could not be enabled")
            return connection
        except Exception:
            connection.close()
            raise


def _is_reparse(path: Path) -> bool:
    stat = path.lstat()
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & REPARSE_ATTRIBUTE)


def is_sqlite_transient(relative: str) -> bool:
    return portable_path(relative).casefold().endswith(SQLITE_TRANSIENT_SUFFIXES)


def _assert_plain_directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or _is_reparse(path):
        raise HistoricalContractError(f"snapshot root must be a plain directory: {path}")
    return resolved


def _assert_contained_regular(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise HistoricalContractError(f"source escapes snapshot: {target}") from error
    current = root
    for part in relative.parts:
        current = current / part
        if not current.exists():
            raise HistoricalContractError(f"source is missing: {current}")
        if _is_reparse(current):
            raise HistoricalContractError(f"source reparse/link is forbidden: {current}")
    if not target.is_file():
        raise HistoricalContractError(f"source is not a regular file: {target}")


def ensure_output_separate(snapshot_root: Path, output_root: Path) -> None:
    source = snapshot_root.resolve(strict=True)
    output = output_root.resolve(strict=False)
    if output == source or source in output.parents or output in source.parents:
        raise HistoricalContractError("source and output trees overlap")
    if output.exists() and _is_reparse(output):
        raise HistoricalContractError("output root cannot be a reparse/link")


def _verify_manifest_descriptors(root: Path, evidence: Mapping[str, Any]) -> None:
    # This pass deliberately validates every committed descriptor before a
    # source artifact or inventory row is opened.
    unique_portable_paths(item["path"] for item in evidence["manifests"])
    for descriptor in evidence["manifests"]:
        relative = portable_path(descriptor["path"])
        path = root.joinpath(*relative.split("/"))
        _assert_contained_regular(root, path)
        if path.stat().st_size != descriptor["bytes"]:
            raise HistoricalContractError(f"manifest byte count mismatch: {relative}")
        if sha256_file(path) != descriptor["sha256"]:
            raise HistoricalContractError(f"manifest digest mismatch: {relative}")


def _inventory(root: Path, relative: str) -> dict[str, InventoryEntry]:
    path = root.joinpath(*portable_path(relative).split("/"))
    records: list[InventoryEntry] = []
    for line_number, raw in enumerate(path.read_bytes().splitlines(), 1):
        value = strict_json_bytes(raw, source=f"{relative}:{line_number}")
        if not isinstance(value, dict) or set(value) != {
            "path",
            "type",
            "bytes",
            "mtime_utc",
            "sha256",
        }:
            raise HistoricalContractError(f"invalid inventory row {line_number}")
        row_path = portable_path(value["path"])
        kind = value["type"]
        digest = value["sha256"]
        if kind not in {"file", "directory"}:
            raise HistoricalContractError(f"invalid inventory type at row {line_number}")
        if not isinstance(value["bytes"], int) or value["bytes"] < 0:
            raise HistoricalContractError(f"invalid inventory bytes at row {line_number}")
        if kind == "file" and (not isinstance(digest, str) or len(digest) != 64):
            raise HistoricalContractError(f"invalid inventory digest at row {line_number}")
        if kind == "directory" and (digest is not None or value["bytes"] != 0):
            raise HistoricalContractError(f"invalid directory row {line_number}")
        records.append(InventoryEntry(row_path, kind, value["bytes"], digest))
    unique_portable_paths(row.path for row in records)
    return {row.path: row for row in records}


def _critical_relative(source_path: str) -> str:
    data_prefix = "/srv/ar-local/data/"
    state_prefix = "/srv/ar-local/AR-local/state/"
    if source_path.startswith(data_prefix):
        return portable_path("pi/data/" + source_path[len(data_prefix) :])
    if source_path.startswith(state_prefix):
        return portable_path("pi/repo-state/state/" + source_path[len(state_prefix) :])
    raise HistoricalContractError(f"unknown critical source root: {source_path}")


def _critical_entries(
    root: Path, inventory: Mapping[str, InventoryEntry]
) -> dict[str, CriticalEntry]:
    relative = "manifests/pi-critical-source-sha256.txt"
    result: dict[str, CriticalEntry] = {}
    for line_number, line in enumerate(
        root.joinpath(*relative.split("/")).read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise HistoricalContractError(f"invalid critical manifest row {line_number}")
        digest, source_path = parts
        mapped = _critical_relative(source_path)
        entry = inventory.get(mapped)
        if entry is None or entry.kind != "file":
            raise HistoricalContractError(f"critical file missing from inventory: {mapped}")
        if entry.sha256 != digest:
            raise HistoricalContractError(f"critical/inventory digest mismatch: {mapped}")
        if mapped.casefold() in {key.casefold() for key in result}:
            raise HistoricalContractError(f"duplicate critical path: {mapped}")
        result[mapped] = CriticalEntry(source_path, mapped, digest, entry.bytes)
    return result


def _dates(root: Path) -> tuple[str, ...]:
    values = tuple(
        line.strip()
        for line in (root / "manifests" / "pi-run-entries.txt")
        .read_text(encoding="utf-8-sig")
        .splitlines()
        if line.strip()
    )
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise HistoricalContractError("run dates must be unique and sorted")
    return values


def open_verified_snapshot(
    snapshot_root: Path,
    *,
    output_root: Path | None = None,
    rehash_critical: bool = False,
) -> VerifiedSnapshot:
    corpus = validate_contract_tree()
    evidence = load_strict_json(EVIDENCE_PATH)
    if not isinstance(evidence, dict):
        raise HistoricalContractError("preservation evidence is not an object")
    root = _assert_plain_directory(snapshot_root)
    if root.name != evidence["snapshot_id"] or root.name != corpus["snapshot_id"]:
        raise HistoricalContractError("snapshot path is not the explicitly locked snapshot")
    if output_root is not None:
        ensure_output_separate(root, output_root)
    _verify_manifest_descriptors(root, evidence)
    inventory = _inventory(root, evidence["retrieval"]["inventory_relative_path"])
    critical = _critical_entries(root, inventory)
    critical_bytes = sum(item.bytes for item in critical.values())
    expected = corpus["critical_population"]
    if len(critical) != expected["files"] or critical_bytes != expected["bytes"]:
        raise HistoricalContractError("critical source population differs from corpus lock")
    dates = _dates(root)
    if len(dates) != corpus["retained_dates"]:
        raise HistoricalContractError("retained date population differs from corpus lock")
    ledger = load_strict_json(root / "manifests" / "pi-source-ledger-verification.json")
    if ledger.get("checked") != corpus["legacy_ledger_records"]:
        raise HistoricalContractError("legacy ledger role count differs from corpus lock")
    snapshot = VerifiedSnapshot(
        root=root,
        snapshot_id=root.name,
        inventory=inventory,
        critical=critical,
        dates=dates,
        legacy_ledger_findings=tuple(ledger["findings"]),
    )
    if rehash_critical:
        checked, checked_bytes = snapshot.rehash(critical)
        if (checked, checked_bytes) != (expected["files"], expected["bytes"]):
            raise HistoricalContractError("full critical rehash population mismatch")
    return snapshot


def date_artifacts(snapshot: VerifiedSnapshot, date: str) -> tuple[InventoryEntry, ...]:
    prefixes = (
        f"pi/data/runs/{date}/",
        f"pi/data/state/{date}.",
        f"github/AR-local/releases/app-payload-{date}/",
    )
    entries = [
        item
        for path, item in snapshot.inventory.items()
        if item.kind == "file"
        and not is_sqlite_transient(path)
        and not any("latest" in part for part in path.casefold().split("/"))
        and any(path.startswith(prefix) for prefix in prefixes)
    ]
    if not entries:
        raise HistoricalContractError(f"date has no source artifacts: {date}")
    return tuple(sorted(entries, key=lambda item: item.path))


def iter_dates(snapshot: VerifiedSnapshot, *, reverse: bool = False) -> Iterator[str]:
    yield from (reversed(snapshot.dates) if reverse else snapshot.dates)
