"""Exact transport selection and membership races, not business data fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import pi_drive_backup as backup
from pi_drive_backup_source import restore_relative
from pi_drive_backup_targets import backup_targets


@pytest.fixture
def scope(tmp_path):
    data, stage = tmp_path / "data", tmp_path / "spool/freeze-test"
    data.mkdir()
    stage.mkdir(parents=True)
    manifest_path = stage.parent / "manifest.json"
    manifest_path.write_text("frozen manifest transport fixture")
    return data, stage, manifest_path


def add(path, *, direct=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"transport fixture\n")
    return {"backup_path": path.as_posix(), "source_path": path.as_posix(),
            "direct": direct, "size": path.stat().st_size}


def prepare(scope, rows):
    data, stage, manifest = scope
    return backup_targets({"files": rows}, stage, data, manifest, lambda: None)


def listed(targets):
    return [Path(value.decode()) for value in targets.path.read_bytes().split(b"\x00") if value]


def expanded(paths):
    return {p for root in paths for p in (root.rglob("*") if root.is_dir() else [root]) if p.is_file()}


def test_recursive_compaction_preserves_exact_selection_and_literal_paths(scope):
    data, stage, manifest = scope
    rows = [add(data / f"runs/day/provider/product-{i}/detail [literal].json") for i in range(20)]
    rows += [add(stage / "control/service.conf", direct=False), add(stage / "data/state/marker.json", direct=False)]
    with prepare(scope, rows) as targets:
        assert expanded(listed(targets)) == {Path(row["backup_path"]) for row in rows} | {manifest}
        assert targets.target_count == 4  # finalized run, two private roots, manifest
        assert data / "runs" not in listed(targets) and stage not in listed(targets)
        targets.check_summary({"total_files_processed": 23,
                               "total_bytes_processed": sum(row["size"] for row in rows) + manifest.stat().st_size})


@pytest.mark.parametrize("extra", ["credentials.env", "unselected/secret.txt", "empty-directory"])
def test_partial_directories_never_add_unselected_entries(scope, extra):
    data, _, manifest = scope
    root = data / "runs/day"
    rows = [add(root / "chosen.txt"), add(root / "complete/nested/chosen.txt")]
    if extra == "empty-directory":
        (root / extra).mkdir()
    else:
        add(root / extra)
    with prepare(scope, rows) as targets:
        assert root not in listed(targets)
        assert expanded(listed(targets)) == {Path(row["backup_path"]) for row in rows} | {manifest}


def test_post_upload_check_detects_nested_membership_change(scope):
    data, _, _ = scope
    root = data / "runs/day"
    rows = [add(root / "a/b/chosen.txt")]
    with prepare(scope, rows) as targets:
        add(root / "a/b/unselected.txt")
        # Root metadata can remain unchanged; all selected descendant dirs count.
        with pytest.raises(RuntimeError, match="membership changed"):
            targets.verify()


def test_manifest_path_replacement_and_outside_scope_fail_closed(scope):
    data, stage, _ = scope
    outside = add(data / "state/live.txt")
    with pytest.raises(ValueError, match="outside immutable"):
        with prepare(scope, [outside]):
            pass
    assert (stage / "targets.sqlite").exists()  # caller retains evidence until stage cleanup


def test_hardlinked_selected_file_is_refused(scope):
    data, _, _ = scope
    row = add(data / "runs/day/chosen.txt")
    os.link(row["backup_path"], data / "runs/day/alias.txt")
    with pytest.raises(ValueError, match="unsafe backup source"):
        with prepare(scope, [row]):
            pass


@pytest.mark.parametrize("files,bytes_", [(2, 1), (1, 2), (True, 1), (1, True)])
def test_summary_mismatch_cannot_pass(scope, files, bytes_):
    row = add(scope[0] / "runs/day/chosen.txt")
    with prepare(scope, [row]) as targets:
        with pytest.raises(ValueError, match="totals differ"):
            targets.check_summary({"total_files_processed": files, "total_bytes_processed": bytes_})


def test_native_compacted_targets_incremental_exact_restore(scope, monkeypatch):
    executable = shutil.which("restic")
    if not executable:
        pytest.skip("requires native Restic")
    version = subprocess.run([executable, "version"], capture_output=True, text=True, check=True, timeout=10).stdout
    if not version.startswith("restic 0.18."):
        pytest.skip("transport pinned to deployed Restic 0.18")
    data, stage, manifest = scope
    rows = [add(data / f"runs/day/provider/product-{i}/detail [literal].txt") for i in range(30)]
    rows += [add(data / "runs/partial/chosen.txt")]
    excluded = data / "runs/partial/credentials.env"
    add(excluded)
    spool = stage.parent
    password = spool / "password"
    password.write_text("temporary-native-transport-test")
    password.chmod(0o600)
    client = backup.Restic(backup.Config(data, spool, str(spool / "repository"), password,
                                       spool / "unused-rclone", [], restic=executable))
    monkeypatch.setattr(backup, "guard_window", lambda: None)
    client.run("init", "--repository-version", "2")
    # Seed explicit files to verify compatibility with already accepted snapshots.
    original = spool / "original.raw"
    original.write_bytes(b"".join((row["backup_path"].encode() + b"\x00") for row in rows)
                         + manifest.as_posix().encode() + b"\x00")
    first = json.loads(client.run("backup", "--json", "--no-scan", "--group-by", "host,tags",
                                 "--files-from-raw", str(original)))
    changed = Path(rows[0]["backup_path"])
    changed.write_bytes(b"changed transport fixture\n" * 20)
    rows[0]["size"] = changed.stat().st_size
    with prepare(scope, rows) as targets:
        assert targets.target_count == 3
        final = json.loads(client.run("backup", "--json", "--no-scan", "--group-by", "host,tags",
                                     "--files-from-raw", str(targets.path)))
        targets.verify()
        targets.check_summary(final)
    assert first["snapshot_id"] != final["snapshot_id"]
    assert final["files_changed"] == 1 and final["files_unmodified"] == len(rows)
    client.run("check")
    restored = spool / "restored"
    client.run("restore", final["snapshot_id"], "--target", str(restored), "--verify")
    expected = {restore_relative(path.as_posix()).as_posix(): path.read_bytes()
                for path in [*(Path(r["backup_path"]) for r in rows), manifest]}
    actual = {p.relative_to(restored).as_posix(): p.read_bytes() for p in restored.rglob("*") if p.is_file()}
    assert actual == expected and not any(p.name == excluded.name for p in restored.rglob("*"))
