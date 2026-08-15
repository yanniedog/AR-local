"""Deterministic, dormant historical candidate construction and installation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading
from typing import Any, Callable, Iterable, Mapping

from cdr_atomic import ImmutablePathError, atomic_write_bytes
from cdr_file_lock import FileLock
from cdr_historical_contract import (
    HistoricalContractError,
    canonical_json_bytes,
    candidate_identity,
    sha256_bytes,
    validate_candidate,
    validate_history_index,
    validate_schema,
    validate_source_manifest,
)
from cdr_historical_parity import raw_semantic_collisions, td_fallback_strata
from cdr_historical_source import (
    InventoryEntry,
    VerifiedSnapshot,
    date_artifacts,
    ensure_output_separate,
)


ROOT = Path(__file__).resolve().parent
TOOL_FILES = (
    "cdr_historical_contract.py",
    "cdr_historical_source.py",
    "cdr_historical_parity.py",
    "cdr_historical_candidate.py",
    "cdr_historical_acceptance.py",
    "contracts/historical/contract-lock.json",
    "contracts/historical/corpus-lock-v1.json",
    "contracts/historical/corpus-lock-v1.schema.json",
    "contracts/historical/source-manifest-v1.schema.json",
    "contracts/historical/additions-audit-v1.schema.json",
    "contracts/historical/candidate-manifest-v1.schema.json",
    "contracts/historical/history-index-v1.schema.json",
    "contracts/historical/acceptance-report-v1.schema.json",
)
UNAVAILABLE_REASON = (
    "the preserved cleaned projection has no complete register/provider/attempt population"
)
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.Lock] = {}


@dataclass(frozen=True)
class CandidateSpec:
    date: str
    variant_ordinal: int
    revision_ordinal: int
    relation: str
    artifact_path: str
    counts_path: str | None = None
    parent_coordinate: tuple[str, int, int] | None = None


@dataclass(frozen=True)
class BuiltHistory:
    sources: Mapping[str, bytes]
    candidates: Mapping[str, bytes]
    index: bytes
    index_sha256: str


def _process_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(str(path.resolve(strict=False)))
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.Lock())


def unavailable_population() -> dict[str, Any]:
    return {"state": "unavailable", "value": None, "reason": UNAVAILABLE_REASON}


def _artifact(entry: InventoryEntry, *, role: str | None = None) -> dict[str, Any]:
    if entry.sha256 is None:
        raise HistoricalContractError(f"artifact lacks digest: {entry.path}")
    result: dict[str, Any] = {
        "path": entry.path,
        "bytes": entry.bytes,
        "sha256": entry.sha256,
    }
    if role is not None:
        result = {"role": role, **result}
    return result


def _role(path: str) -> str:
    if path.endswith(".done.json"):
        return "run_completion_marker"
    if path.endswith(".integrity.json"):
        return "legacy_integrity_record"
    if "/dashboard-cache/" in path:
        return "dashboard_projection"
    if "/app-payload/" in path or path.startswith("github/"):
        return "published_projection"
    if path.endswith(".sqlite") or ".sqlite." in path or path.endswith((".sqlite-wal", ".sqlite-shm")):
        return "sqlite_projection"
    if path.endswith(".xlsx") or ".xlsx." in path:
        return "workbook_projection"
    if "banks-" in path and ".json" in path:
        return "banks_projection"
    return "retained_evidence"


def _counts(
    snapshot: VerifiedSnapshot, spec: CandidateSpec, value: Mapping[str, Any]
) -> dict[str, int]:
    if spec.counts_path:
        value = snapshot.read_json(spec.counts_path)
    if not isinstance(value, Mapping):
        raise HistoricalContractError(f"candidate count source is not an object: {spec.date}")
    counts = value.get("banks_counts") or value.get("counts")
    if counts is None:
        counts = {key: len(value.get(key, [])) for key in ("products", "rates", "failures")}
    result = {key: counts.get(key) for key in ("products", "rates", "failures")}
    if not all(isinstance(number, int) and number >= 0 for number in result.values()):
        raise HistoricalContractError(f"candidate populations are not exact: {spec.date}")
    return result  # type: ignore[return-value]


def build_source_manifest(
    snapshot: VerifiedSnapshot,
    date: str,
    *,
    banks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entries = date_artifacts(snapshot, date)
    artifacts = [_artifact(entry, role=_role(entry.path)) for entry in entries]
    main_path = f"pi/data/runs/{date}/_exports/banks-{date}.json"
    main = banks if banks is not None else snapshot.read_json(main_path)
    if not isinstance(main, Mapping):
        raise HistoricalContractError(f"banks export is not an object: {date}")
    populations = {key: len(main.get(key, [])) for key in ("products", "rates", "failures")}
    manifest = {
        "schema_version": 1,
        "contract": "legacy-historical-source-manifest-v1",
        "snapshot_id": snapshot.snapshot_id,
        "observation_date": date,
        "observation_state": "partial",
        "artifact_set_sha256": sha256_bytes(canonical_json_bytes(artifacts)),
        "artifacts": artifacts,
        "populations": populations,
        "unavailable": {
            "register": unavailable_population(),
            "providers": unavailable_population(),
            "attempts": unavailable_population(),
        },
        "blockers": [
            "official register response and hash were not retained",
            "complete provider and attempt denominators were not retained",
            "legacy cleaned projections cannot establish complete source provenance",
            "SQLite WAL and SHM sidecars are transient evidence excluded from candidate inputs",
        ],
    }
    return validate_source_manifest(manifest)


def candidate_specs(dates: Iterable[str]) -> tuple[CandidateSpec, ...]:
    specs: list[CandidateSpec] = []
    for date in dates:
        current = f"pi/data/runs/{date}/_exports/banks-{date}.json"
        if date in {"2026-05-20", "2026-05-26"}:
            backup = current + ".bak-20260527T011635Z"
            specs.append(CandidateSpec(date, 1, 1, "root_projection", backup))
            specs.append(
                CandidateSpec(
                    date,
                    1,
                    2,
                    "legacy_external_correction",
                    current,
                    parent_coordinate=(date, 1, 1),
                )
            )
        else:
            specs.append(CandidateSpec(date, 1, 1, "root_projection", current))
        if date == "2026-05-19":
            dashboard = (
                "pi/data/runs/2026-05-19/_exports/dashboard-cache/"
                "2026-05-19/banks.json"
            )
            counts = (
                "pi/data/runs/2026-05-19/_exports/dashboard-cache/"
                "2026-05-19/manifest.json"
            )
            specs.append(CandidateSpec(date, 2, 1, "parallel_projection", dashboard, counts))
    return tuple(sorted(specs, key=lambda item: (item.date, item.variant_ordinal, item.revision_ordinal)))


def _git_output(*args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HistoricalContractError("local Git provenance is unavailable") from error
    if result.returncode != 0:
        raise HistoricalContractError(f"local Git provenance failed: git {args[0]}")
    return result.stdout


def _checkout_matches_blob(path: Path, blob: bytes) -> bool:
    checkout = path.read_bytes()
    normalized = checkout.replace(b"\r\n", b"\n")
    return b"\r" not in normalized and normalized == blob


def _tool(commit: str) -> dict[str, Any]:
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise HistoricalContractError("tool commit must be an exact lowercase Git commit")
    resolved = _git_output("rev-parse", "--verify", f"{commit}^{{commit}}").decode("ascii").strip()
    if resolved != commit:
        raise HistoricalContractError("tool commit does not resolve exactly")
    files = []
    for relative in TOOL_FILES:
        path = ROOT / relative
        blob = _git_output("show", f"{commit}:{relative}")
        if not _checkout_matches_blob(path, blob):
            raise HistoricalContractError(f"tool checkout differs from commit: {relative}")
        files.append({"path": relative, "bytes": len(blob), "sha256": sha256_bytes(blob)})
    return {
        "commit": commit,
        "python_version": "CPython-3.10-or-3.11/canonical-json-v1",
        "files": files,
    }


def _semantic_summary(value: Mapping[str, Any]) -> dict[str, int]:
    rates = value.get("rates", []) if isinstance(value, Mapping) else []
    products = value.get("products", []) if isinstance(value, Mapping) else []
    collisions = raw_semantic_collisions(products, rates)
    terms = td_fallback_strata(rates)
    return {
        "semantic_collision_groups": collisions.conflicting_groups,
        "semantic_collision_rows": collisions.conflicting_rows,
        "semantic_duplicate_same_value_groups": collisions.duplicate_same_value_groups,
        "semantic_duplicate_same_value_rows": collisions.duplicate_same_value_rows,
        "semantic_nonunique_rows": collisions.nonunique_rows,
        "td_no_evidence_terms": terms["no_evidence"],
        "taxonomy_rows": 0,
        "missing_evidence_rows": terms["no_evidence"],
    }


def _build_candidate(
    snapshot: VerifiedSnapshot,
    spec: CandidateSpec,
    source: Mapping[str, Any],
    source_manifest_sha256: str,
    tool: Mapping[str, Any],
    parents: Mapping[tuple[str, int, int], tuple[str, str]],
    value: Mapping[str, Any],
) -> dict[str, Any]:
    entry = snapshot.inventory.get(spec.artifact_path)
    if entry is None or entry.kind != "file":
        raise HistoricalContractError(f"variant artifact is absent: {spec.artifact_path}")
    parent_candidate, parent_source = (None, None)
    if spec.parent_coordinate is not None:
        try:
            parent_candidate, parent_source = parents[spec.parent_coordinate]
        except KeyError as error:
            raise HistoricalContractError("candidate parent was not built first") from error
    body: dict[str, Any] = {
        "schema_version": 1,
        "contract": "legacy-historical-candidate-v1",
        "coordinate": {
            "date": spec.date,
            "variant_ordinal": spec.variant_ordinal,
            "revision_ordinal": spec.revision_ordinal,
        },
        "lineage": {
            "relation": spec.relation,
            "parent_candidate_sha256": parent_candidate,
            "parent_source_manifest_sha256": parent_source,
        },
        "observation_state": "partial",
        "promotion_eligible": False,
        "blockers": list(source["blockers"]),
        "source": {
            "snapshot_id": snapshot.snapshot_id,
            "source_manifest_sha256": source_manifest_sha256,
            "variant_sha256": entry.sha256,
        },
        "tool": dict(tool),
        "populations": _counts(snapshot, spec, value),
        "quarantine": _semantic_summary(value),
        "unavailable": dict(source["unavailable"]),
        "artifacts": [_artifact(entry)],
    }
    identity = candidate_identity(body)
    coordinate = body["coordinate"]
    body["candidate_id"] = (
        f"hist-{spec.date}-v{coordinate['variant_ordinal']:04d}"
        f"-r{coordinate['revision_ordinal']:04d}-{identity[:12]}"
    )
    return validate_candidate(body)


def build_history(snapshot: VerifiedSnapshot, *, tool_commit: str) -> BuiltHistory:
    tool = _tool(tool_commit)
    source_bytes: dict[str, bytes] = {}
    candidates: dict[str, bytes] = {}
    parent_digests: dict[tuple[str, int, int], tuple[str, str]] = {}
    dates = tuple(sorted(snapshot.dates))
    indexed: dict[str, list[dict[str, Any]]] = {date: [] for date in dates}
    specs_by_date = {
        date: tuple(spec for spec in candidate_specs(dates) if spec.date == date)
        for date in dates
    }
    for date in dates:
        main_path = f"pi/data/runs/{date}/_exports/banks-{date}.json"
        main = snapshot.read_json(main_path)
        source = build_source_manifest(snapshot, date, banks=main)
        source_payload = canonical_json_bytes(source)
        source_digest = sha256_bytes(source_payload)
        source_bytes[source_digest] = source_payload
        for spec in specs_by_date[date]:
            value = main if spec.artifact_path == main_path else snapshot.read_json(spec.artifact_path)
            candidate = _build_candidate(
                snapshot,
                spec,
                source,
                source_digest,
                tool,
                parent_digests,
                value,
            )
            payload = canonical_json_bytes(candidate)
            digest = sha256_bytes(payload)
            parent_digests[(spec.date, spec.variant_ordinal, spec.revision_ordinal)] = (
                digest,
                source_digest,
            )
            candidates[digest] = payload
            indexed[spec.date].append(
                {"candidate_id": candidate["candidate_id"], "sha256": digest, "bytes": len(payload)}
            )
    index = {
        "schema_version": 1,
        "contract": "legacy-historical-index-v1",
        "dates": [{"date": date, "candidates": indexed[date]} for date in dates],
        "gaps": [
            {"date": "2026-05-14", "status": "known_gap", "reason": "legacy code records no run"},
            {"date": "2026-06-26", "status": "unclassified_gap", "reason": "no run, marker, or dated release is preserved"},
        ],
        "candidate_count": len(candidates),
        "updates_operational_latest_complete": False,
    }
    validate_history_index(index)
    index_bytes = canonical_json_bytes(index)
    return BuiltHistory(source_bytes, candidates, index_bytes, sha256_bytes(index_bytes))


def _expected_files(history: BuiltHistory) -> dict[str, bytes]:
    result = {
        f"source-manifests/{digest}.json": payload for digest, payload in history.sources.items()
    }
    result.update(
        {f"candidates/{digest}.json": payload for digest, payload in history.candidates.items()}
    )
    result[f"history-index/{history.index_sha256}.json"] = history.index
    return result


def _verify_tree(root: Path, expected: Mapping[str, bytes]) -> None:
    actual = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )
    if actual != sorted(expected):
        raise HistoricalContractError("candidate bundle file inventory differs")
    for relative, payload in expected.items():
        if (root / relative).read_bytes() != payload:
            raise HistoricalContractError(f"candidate bundle corruption: {relative}")


def install_history(
    snapshot: VerifiedSnapshot,
    output_root: Path,
    history: BuiltHistory,
    *,
    fail_at: str | None = None,
    failure_hook: Callable[[str], None] | None = None,
) -> Path:
    ensure_output_separate(snapshot.root, output_root)
    expected = _expected_files(history)
    bundle_digest = sha256_bytes(
        canonical_json_bytes({path: sha256_bytes(payload) for path, payload in sorted(expected.items())})
    )
    output_root.mkdir(parents=True, exist_ok=True)
    stage = output_root / ".staging" / bundle_digest
    final = output_root / "bundles" / bundle_digest
    lock = output_root / ".locks" / f"{bundle_digest}.lock"
    # Windows CRT locks reject a second lock attempt from another thread in the
    # same process with EDEADLK rather than waiting. Serialize those callers
    # first; FileLock remains the cross-process fence.
    with _process_lock(lock), FileLock(lock):
        if final.exists():
            _verify_tree(final, expected)
            return final
        stage.mkdir(parents=True, exist_ok=True)
        for index, (relative, payload) in enumerate(sorted(expected.items())):
            point = f"before_file_{index}"
            if failure_hook:
                failure_hook(point)
            if fail_at == point:
                raise RuntimeError(f"injected failure at {point}")
            try:
                atomic_write_bytes(stage / relative, payload, create_once=True)
            except ImmutablePathError as error:
                raise HistoricalContractError(str(error)) from error
        _verify_tree(stage, expected)
        if failure_hook:
            failure_hook("before_install")
        if fail_at == "before_install":
            raise RuntimeError("injected failure at before_install")
        final.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(stage, final)
        except OSError:
            if not final.exists():
                raise
            _verify_tree(final, expected)
        _verify_tree(final, expected)
    return final


def additions_audit(snapshot: VerifiedSnapshot | None = None) -> dict[str, Any]:
    original_files, original_bytes = 568, 18177646221
    addition_files, addition_bytes = 688, 147127281
    changed_dates = 57
    if snapshot is not None:
        changed = sorted(
            item["date"]
            for item in snapshot.legacy_ledger_findings
            if item.get("issue") == "CHANGED"
        )
        originals: list[tuple[str, int, str]] = []
        additions: list[InventoryEntry] = []
        for date in changed:
            integrity = snapshot.read_json(f"pi/data/state/{date}.integrity.json")
            recorded = set()
            for item in integrity["files"]:
                path = f"pi/data/runs/{date}/_exports/{item['path']}"
                recorded.add(path)
                originals.append((path, item["size"], item["sha256"]))
            prefix = f"pi/data/runs/{date}/_exports/"
            additions.extend(
                item
                for path, item in snapshot.inventory.items()
                if item.kind == "file" and path.startswith(prefix) and path not in recorded
            )
        for path, size, digest in originals:
            entry = snapshot.inventory.get(path)
            if entry is None or (entry.bytes, entry.sha256) != (size, digest):
                raise HistoricalContractError(f"legacy recorded original changed: {path}")
        changed_dates = len(changed)
        original_files = len(originals)
        original_bytes = sum(item[1] for item in originals)
        addition_files = len(additions)
        addition_bytes = sum(item.bytes for item in additions)
    value = {
        "schema_version": 1,
        "contract": "legacy-historical-additions-audit-v1",
        "changed_dates": changed_dates,
        "original_population": {"files": original_files, "bytes": original_bytes},
        "addition_population": {"files": addition_files, "bytes": addition_bytes},
        "legacy_findings_preserved": True,
    }
    return validate_schema("additions_audit", value)
