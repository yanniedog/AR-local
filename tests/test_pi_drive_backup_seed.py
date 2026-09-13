"""Restore transport fixtures, never production backup acceptance."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

import pi_drive_backup as backup
import pi_drive_backup_seed as seed
import pi_drive_backup_recovery as recovery


def spec(path):
    info = path.stat()
    return {"directory": path.name, "device": info.st_dev, "inode": info.st_ino}


@pytest.mark.parametrize("patch", [{"directory": "../restore-abcdefgh"}, {"directory": "/restore-abcdefgh"},
    {"directory": "restore-abcdefgh/child"}, {"directory": "restore-abcdefgh\\child"},
    {"directory": "cache"}, {"inode": 0}, {"inode": True}, {"device": -1}, {"device": "1"}, {"extra": 1}])
def test_descriptor_rejects_unbounded_or_ambiguous_seed(patch):
    with pytest.raises(ValueError): seed.validate_seed({"directory": "restore-abcdefgh", "device": 1, "inode": 2, **patch})


def test_copy_is_bounded_and_never_propagates_source_metadata(tmp_path):
    source = tmp_path / "source"; source.write_bytes(b"payload" * 10000)
    source.chmod(0o444)
    target = tmp_path / "new" / "copied"
    before = source.read_bytes(), source.stat().st_mtime_ns
    with source.open("rb") as stream:
        count, digest = seed.copy_file(stream, source.stat(), target, lambda: None)
    assert count == source.stat().st_size and digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert target.read_bytes() == source.read_bytes() and target.stat().st_ino != source.stat().st_ino
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    target.write_bytes(b"independent")
    assert source.read_bytes() == before[0]


@pytest.mark.parametrize("body,size", [(b"short", 9), (b"growing", 3)])
def test_copy_rejects_truncation_or_growth(tmp_path, body, size):
    source = tmp_path / "source"; source.write_bytes(body)
    with source.open("rb") as stream, pytest.raises(ValueError, match="grew|truncated"):
        seed.copy_file(stream, SimpleNamespace(st_size=size), tmp_path / "new", lambda: None)


def test_copy_refuses_existing_destination_and_propagates_guard(tmp_path):
    target = tmp_path / "new"; target.write_bytes(b"preserve")
    source = tmp_path / "source"; source.write_bytes(b"x")
    with source.open("rb") as stream, pytest.raises(FileExistsError):
        seed.copy_file(stream, source.stat(), target, lambda: None)
    assert target.read_bytes() == b"preserve"
    def guard(): raise backup.Blocked("quiet window")
    with source.open("rb") as stream, pytest.raises(backup.Blocked):
        seed.copy_file(stream, source.stat(), tmp_path / "other", guard)


@pytest.fixture
def posix_seed(tmp_path, monkeypatch):
    if os.name != "posix": pytest.skip("native openat/read-only mount contract requires POSIX")
    root = tmp_path / "restore-abcdefgh"; root.mkdir()
    target = tmp_path / "restore-ijklmnop"; target.mkdir()
    # Only the kernel mount response is synthetic; all traversal/copy I/O is real.
    monkeypatch.setattr(os, "fstatvfs", lambda _: SimpleNamespace(f_flag=os.ST_RDONLY))
    return root, target


def row(name, size):
    return {"backup_path": "/" + name, "logical_path": "data/" + name, "size": size}


def test_native_seed_counts_missing_partial_corrupt_and_oversize_hints(posix_seed):
    root, target = posix_seed
    (root / "short").write_bytes(b"par")
    (root / "corrupt").write_bytes(b"wrong")
    (root / "oversize").write_bytes(b"too long")
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    result = seed.copy_seed(root.parent, target, [row("short", 8), row("corrupt", 5), row("missing", 3), row("oversize", 2)], spec(root), guard=lambda: None)
    assert result["files_copied"] == 2 and result["bytes_copied"] == 8
    assert result["files_missing"] == result["files_oversize"] == 1
    assert (target / "short").read_bytes() == b"par" and (target / "corrupt").read_bytes() == b"wrong"
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}
    seed.validate_seed_receipt(spec(root), result)


@pytest.mark.parametrize("fault", ["file_symlink", "parent_symlink", "hardlink", "fifo", "escape"])
def test_native_seed_refuses_nonregular_or_escaping_paths(posix_seed, fault):
    root, target = posix_seed
    outside = root.parent / "outside"; outside.mkdir(); (outside / "item").write_bytes(b"x")
    name = "item"
    if fault == "file_symlink": (root / name).symlink_to(outside / "item")
    elif fault == "parent_symlink": (root / "parent").symlink_to(outside, target_is_directory=True); name = "parent/item"
    elif fault == "hardlink": os.link(outside / "item", root / name)
    elif fault == "fifo": os.mkfifo(root / name)
    else: name = "../outside/item"
    with pytest.raises((ValueError, OSError)):
        seed.copy_seed(root.parent, target, [row(name, 1)], spec(root), guard=lambda: None)
    assert (outside / "item").read_bytes() == b"x"


@pytest.mark.parametrize("fault", ["writable", "identity", "same_target", "nonempty"])
def test_native_seed_requires_readonly_identity_and_fresh_destination(posix_seed, monkeypatch, fault):
    root, target = posix_seed; value = spec(root)
    if fault == "writable": monkeypatch.setattr(os, "fstatvfs", lambda _: SimpleNamespace(f_flag=0))
    elif fault == "identity": value["inode"] += 1
    elif fault == "same_target": target = root
    else: (target / "unrelated").write_bytes(b"preserve")
    with pytest.raises(ValueError): seed.copy_seed(root.parent, target, [], value, guard=lambda: None)


@pytest.mark.parametrize("fault", ["replace", "disappear", "mutate"])
def test_native_seed_rejects_source_races_after_open(posix_seed, monkeypatch, fault):
    root, target = posix_seed
    source = root / "item"; source.write_bytes(b"old")
    real = seed.copy_file
    def copy(stream, info, destination, guard):
        result = real(stream, info, destination, guard)
        if fault == "disappear": source.unlink()
        elif fault == "mutate": source.write_bytes(b"new")
        else:
            replacement = root / "replacement"; replacement.write_bytes(b"old"); replacement.replace(source)
        return result
    monkeypatch.setattr(seed, "copy_file", copy)
    with pytest.raises(ValueError): seed.copy_seed(root.parent, target, [row("item", 3)], spec(root), guard=lambda: None)


def test_native_seed_rejects_parent_replacement_during_copy(posix_seed, monkeypatch):
    root, target = posix_seed
    parent = root / "parent"; parent.mkdir(); (parent / "item").write_bytes(b"old")
    real = seed.copy_file
    def copy(stream, info, destination, guard):
        result = real(stream, info, destination, guard)
        parent.rename(root / "previous")
        parent.mkdir(); (parent / "item").write_bytes(b"old")
        return result
    monkeypatch.setattr(seed, "copy_file", copy)
    with pytest.raises(ValueError, match="parent changed"):
        seed.copy_seed(root.parent, target, [row("parent/item", 3)], spec(root), guard=lambda: None)


@pytest.mark.parametrize("patch", [{"untrusted": False}, {"read_only": False}, {"files_copied": True},
    {"files_missing": 2}, {"bytes_copied": -1}, {"copied_streams_sha256": "bad"}, {"seed": {}}])
def test_parent_refuses_unbound_seed_accounting(patch):
    identity = {"directory": "restore-abcdefgh", "device": 1, "inode": 2}
    value = {"schema": seed.SCHEMA, "seed": identity, "untrusted": True, "read_only": True,
        "files_considered": 1, "files_copied": 1, "files_missing": 0, "files_oversize": 0,
        "bytes_copied": 5, "copied_streams_sha256": "a" * 64}
    with pytest.raises(ValueError): seed.validate_seed_receipt(identity, {**value, **patch})


@pytest.mark.parametrize("repair", [True, False])
def test_seed_is_not_acceptance_full_bytes_and_sqlite_still_required(posix_seed, tmp_path, monkeypatch, repair):
    root, unused_target = posix_seed
    database = tmp_path / "snapshot.sqlite"
    with sqlite3.connect(database) as connection: connection.execute("CREATE TABLE transport_control(id INTEGER PRIMARY KEY)")
    (root / "snapshot.sqlite").write_bytes(b"partial and corrupt")
    manifest_path = tmp_path / "source-manifest.json"; manifest_path.write_text('{"fixture":"transport"}')
    manifest = {"files": [{**row("snapshot.sqlite", database.stat().st_size),
        "sha256": backup.digest(database), "sqlite": True}]}
    config = backup.Config(tmp_path / "unread-source", tmp_path, "unused", tmp_path / "password", tmp_path / "config", [])
    monkeypatch.setattr(backup, "guard_window", lambda: None)
    before = (root / "snapshot.sqlite").read_bytes()
    seen = []
    class Transport:
        def run(self, *args):
            assert args[0] == "restore" and args[1] == "a" * 64
            assert args[-3:] == ("--overwrite", "always", "--verify")
            target = Path(args[args.index("--target") + 1]); seen.append(target)
            assert target != root and (target / "snapshot.sqlite").read_bytes() == before
            if repair: shutil.copyfile(database, target / "snapshot.sqlite")
            destination = target / backup.restore_relative(manifest_path.as_posix())
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(manifest_path, destination)
            return ""
    if repair:
        result = backup.restore_snapshot(config, Transport(), "a" * 64, manifest, full=True,
                                         manifest_path=manifest_path, seed=spec(root))
        assert result["files_verified"] == 2 and result["databases_verified"] == 1
        assert result["seed"]["untrusted"] and result["full"] is True
    else:
        with pytest.raises(ValueError, match="restored bytes differ"):
            backup.restore_snapshot(config, Transport(), "a" * 64, manifest, full=True,
                                    manifest_path=manifest_path, seed=spec(root))
    assert root.is_dir() and (root / "snapshot.sqlite").read_bytes() == before
    assert seen and all(not path.exists() for path in seen) and unused_target.is_dir()
    assert not (tmp_path / "latest-verified.json").exists() and not config.data.exists()


def test_seed_cannot_be_used_for_partial_restore(tmp_path):
    with pytest.raises(ValueError, match="full snapshot"):
        backup.restore_snapshot(None, None, "a" * 64, {}, seed={})


def test_cleanup_refuses_replaced_fresh_target(tmp_path, monkeypatch):
    database = tmp_path / "snapshot.sqlite"
    with sqlite3.connect(database) as connection: connection.execute("CREATE TABLE transport_control(id INTEGER PRIMARY KEY)")
    manifest = {"files": [{**row("snapshot.sqlite", database.stat().st_size),
        "sha256": backup.digest(database), "sqlite": True}]}
    config = backup.Config(tmp_path / "source", tmp_path, "unused", tmp_path / "password", tmp_path / "config", [])
    monkeypatch.setattr(backup, "guard_window", lambda: None)
    seen = []
    class Transport:
        def run(self, *args):
            target = Path(args[args.index("--target") + 1]); seen.append(target)
            target.rename(tmp_path / "retained-original-target")
            target.mkdir(); (target / "unrelated").write_text("preserve")
            raise RuntimeError("transport fixture failure")
    with pytest.raises(ValueError, match="unsafe restore cleanup"):
        backup.restore_snapshot(config, Transport(), "a" * 64, manifest, full=True)
    assert (seen[0] / "unrelated").read_text() == "preserve"
    assert (tmp_path / "retained-original-target").is_dir()


def test_real_local_restic_repairs_corrupt_seed_and_full_sqlite(posix_seed, tmp_path, monkeypatch):
    executable = shutil.which("restic")
    if not executable: pytest.skip("real Restic fixture runs when the native binary is installed")
    version = subprocess.run([executable, "version"], capture_output=True, text=True, timeout=10, check=True).stdout
    if not version.startswith("restic 0.18."): pytest.skip("fixture is pinned to deployed Restic 0.18")
    root, _unused = posix_seed
    source = tmp_path / "transport-source"; source.mkdir()
    (source / "blob").write_bytes(bytes(range(256)) * 8192)
    database = source / "fixture.sqlite"
    with sqlite3.connect(database) as connection: connection.execute("CREATE TABLE transport_control(id INTEGER PRIMARY KEY)")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "RESTIC_PASSWORD": "temporary-local-transport-fixture", "GOMAXPROCS": "1", "GOMEMLIMIT": "96MiB"}
    def command(*args):
        return subprocess.run([executable, "--no-cache", "--repo", str(tmp_path / "repository"), *args],
                              env=env, capture_output=True, text=True, timeout=60, check=True).stdout
    command("init")
    output = command("backup", "--json", str(source))
    snapshot = [json.loads(line)["snapshot_id"] for line in output.splitlines()
                if json.loads(line).get("message_type") == "summary"][0]
    rows = []
    for path in source.iterdir():
        rows.append({"logical_path": "data/" + path.name, "backup_path": path.as_posix(),
                     "size": path.stat().st_size, "sha256": backup.digest(path), "sqlite": path == database})
        cached = root / backup.restore_relative(path.as_posix()); cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(b"bad partial")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(backup, "guard_window", lambda: None)
    config = backup.Config(tmp_path / "untouched", tmp_path, "unused", tmp_path / "password", tmp_path / "config", [])
    class Transport:
        def run(self, *args): return command("--quiet", *args)
    result = backup.restore_snapshot(config, Transport(), snapshot, {"files": rows}, full=True, seed=spec(root))
    assert result["files_verified"] == 2 and result["databases_verified"] == 1
    assert result["seed"]["files_copied"] == 2 and result["seed"]["untrusted"] is True
    assert all(path.read_bytes() == body for path, body in before.items())
