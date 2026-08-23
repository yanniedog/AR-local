"""Fail-closed tests for preservation source scoping."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ar_local_backup_scope import (  # noqa: E402
    build_data_scope,
    copy_scoped_data,
    metadata_only_records,
    scoped_tree_metadata,
)


def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "runs/2026-08-24").mkdir(parents=True)
    (root / "runs/2026-08-24/local-cdr.sqlite").write_bytes(b"sqlite evidence")
    (root / "state/export-contracts-v2").mkdir(parents=True)
    (root / "state/export-contracts-v2/contract.json").write_text("{}\n", encoding="utf-8")
    return root


def test_scope_copies_cdr_roots_without_traversing_netdata_secrets(tmp_path: Path) -> None:
    root = data_root(tmp_path)
    (root / ".daily-export-stage").mkdir()
    (root / "netdata/lib/bearer_tokens").mkdir(parents=True)
    secret = root / "netdata/lib/mcp_dev_preview_api_key"
    secret.write_text("must-not-enter-snapshot", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs/ingest.log").write_text("retained log\n", encoding="utf-8")
    scope = build_data_scope(root.resolve())
    assert [path.name for path in scope.included] == ["runs", "state", "logs"]
    manifest = scope.manifest()
    assert manifest["unknown_roots_allowed"] is False
    netdata = next(item for item in manifest["excluded"] if item["path"] == "netdata")
    assert netdata["exists"] is True
    assert netdata["contents_copied"] is False
    destination = tmp_path / "snapshot-data"
    copy_scoped_data(scope, destination, exclude=set())
    assert (destination / "runs/2026-08-24/local-cdr.sqlite").is_file()
    assert (destination / "state/export-contracts-v2/contract.json").is_file()
    assert (destination / "logs/ingest.log").is_file()
    assert not (destination / "netdata").exists()
    assert not (destination / ".daily-export-stage").exists()
    assert b"must-not-enter-snapshot" not in b"".join(
        path.read_bytes() for path in destination.rglob("*") if path.is_file()
    )
    assert secret in scope.secret_locations


def test_scope_rejects_unknown_top_level_path(tmp_path: Path) -> None:
    root = data_root(tmp_path)
    (root / "unclassified-business-data").mkdir()
    with pytest.raises(ValueError, match="unclassified paths"):
        build_data_scope(root.resolve())


def test_scope_rejects_nonempty_transient_stage(tmp_path: Path) -> None:
    root = data_root(tmp_path)
    (root / ".daily-export-stage").mkdir()
    (root / ".daily-export-stage/partial.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="transient data path is not empty"):
        build_data_scope(root.resolve())


@pytest.mark.parametrize("missing", ("runs", "state"))
def test_scope_requires_cdr_history_and_state(tmp_path: Path, missing: str) -> None:
    root = data_root(tmp_path)
    target = root / missing
    for path in sorted(target.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    target.rmdir()
    with pytest.raises(ValueError, match="missing required paths"):
        build_data_scope(root.resolve())


def test_scope_rejects_hardlinked_business_evidence(tmp_path: Path) -> None:
    root = data_root(tmp_path)
    source = root / "runs/2026-08-24/local-cdr.sqlite"
    os.link(source, root / "runs/2026-08-24/alias.sqlite")
    scope = build_data_scope(root.resolve())
    with pytest.raises(ValueError, match="not a unique regular file"):
        scoped_tree_metadata(scope, set())


def test_metadata_only_inventory_never_reports_permission_denial_as_absent(
    monkeypatch, tmp_path: Path
) -> None:
    protected = tmp_path / "protected-secret"
    original = Path.stat

    def deny_target(path: Path, *args, **kwargs):
        if path == protected:
            raise PermissionError("simulated protected parent")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", deny_target)
    record = metadata_only_records([protected])[0]
    assert record == {
        "path": str(protected),
        "exists": None,
        "metadata_status": "INACCESSIBLE",
    }
