"""Deterministic lineage and create-once candidate bundle tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any

import pytest

from cdr_historical_candidate import (
    additions_audit,
    build_history,
    candidate_specs,
    install_history,
)
from cdr_historical_contract import HistoricalContractError, sha256_bytes
from cdr_historical_source import InventoryEntry


SNAPSHOT_ID = "20260814T202526AEST-pi5-3dc9b4677"
TOOL_COMMIT = "a" * 40


def retained_dates() -> tuple[str, ...]:
    values: list[str] = []
    cursor = date(2026, 5, 13)
    gaps = {date(2026, 5, 14), date(2026, 6, 26)}
    while len(values) < 92:
        if cursor not in gaps:
            values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


class FakeSnapshot:
    def __init__(self, root: Path, *, reverse: bool = False) -> None:
        self.root = root
        self.root.mkdir()
        self.snapshot_id = SNAPSHOT_ID
        dates = retained_dates()
        self.dates = tuple(reversed(dates)) if reverse else dates
        self.inventory: dict[str, InventoryEntry] = {}
        self.values: dict[str, Any] = {}
        self.critical = {}
        self.legacy_ledger_findings = ()
        for value in dates:
            main = f"pi/data/runs/{value}/_exports/banks-{value}.json"
            self._add(main, {"products": [{"id": value}], "rates": [], "failures": []})
            self._add(
                f"pi/data/runs/{value}/_exports/local-cdr.sqlite-shm",
                {"transient": True},
            )
            if value in {"2026-05-20", "2026-05-26"}:
                self._add(main + ".bak-20260527T011635Z", {"products": [{"id": value + "-original"}], "rates": [], "failures": []})
            if value == "2026-05-19":
                dashboard = f"pi/data/runs/{value}/_exports/dashboard-cache/{value}/banks.json"
                manifest = f"pi/data/runs/{value}/_exports/dashboard-cache/{value}/manifest.json"
                self._add(dashboard, {"products": [{"id": "peer-a"}, {"id": "peer-b"}], "rates": [], "failures": []})
                self._add(manifest, {"banks_counts": {"products": 2, "rates": 0, "failures": 0}})

    def _add(self, path: str, value: Any) -> None:
        payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.values[path] = value
        self.inventory[path] = InventoryEntry(path, "file", len(payload), sha256_bytes(payload))

    def read_json(self, path: str) -> Any:
        return self.values[path]


def _candidate_values(history: Any) -> list[dict[str, Any]]:
    return [json.loads(payload) for payload in history.candidates.values()]


def test_candidate_coordinates_are_exact_and_no_semantic_variant_is_truncated(tmp_path: Path) -> None:
    snapshot = FakeSnapshot(tmp_path / "snapshot")
    specs = candidate_specs(snapshot.dates)
    assert len(specs) == 95
    assert [(item.variant_ordinal, item.revision_ordinal, item.relation) for item in specs if item.date == "2026-05-19"] == [
        (1, 1, "root_projection"),
        (2, 1, "parallel_projection"),
    ]
    for value in ("2026-05-20", "2026-05-26"):
        assert [(item.variant_ordinal, item.revision_ordinal, item.relation) for item in specs if item.date == value] == [
            (1, 1, "root_projection"),
            (1, 2, "legacy_external_correction"),
        ]


def test_history_is_deterministic_under_reversed_discovery(tmp_path: Path) -> None:
    forward = build_history(FakeSnapshot(tmp_path / "forward"), tool_commit=TOOL_COMMIT)
    reverse = build_history(FakeSnapshot(tmp_path / "reverse", reverse=True), tool_commit=TOOL_COMMIT)
    assert forward.index == reverse.index
    assert forward.candidates == reverse.candidates
    assert forward.sources == reverse.sources
    assert json.loads(forward.index)["candidate_count"] == 95


def test_same_date_corrections_bind_parent_candidate_and_source_hashes(tmp_path: Path) -> None:
    history = build_history(FakeSnapshot(tmp_path / "snapshot"), tool_commit=TOOL_COMMIT)
    candidates = _candidate_values(history)
    for value in ("2026-05-20", "2026-05-26"):
        root = next(item for item in candidates if item["coordinate"] == {"date": value, "variant_ordinal": 1, "revision_ordinal": 1})
        child = next(item for item in candidates if item["coordinate"] == {"date": value, "variant_ordinal": 1, "revision_ordinal": 2})
        root_bytes = next(payload for payload in history.candidates.values() if json.loads(payload)["candidate_id"] == root["candidate_id"])
        assert child["lineage"]["parent_candidate_sha256"] == sha256_bytes(root_bytes)
        assert child["lineage"]["parent_source_manifest_sha256"] == root["source"]["source_manifest_sha256"]
        source_digest = root["source"]["source_manifest_sha256"]
        assert sha256_bytes(history.sources[source_digest]) == source_digest


@pytest.mark.parametrize("fail_at", ["before_file_0", "before_file_20", "before_install"])
def test_injected_failure_leaves_no_completed_bundle_and_retry_is_exact(
    tmp_path: Path, fail_at: str
) -> None:
    snapshot = FakeSnapshot(tmp_path / "snapshot")
    history = build_history(snapshot, tool_commit=TOOL_COMMIT)
    output = tmp_path / "output"
    with pytest.raises(RuntimeError, match="injected failure"):
        install_history(snapshot, output, history, fail_at=fail_at)
    assert not (output / "bundles").exists() or not list((output / "bundles").iterdir())
    final = install_history(snapshot, output, history)
    assert final.is_dir()
    assert install_history(snapshot, output, history) == final


def test_corrupt_staged_or_completed_bytes_fail_closed(tmp_path: Path) -> None:
    snapshot = FakeSnapshot(tmp_path / "snapshot")
    history = build_history(snapshot, tool_commit=TOOL_COMMIT)
    output = tmp_path / "output"
    with pytest.raises(RuntimeError):
        install_history(snapshot, output, history, fail_at="before_install")
    staged = next((output / ".staging").iterdir())
    first = next(path for path in staged.rglob("*.json"))
    first.write_bytes(b"corrupt")
    with pytest.raises(HistoricalContractError, match="immutable path"):
        install_history(snapshot, output, history)


def test_concurrent_idempotent_builds_install_one_exact_bundle(tmp_path: Path) -> None:
    snapshot = FakeSnapshot(tmp_path / "snapshot")
    history = build_history(snapshot, tool_commit=TOOL_COMMIT)
    output = tmp_path / "output"
    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(lambda _: install_history(snapshot, output, history), range(2)))
    assert paths[0] == paths[1]
    assert len(list((output / "bundles").iterdir())) == 1


def test_candidate_artifact_names_are_content_addressed(tmp_path: Path) -> None:
    snapshot = FakeSnapshot(tmp_path / "snapshot")
    history = build_history(snapshot, tool_commit=TOOL_COMMIT)
    final = install_history(snapshot, tmp_path / "output", history)
    for path in final.rglob("*.json"):
        assert path.stem == sha256_bytes(path.read_bytes())


def test_source_manifests_exclude_sqlite_transient_sidecars(tmp_path: Path) -> None:
    history = build_history(FakeSnapshot(tmp_path / "snapshot"), tool_commit=TOOL_COMMIT)
    for payload in history.sources.values():
        paths = [item["path"] for item in json.loads(payload)["artifacts"]]
        assert not any(path.endswith((".sqlite-shm", ".sqlite-wal")) for path in paths)


def test_additions_audit_keeps_originals_and_additions_separate() -> None:
    assert additions_audit() == {
        "schema_version": 1,
        "contract": "legacy-historical-additions-audit-v1",
        "changed_dates": 57,
        "original_population": {"files": 568, "bytes": 18177646221},
        "addition_population": {"files": 688, "bytes": 147127281},
        "legacy_findings_preserved": True,
    }
