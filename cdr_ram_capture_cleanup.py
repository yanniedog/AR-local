"""Bounded cleanup of the exact RAM stage sealed by its original finalization.

Existing unsealed stages cannot be adopted by an already-finalized retry.
Capture receipts bind products; the separate seal binds the whole stage.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping

from cdr_atomic import atomic_write_json
from cdr_finalization import verify_completion_marker
from cdr_terms.identity import byte_digest, canonical_json, digest, require_sha


@dataclass
class CleanupBudget:
    max_bytes: int = 1024 ** 3
    max_entries: int = 100000
    max_seconds: float = 30
    bytes_read: int = 0
    entries: int = 0
    started: float = 0
    exhausted: bool = False

    def __post_init__(self):
        if not 0 < self.max_bytes <= 1024 ** 3 or not 0 < self.max_entries <= 100000 or not 0 < self.max_seconds <= 30:
            raise ValueError("invalid_cleanup_bounds")
        self.started = time.monotonic()

    def check(self, *, size: int = 0, entries: int = 0, reserve_bytes: int = 0):
        if (self.exhausted or self.bytes_read + size + reserve_bytes > self.max_bytes or self.entries + entries > self.max_entries
                or time.monotonic() - self.started > self.max_seconds):
            self.exhausted = True
            raise ValueError("cleanup_budget_exhausted")
        self.bytes_read += size
        self.entries += entries


def _node(path: Path, directory: bool):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("cleanup_path_contains_link")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError("cleanup_path_contains_special_node")
    if not info.st_ino or (not directory and info.st_nlink != 1):
        raise ValueError("cleanup_path_identity_unavailable_or_shared")
    return info


def _absolute(path: Path) -> Path:
    result = path.expanduser().absolute()
    # Check before resolving; resolve alone would conceal an intermediate link.
    for parent in reversed((result, *result.parents)):
        try:
            _node(parent, True)
        except FileNotFoundError:
            continue
    return result.resolve()


def _inside(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if any(not part or part in {".", ".."} or "\\" in part or ":" in part for part in parts):
        raise ValueError("unsafe_cleanup_relative_path")
    target = root.joinpath(*parts)
    if root not in target.resolve().parents:
        raise ValueError("cleanup_target_escaped_configured_root")
    current = root
    _node(current, True)
    for part in parts[:-1]:
        current /= part
        _node(current, True)
    return target


def _identity(info, directory: bool) -> dict[str, int | str]:
    identity = {"kind": "directory" if directory else "file", "device": info.st_dev, "inode": info.st_ino}
    if not directory:
        identity.update(bytes=info.st_size, mtime_ns=info.st_mtime_ns)
    return identity


def _file(path: Path, budget: CleanupBudget) -> dict[str, Any]:
    before = _node(path, False)
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        if _identity(os.fstat(stream.fileno()), False) != _identity(before, False):
            raise ValueError("cleanup_file_replaced_while_opening")
        remaining = before.st_size
        while remaining:
            amount = min(1024 * 1024, remaining)
            budget.check(reserve_bytes=amount)
            chunk = stream.read(amount)
            budget.check(size=len(chunk))
            if not chunk:
                raise ValueError("cleanup_file_changed_while_reading")
            hashed.update(chunk)
            remaining -= len(chunk)
    after = _node(path, False)
    if _identity(before, False) != _identity(after, False):
        raise ValueError("cleanup_file_changed_while_hashing")
    return {**_identity(after, False), "sha256": hashed.hexdigest()}


def _scan(root: Path, budget: CleanupBudget, *, hash_files: bool) -> dict[str, dict]:
    records = {"": _identity(_node(root, True), True)}
    budget.check(entries=1)
    pending = [root]
    while pending:
        budget.check()
        current = pending.pop()
        _node(current, True)
        with os.scandir(current) as entries:
            for entry in entries:
                budget.check(entries=1)
                path = Path(entry.path)
                directory = entry.is_dir(follow_symlinks=False)
                records[path.relative_to(root).as_posix()] = (
                    _file(path, budget) if hash_files and not directory else _identity(_node(path, directory), directory))
                if directory:
                    pending.append(path)
    return records


def _inventory(root: Path, budget: CleanupBudget) -> dict[str, dict]:
    records = _scan(root, budget, hash_files=True)
    # Re-discover membership and identities, including empty directories.
    metadata = {path: {key: value for key, value in item.items() if key != "sha256"} for path, item in records.items()}
    if _scan(root, budget, hash_files=False) != metadata:
        raise ValueError("cleanup_tree_changed_while_sealing")
    return records


def _read_receipt(path: Path, budget: CleanupBudget) -> bytes:
    before = _node(path, False)
    if before.st_size > 32 * 1024 * 1024:
        raise ValueError("cleanup_receipt_exceeds_byte_budget")
    budget.check(size=before.st_size)
    with path.open("rb") as stream:
        body = stream.read(before.st_size)
    if len(body) != before.st_size or _identity(_node(path, False), False) != _identity(before, False):
        raise ValueError("cleanup_receipt_changed_while_reading")
    budget.check()
    return body


def _layout(finalized, ram_root: Path, state_dir: Path, runs_root: Path, run_date: str, budget: CleanupBudget):
    day = finalized.get("run_date")
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or day != run_date:
        raise ValueError("cleanup_requires_canonical_date")
    if finalized.get("ram_staged") is not True or not verify_completion_marker(finalized, state_dir, day, budget=budget.check):
        budget.check()
        raise ValueError("cleanup_requires_verified_ram_finalization")
    root = _absolute(ram_root)
    if _absolute(Path(finalized["ram_root"])) != root:
        raise ValueError("marker_ram_root_differs_from_configuration")
    for protected in (state_dir, runs_root, Path(os.environ["AR_LOCAL_TERMS_ROOT"])):
        other = protected.expanduser().resolve()
        if root == other or root in other.parents or other in root.parents:
            raise ValueError("cleanup_root_overlaps_protected_data")
    return root, day


def _seal_path(state_dir: Path, generation: str) -> Path:
    parent = _absolute(state_dir) / "ram-capture-cleanup"
    if parent.exists() or parent.is_symlink():
        _node(parent, True)
    return parent / (digest(generation) + ".json")


def _once(path: Path, payload: dict, budget: CleanupBudget):
    budget.check()
    if path.exists():
        if canonical_json(json.loads(_read_receipt(path, budget))) != canonical_json(payload):
            raise ValueError("cleanup_receipt_identity_conflict")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _absolute(path.parent)
    atomic_write_json(path, payload, create_once=True)


def _outcome(status: str, budget: CleanupBudget, **extra):
    return {"status": status, "bytes_charged": budget.bytes_read, "entries_checked": budget.entries,
            "elapsed_seconds": round(time.monotonic() - budget.started, 6), **extra}


def seal_ram_capture_stage(finalized: Mapping[str, Any], *, ram_root: Path, state_dir: Path,
                           runs_root: Path, run_date: str, clean: bool, budget: CleanupBudget | None = None) -> dict:
    """Original-run only. A failed seal never changes finalization or source files."""
    budget = budget or CleanupBudget()
    if not clean or not os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip():
        return _outcome("DISABLED", budget)
    try:
        root, day = _layout(finalized, ram_root, state_dir, runs_root, run_date, budget)
        targets = {}
        for relative in (f"runs/{day}", f"exports/{day}"):
            # RAM exports are optional; the persistent export stage is separate.
            if not (root / relative).exists():
                if relative.startswith("runs/"):
                    raise ValueError("original_ram_source_stage_missing")
                continue
            targets[relative] = _inventory(_inside(root, relative), budget)
        seal = {"schema_version": 1, "generation_id": finalized["generation_id"],
                "export_contract_digest": finalized["export_contract_digest"], "run_date": day,
                "ram_root": str(root), "targets": targets}
        path = _seal_path(state_dir, finalized["generation_id"])
        budget.check()
        _once(path, seal, budget)
        return _outcome("SEALED", budget, seal_sha256=byte_digest(_read_receipt(path, budget)))
    except (KeyError, OSError, ValueError, TypeError) as error:
        return _outcome("PRESERVED", budget, reason=str(error))


def _capture(finalized, capture, budget: CleanupBudget) -> dict:
    if not capture or capture.get("status") != "CAPTURED_AND_QUEUED":
        raise ValueError("cleanup_requires_successful_capture")
    root = _absolute(Path(os.environ["AR_LOCAL_TERMS_ROOT"]))
    path = _inside(root, "captures/" + digest(finalized["generation_id"]) + ".json")
    body = _read_receipt(path, budget)
    if byte_digest(body) != capture.get("receipt_sha256"):
        raise ValueError("capture_receipt_hash_mismatch")
    receipt = json.loads(body)
    if not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1:
        raise ValueError("capture_receipt_schema_invalid")
    for field, expected in (("generation_id", finalized["generation_id"]),
                            ("export_contract_digest", finalized["export_contract_digest"]),
                            ("source_run_date", finalized["run_date"]), ("status", "CAPTURED_AND_QUEUED")):
        if receipt.get(field) != expected or capture.get(field) != expected:
            raise ValueError("capture_receipt_generation_mismatch")
    database = _inside(root, "evidence.sqlite3")
    database_size = _node(database, False).st_size
    # Immutable read mode cannot create or modify WAL/SHM sidecars. A live WAL
    # may hold newer completion state, so defer instead of ignoring it.
    wal = database.with_name(database.name + "-wal")
    if wal.exists() or wal.is_symlink():
        if _node(wal, False).st_size:
            raise ValueError("capture_archive_has_uncheckpointed_wal")
    # Charge the entire database conservatively for the bounded indexed lookup;
    # this is a work allowance, not a claim of measured SQLite physical reads.
    budget.check(size=database_size, entries=1)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)) as connection:
        connection.set_progress_handler(lambda: (budget.check() or 0), 100)
        if connection.execute("PRAGMA application_id").fetchone()[0] != 0x4152544D or connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("capture_archive_is_not_a_completed_terms_store")
        row = connection.execute("SELECT receipt_sha256 FROM ingest_captures WHERE ingest_id=?", (finalized["generation_id"],)).fetchone()
    if not row or row[0] != capture["receipt_sha256"]:
        raise ValueError("capture_receipt_has_no_completed_archive_record")
    budget.check()
    return receipt


def _match(actual: dict, expected: dict, *, partial: bool):
    if (not partial and canonical_json(actual) != canonical_json(expected)) or any(
            canonical_json(expected.get(path)) != canonical_json(item) for path, item in actual.items()):
        raise ValueError("sealed_ram_stage_changed_or_replaced")


def _remove_sealed(root: Path, quarantine: Path, actual: dict, expected: dict, budget: CleanupBudget, fault):
    for relative, item in sorted(actual.items()):
        if item["kind"] != "file":
            continue
        budget.check()
        if fault:
            fault("before_file", quarantine / relative)
        path = _inside(quarantine, relative)
        if _file(path, budget) != expected[relative]:
            raise ValueError("sealed_file_changed_before_removal")
        if root not in path.resolve().parents:
            raise ValueError("cleanup_file_escaped_configured_root")
        path.unlink()
    # Keep the root identity until a flushed, create-once emptied transition
    # exists. A crash after root rmdir must not strand the next sealed target.
    directories = [relative for relative, item in actual.items() if relative and item["kind"] == "directory"]
    for relative in sorted(directories, key=lambda item: (item.count("/"), len(item)), reverse=True):
        budget.check()
        path = _inside(quarantine, relative) if relative else quarantine
        if _identity(_node(path, True), True) != expected[relative]:
            raise ValueError("sealed_directory_changed_before_removal")
        if root not in path.resolve().parents:
            raise ValueError("cleanup_directory_escaped_configured_root")
        path.rmdir()  # Unknown/new files are retained; never recursively removed.


def _finish_empty_target(root, quarantine_relative, expected, attempt_path, plan, budget, fault):
    quarantine = root / quarantine_relative
    emptied = attempt_path.with_suffix(".emptied.json")
    transition = {**plan, "status": "EMPTIED", "quarantine_root_identity": expected[""]}
    if not attempt_path.exists():
        raise ValueError("emptied_quarantine_has_no_prior_cleanup_plan")
    _once(attempt_path, plan, budget)
    if emptied.exists():
        _once(emptied, transition, budget)
    else:
        _inside(root, quarantine_relative)
        _match(_inventory(quarantine, budget), {"": expected[""]}, partial=False)
        if fault:
            fault("before_emptied", quarantine)
        # atomic_write_json flushes the file before linking the immutable
        # transition. Windows has no directory-fsync guarantee here; this is a
        # process-restart protocol, not a claim of hard power-loss durability.
        _once(emptied, transition, budget)
        if fault:
            fault("after_emptied", quarantine)
    if quarantine.exists() or quarantine.is_symlink():
        _inside(root, quarantine_relative)
        _match(_inventory(quarantine, budget), {"": expected[""]}, partial=False)
        budget.check()
        quarantine.rmdir()  # Refuse replacement roots and nonempty directories.
        if fault:
            fault("after_root_removal", quarantine)
    _once(attempt_path.with_suffix(".done.json"), plan, budget)


def _rename_without_replacement(source: Path, target: Path):
    if os.name == "nt":
        source.rename(target)  # Windows refuses an existing destination.
        return
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    if rename is None:
        raise ValueError("atomic_no_replace_quarantine_is_unavailable")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):  # AT_FDCWD, RENAME_NOREPLACE
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _cleanup_target(root, relative, expected, seal_sha, state_dir, budget, fault, work_paths):
    attempt_path = _seal_path(state_dir, seal_sha + relative).with_suffix(".attempt.json")
    quarantine_relative = ".terms-capture-cleanup/" + digest([seal_sha, relative])
    quarantine = root / quarantine_relative
    plan = {"schema_version": 1, "seal_sha256": seal_sha, "relative_path": relative,
            "quarantine_relative_path": quarantine_relative}
    done = attempt_path.with_suffix(".done.json")
    if done.exists():
        _once(done, plan, budget)
        return
    if attempt_path.with_suffix(".emptied.json").exists():
        _finish_empty_target(root, quarantine_relative, expected, attempt_path, plan, budget, fault)
        return
    if quarantine.exists() or quarantine.is_symlink():
        work_paths.append(str(quarantine))
        if not attempt_path.exists():
            raise ValueError("quarantine_has_no_prior_cleanup_plan")
        _once(attempt_path, plan, budget)
        _inside(root, quarantine_relative)
        actual = _inventory(quarantine, budget)
        _match(actual, expected, partial=True)
    else:
        original = _inside(root, relative)
        _match(_inventory(original, budget), expected, partial=False)
        _once(attempt_path, plan, budget)
        quarantine.parent.mkdir(exist_ok=True)
        _inside(root, quarantine_relative)
        budget.check()
        if fault:
            fault("before_rename", original)
        # Recheck the root identity immediately before the same-filesystem move.
        if _identity(_node(original, True), True) != expected[""]:
            raise ValueError("sealed_stage_replaced_before_quarantine")
        _inside(root, relative)
        _inside(root, quarantine_relative)
        _rename_without_replacement(original, quarantine)
        work_paths.append(str(quarantine))
        if fault:
            fault("after_rename", quarantine)
        actual = _inventory(quarantine, budget)
        _match(actual, expected, partial=False)
    _remove_sealed(root, quarantine, actual, expected, budget, fault)
    _finish_empty_target(root, quarantine_relative, expected, attempt_path, plan, budget, fault)


def cleanup_captured_ram_stage(finalized: Mapping[str, Any], capture: Mapping[str, Any] | None, *,
                               ram_root: Path, state_dir: Path, runs_root: Path, run_date: str, clean: bool,
                               budget: CleanupBudget | None = None,
                               fault: Callable[[str, Path], None] | None = None) -> dict:
    """Only a prior original-run seal can authorize retry cleanup."""
    budget = budget or CleanupBudget()
    work_paths = []
    if not clean or not os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip():
        return _outcome("DISABLED", budget)
    try:
        root, day = _layout(finalized, ram_root, state_dir, runs_root, run_date, budget)
        path = _seal_path(state_dir, finalized["generation_id"])
        body = _read_receipt(path, budget)
        seal, seal_sha = json.loads(body), byte_digest(body)
        for key, expected in (("schema_version", 1), ("generation_id", finalized["generation_id"]),
                              ("export_contract_digest", finalized["export_contract_digest"]),
                              ("run_date", day), ("ram_root", str(root))):
            if canonical_json(seal.get(key)) != canonical_json(expected):
                raise ValueError("cleanup_seal_generation_mismatch")
        targets = seal["targets"]
        if f"runs/{day}" not in targets or set(targets) - {f"runs/{day}", f"exports/{day}"}:
            raise ValueError("cleanup_seal_targets_invalid")
        receipt = _capture(finalized, capture, budget)
        if (not isinstance(receipt.get("sources"), list) or type(receipt.get("products")) is not int
                or receipt["products"] <= 0 or type(receipt.get("source_bytes")) is not int):
            raise ValueError("capture_source_inventory_invalid")
        for item in receipt["sources"]:
            if not isinstance(item, dict) or not isinstance(item.get("relative_path"), str):
                raise ValueError("capture_source_inventory_invalid")
            require_sha(item.get("sha256"))
        sources = {item["relative_path"]: item["sha256"] for item in receipt["sources"]}
        sealed_sources = {name: item["sha256"] for name, item in targets[f"runs/{day}"].items()
                          if name.startswith("banks/") and name.endswith("/product-detail.json") and item["kind"] == "file"}
        source_bytes = sum(targets[f"runs/{day}"][name]["bytes"] for name in sealed_sources)
        if (sources != sealed_sources or len(sources) != len(receipt["sources"])
                or len(sources) != receipt["products"] or source_bytes != receipt["source_bytes"]):
            raise ValueError("capture_membership_differs_from_sealed_stage")
        for relative, expected in targets.items():
            _cleanup_target(root, relative, expected, seal_sha, state_dir, budget, fault, work_paths)
        budget.check()
        return _outcome("CLEANED", budget, seal_sha256=seal_sha)
    except (KeyError, OSError, ValueError, TypeError, sqlite3.Error) as error:
        return _outcome("PRESERVED", budget, reason=str(error), cleanup_work_paths=work_paths)
