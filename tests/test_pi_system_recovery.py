"""File-only recovery tests. No sudo, mounting, loop or physical device writes."""
import base64
import io
import json
import os
import shutil
import sqlite3
import stat
import struct
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_system_capture as capture
import pi_system_image as image
import pi_system_namespace as namespace
import pi_system_raw_restore as raw_restore
import pi_system_filesystems as filesystems


@pytest.fixture
def portable_metadata(monkeypatch):
    # POSIX ACL/xattr native support is verified separately on Linux. These
    # empty attribute shims permit real file/manifest tests on Windows.
    if not hasattr(capture.os, "listxattr"):
        monkeypatch.setattr(capture.os, "listxattr", lambda *args, **kwargs: [], raising=False)
    if not hasattr(capture.os, "getxattr"):
        monkeypatch.setattr(capture.os, "getxattr", lambda *args, **kwargs: b"", raising=False)
    if not hasattr(capture.os, "O_NOFOLLOW"):
        monkeypatch.setattr(capture.os, "O_NOFOLLOW", 0, raising=False)


def test_mbr_has_only_expected_fat_and_root_partitions():
    body = image.mbr(0x12345678, 8 * 1024 * 2048)
    assert len(body) == 512 and body[510:] == b"\x55\xaa"
    assert struct.unpack_from("<I", body, 440)[0] == 0x12345678
    boot = struct.unpack_from("<B3sB3sII", body, 446)
    root = struct.unpack_from("<B3sB3sII", body, 462)
    assert (boot[0], boot[2], boot[4], boot[5]) == (0x80, 0x0C, 8192, 1048576)
    assert (root[0], root[2], root[4], root[5]) == (0, 0x83, 1056768, 8 * 1024 * 2048)
    assert not any(body[478:510])


@pytest.mark.parametrize("disk,sectors", [(0, 32768), (-1, 32768), (2 ** 32, 32768), (1, 1), (1, 2 ** 32)])
def test_mbr_rejects_invalid_geometry(disk, sectors):
    with pytest.raises(ValueError):
        image.mbr(disk, sectors)


@pytest.mark.parametrize("name", ["../x", "/etc", "a/../b", "a//b", "a/./b", "", "."])
def test_restore_paths_cannot_escape(name):
    with pytest.raises(ValueError):
        capture.relative(name)


@pytest.mark.parametrize("loop", ["/dev/sda", "/dev/nvme0n1", "/dev/mmcblk0", "/dev/loop0p1", "../dev/loop0"])
def test_backing_lookup_rejects_every_physical_device_name(loop):
    with pytest.raises(ValueError):
        image.backing_file(loop)


def test_batch_copy_memory_is_bounded(monkeypatch, tmp_path):
    sizes = []
    monkeypatch.setattr(capture, "copy_batch", lambda work, settings, tree, batch, label: sizes.append(len(batch)))
    capture.copy_batches(tmp_path, {}, "root", (str(n).encode() for n in range(10001)), "test")
    assert sizes == [4096, 4096, 1809]


def test_null_file_list_preserves_newlines_and_multiblock_paths(tmp_path):
    file = tmp_path / "paths"
    expected = [b"normal", b"contains\nnewline", b"x" * 70000]
    file.write_bytes(b"\0".join(expected) + b"\0")
    assert list(capture.null_names(file)) == expected
    file.write_bytes(b"truncated")
    with pytest.raises(ValueError, match="truncated"):
        list(capture.null_names(file))


def test_cross_batch_hardlinks_reconstructed_only_in_private_stage(tmp_path):
    root = tmp_path / "frozen/root"
    root.mkdir(parents=True)
    (root / "first").write_bytes(b"same source inode")
    (root / "second").write_bytes(b"same source inode")
    source = tmp_path / "untouched-source"
    source.write_bytes(b"source unchanged")
    database = sqlite3.connect(tmp_path / "inventory.sqlite")
    database.execute("CREATE TABLE links(phase TEXT,tree TEXT,dev INTEGER,ino INTEGER,path TEXT)")
    database.executemany("INSERT INTO links VALUES (?,?,?,?,?)", [("final", "root", 1, 2, "first"), ("final", "root", 1, 2, "second")])
    database.commit()
    database.close()
    capture.repair_hardlinks(tmp_path, "final", "root")
    assert (root / "first").stat().st_ino == (root / "second").stat().st_ino
    assert source.read_bytes() == b"source unchanged"


def test_hardlink_content_disagreement_stays_failure(tmp_path):
    root = tmp_path / "frozen/root"
    root.mkdir(parents=True)
    (root / "first").write_bytes(b"old bytes")
    (root / "second").write_bytes(b"changed bytes")
    database = sqlite3.connect(tmp_path / "inventory.sqlite")
    database.execute("CREATE TABLE links(phase TEXT,tree TEXT,dev INTEGER,ino INTEGER,path TEXT)")
    database.executemany("INSERT INTO links VALUES (?,?,?,?,?)", [("final", "root", 1, 2, "first"), ("final", "root", 1, 2, "second")])
    database.commit()
    database.close()
    with pytest.raises(ValueError, match="changed during copy"):
        capture.repair_hardlinks(tmp_path, "final", "root")
    assert (root / "first").read_bytes() == b"old bytes"
    assert (root / "second").read_bytes() == b"changed bytes"


def test_full_restored_manifest_rejects_byte_and_metadata_changes(tmp_path, portable_metadata):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "file").write_bytes(b"real existing bytes")
    manifest = tmp_path / "manifest.jsonl"
    capture.tree_manifest(root, manifest)
    assert image.verify_tree(root, manifest)["result"] == "PASS"
    (root / "file").write_bytes(b"corrupted content")
    with pytest.raises(ValueError, match="differ"):
        image.verify_tree(root, manifest)


def test_manifest_captures_binary_attributes_and_hardlink_identity(monkeypatch, tmp_path, portable_metadata):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "first").write_bytes(b"same bytes")
    os.link(root / "first", root / "second")
    monkeypatch.setattr(capture.os, "listxattr", lambda *args, **kwargs: ["user.raw"], raising=False)
    monkeypatch.setattr(capture.os, "getxattr", lambda *args, **kwargs: b"\xff\x00ACL", raising=False)
    rows = list(capture.metadata(root, tmp_path / "links.sqlite"))
    assert rows[1]["xattrs"]["user.raw"] == base64.b64encode(b"\xff\x00ACL").decode()
    assert rows[2]["hardlink_to"] == "first"
    assert rows[2]["sha256"] == rows[1]["sha256"]


def test_image_boot_identifiers_change_only_image_configuration(tmp_path, portable_metadata):
    root, boot = tmp_path / "root", tmp_path / "boot"
    (root / "etc").mkdir(parents=True)
    boot.mkdir()
    (root / "etc/fstab").write_text("PARTUUID=8fbb928c-02 / ext4 defaults 0 1\nPARTUUID=8fbb928c-01 /boot/firmware vfat defaults 0 2\n")
    (boot / "cmdline.txt").write_text("console=tty1 root=PARTUUID=8fbb928c-02 rootfstype=ext4 rootwait\n")
    original = {"disk_id": "8fbb928c", "root_uuid": "root-old", "boot_uuid": "FAT-OLD"}
    identifiers = {"disk_id": "abcdef12", "root_uuid": "root-new", "boot_uuid": "1234-ABCD"}
    before = (boot / "cmdline.txt").stat().st_mtime_ns
    transforms = image.rewrite_boot(root, boot, original, identifiers)
    assert "root=PARTUUID=abcdef12-02" in (boot / "cmdline.txt").read_text()
    assert "PARTUUID=abcdef12-01" in (root / "etc/fstab").read_text()
    assert (boot / "cmdline.txt").stat().st_mtime_ns == before
    assert transforms["boot"]["cmdline.txt"]["before_sha256"] != transforms["boot"]["cmdline.txt"]["after_sha256"]


def test_unknown_boot_root_configuration_cannot_be_accepted(tmp_path, portable_metadata):
    root, boot = tmp_path / "root", tmp_path / "boot"
    (root / "etc").mkdir(parents=True)
    boot.mkdir()
    (root / "etc/fstab").write_text("/dev/UNKNOWN / ext4 defaults 0 1\n")
    (boot / "cmdline.txt").write_text("root=/dev/UNKNOWN\n")
    with pytest.raises(ValueError, match="unrecognized"):
        image.rewrite_boot(root, boot, {"disk_id": "a", "root_uuid": "b", "boot_uuid": "c"},
                           {"disk_id": "d", "root_uuid": "e", "boot_uuid": "f"})


def test_image_size_reserves_inode_metadata_and_counts_entries(tmp_path):
    file = tmp_path / "manifest"
    file.write_text(json.dumps({"path": "file", "size": 1024}) + "\n" + json.dumps({"path": "link", "size": 1024, "hardlink_to": "file"}) + "\n")
    size, entries = image.image_size(file)
    assert size >= 4096 and entries == 2


def test_archive_stream_preserves_bytes_and_global_hardlinks_without_member_cache(monkeypatch, tmp_path, portable_metadata):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "first").write_bytes(b"payload bytes")
    os.link(root / "first", root / "second")
    manifest = tmp_path / "manifest"
    capture.tree_manifest(root, manifest)
    class OpenBuffer(io.BytesIO):
        def close(self):
            self.saved = self.getvalue()
    buffer = OpenBuffer()
    child = SimpleNamespace(stdin=buffer, wait=lambda: 0, poll=lambda: 0)
    monkeypatch.setattr(capture.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(capture, "run", lambda *args, **kwargs: None)
    capture.compressed_tar(root, manifest, tmp_path / "output")
    with tarfile.open(fileobj=io.BytesIO(buffer.saved)) as archive:
        assert archive.extractfile("first").read() == b"payload bytes"
        assert archive.getmember("second").islnk()
        assert archive.getmember("second").linkname == "first"
        assert "ARLOCAL.metadata" in archive.getmember("first").pax_headers


@pytest.mark.parametrize("octal", [True, False])
def test_external_raw_index_accepts_worker_octal_mode_and_exact_bytes(tmp_path, portable_metadata, octal):
    file = tmp_path / "raw.json"
    file.write_bytes(b"real captured raw bytes")
    info = file.stat()
    row = {"size": info.st_size, "mtime_ns": info.st_mtime_ns, "mode": oct(stat.S_IMODE(info.st_mode)) if octal else stat.S_IMODE(info.st_mode),
           "uid": info.st_uid, "gid": info.st_gid, "sha256": capture.sha(file), "representation": "exact_source_bytes"}
    database = sqlite3.connect(":memory:")
    database.execute("CREATE TABLE files(path TEXT PRIMARY KEY,row_json TEXT)")
    database.execute("INSERT INTO files VALUES (?,?)", ("srv/ar-local/data/runs/raw.json", json.dumps(row)))
    result = capture.external_match(file, info, "srv/ar-local/data/runs/raw.json", database)
    assert result["sha256"] == row["sha256"]
    assert result["mode"] == row["mode"]
    file.write_bytes(b"different source bytes")
    assert capture.external_match(file, file.stat(), "srv/ar-local/data/runs/raw.json", database) is None


def test_new_fat_uuid_is_referenced_with_hyphen_in_fstab(tmp_path, portable_metadata):
    root, boot = tmp_path / "root", tmp_path / "boot"
    (root / "etc").mkdir(parents=True)
    boot.mkdir()
    (root / "etc/fstab").write_text("UUID=ROOT-OLD / ext4 defaults 0 1\nUUID=6222-0710 /boot/firmware vfat defaults 0 2\n")
    (boot / "cmdline.txt").write_text("root=UUID=ROOT-OLD rootwait\n")
    image.rewrite_boot(root, boot, {"disk_id": "8fbb928c", "root_uuid": "ROOT-OLD", "boot_uuid": "6222-0710"},
                       {"disk_id": "12345678", "root_uuid": "ROOT-NEW", "boot_uuid": "AABB-CCDD"})
    assert "UUID=AABB-CCDD /boot/firmware" in (root / "etc/fstab").read_text()


@pytest.mark.parametrize("phase", ["baseline", "prepare", "finalize", "archive", "build", "compress"])
def test_namespace_hides_host_processes_devices_network_and_source_from_privileged_build(phase):
    argv = namespace.argv_for(Path("/protected/code"), Path("/var/lib/ar-local-system-recovery/test"), phase, [])
    assert "--unshare-pid" in argv and "--unshare-net" in argv
    assert "--unshare-user" not in argv
    assert ["--proc", "/proc"] == argv[argv.index("--proc"):argv.index("--proc") + 2]
    assert "--remount-ro" in argv
    assert ("/source/root" in argv) == (phase in {"baseline", "prepare", "finalize"})
    assert ("CAP_SYS_ADMIN" in argv) == (phase == "build")
    assert ("/dev/loop-control" in argv) == (phase == "build")
    assert "/dev/nvme0n1" not in argv and "/dev/mmcblk0" not in argv and "/dev/sda" not in argv
    assert ["--ro-bind", "/protected/code", "/code"] not in [argv[index:index + 3] for index in range(len(argv))]
    exposed = {argv[index + 2] for index, value in enumerate(argv[:-2]) if value == "--ro-bind" and argv[index + 2].startswith("/code/")}
    assert exposed == {"/code/" + name for name in namespace.BUNDLE}
    assert "/code/subprocess.py" not in argv and "/code/hashlib.py" not in argv


def test_root_child_cannot_import_unreviewed_stdlib_shadowing_siblings(tmp_path):
    bundle = tmp_path / "reviewed-staging"
    bundle.mkdir()
    (bundle / "subprocess.py").write_text("raise RuntimeError('unreviewed sibling executed')")
    (bundle / "hashlib.py").write_text("raise RuntimeError('unreviewed sibling executed')")
    argv = namespace.argv_for(bundle, Path("/var/lib/ar-local-system-recovery/test"), "build", [])
    bindings = [argv[index + 1:index + 3] for index, value in enumerate(argv[:-2]) if value == "--ro-bind"]
    assert [str(bundle), "/code"] not in bindings
    assert {target for source, target in bindings if target.startswith("/code/")} == {"/code/" + name for name in namespace.BUNDLE}
    assert all("subprocess.py" not in source and "hashlib.py" not in source for source, target in bindings)


def test_archive_part_checkpoint_is_reused_and_rejects_changed_bytes(monkeypatch, tmp_path):
    calls = []
    def compress(tree, manifest, output):
        calls.append(output)
        output.write_bytes(b"already verified lossless compressed bytes")
        return {"sha256": capture.sha(output), "bytes": output.stat().st_size}
    monkeypatch.setattr(capture, "compressed_tar", compress)
    rows = [json.dumps({"path": "file", "size": 1}) + "\n"]
    first = capture.archive_part(tmp_path, tmp_path, "root", 1, rows, 1)
    assert capture.archive_part(tmp_path, tmp_path, "root", 1, rows, 1) == first
    assert len(calls) == 1
    (tmp_path / first["path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="prefix changed"):
        capture.archive_part(tmp_path, tmp_path, "root", 1, rows, 1)


def writer_plan():
    return {"mutable_paths": ["etc", "var", "home", "root", "srv", "opt", "usr/local"],
            "application_writers": ["app.service"], "writer_paths": {"app.service": ["srv/app", "var/lib/app"]},
            "online_os_capture": {name: "package writer inventory reviewed; online capture window accepted"
                                  for name in ("usr", "bin", "lib", "lib64", "sbin", "boot")}}


def test_scope_requires_all_mutable_host_locations_and_every_writer(tmp_path):
    plan = writer_plan()
    assert "srv" in capture.mutable_scope(plan, tmp_path)
    plan["mutable_paths"].remove("etc")
    with pytest.raises(ValueError, match="mutable scope"):
        capture.mutable_scope(plan, tmp_path)
    plan = writer_plan()
    plan["writer_paths"]["app.service"] = ["usr/share/mutating-app"]
    with pytest.raises(ValueError, match="outside mutable scope"):
        capture.mutable_scope(plan, tmp_path)


def test_unknown_top_level_work_is_refreshed_not_assumed_immutable(tmp_path):
    (tmp_path / "other-project").mkdir()
    (tmp_path / "operator-notes").write_text("unique work")
    assert {"other-project", "operator-notes"} <= set(capture.mutable_scope(writer_plan(), tmp_path))
    plan = writer_plan()
    del plan["online_os_capture"]["usr"]
    with pytest.raises(ValueError, match="classification"):
        capture.mutable_scope(plan, tmp_path)


def test_scoped_inventory_captures_only_named_subtrees_and_root_metadata(tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/changed").write_text("new config")
    (tmp_path / "usr").mkdir()
    (tmp_path / "usr/old-online-copy").write_text("online window")
    names = [name for name, _, _ in capture.inventory(tmp_path, starts=(".", "etc"), skip={"."}, sort_path=tmp_path.parent / "scoped.sqlite")]
    assert names == [".", "etc", "etc/changed"]


def test_cross_scope_hardlinks_are_rejected_before_final_stage_mutation(tmp_path):
    database = sqlite3.connect(tmp_path / "inventory.sqlite")
    database.execute("CREATE TABLE entries(phase TEXT,tree TEXT,path TEXT,value TEXT)")
    database.execute("CREATE TABLE links(phase TEXT,tree TEXT,dev INTEGER,ino INTEGER,path TEXT)")
    database.executemany("INSERT INTO links VALUES ('prepared','root',1,2,?)", [("etc/a",), ("usr/share/a",)])
    database.commit()
    database.close()
    with pytest.raises(ValueError, match="crosses mutable"):
        capture.clear_mutable_entries(tmp_path, ["etc"])


def test_source_inventory_checkpoint_reuses_complete_artifact_and_preserves_incomplete(tmp_path):
    database = sqlite3.connect(tmp_path / "inventory.sqlite")
    database.execute("CREATE TABLE entries(phase TEXT,tree TEXT,path TEXT,value TEXT)")
    database.execute("INSERT INTO entries VALUES ('final','root','file',?)", (json.dumps({"source": [1], "copy_source_after": [1]}),))
    database.commit()
    database.close()
    (tmp_path / "source.jsonl").write_text("interrupted partial")
    first = capture.inventory_artifact(tmp_path, "source.jsonl")
    assert len(list(tmp_path.glob("source.jsonl.incomplete-*"))) == 1
    assert capture.inventory_artifact(tmp_path, "source.jsonl") == first
    (tmp_path / "source.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="artifact changed"):
        capture.inventory_artifact(tmp_path, "source.jsonl")


def test_exact_raw_layer_rejoins_bytes_and_leaves_committed_views_separate(monkeypatch, tmp_path, portable_metadata):
    restored, root = tmp_path / "restored", tmp_path / "image-root"
    source = restored / "data/runs/day/raw.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(bytes(range(256)) * 100)
    views = restored / "committed-view/runs/day/raw.json"
    views.parent.mkdir(parents=True)
    views.write_bytes(b"must never replace exact source")
    (root / "srv/ar-local/data/runs/day").mkdir(parents=True)
    (restored / "restore-result.json").write_text(json.dumps({"result": "FILES_RESTORED_VERIFIED", "catalog_sha256": "accepted"}))
    info = source.stat()
    row = {"source_relative": "runs/day/raw.json", "representation": "exact_source_bytes", "sha256": capture.sha(source),
           "size": info.st_size, "mode": oct(stat.S_IMODE(info.st_mode)), "uid": info.st_uid, "gid": info.st_gid,
           "mtime_ns": info.st_mtime_ns, "restore_xattrs": {}}
    mapping, manifest = tmp_path / "map", tmp_path / "root.manifest"
    mapping.write_text(json.dumps({"tree": "root", "path": "srv/ar-local/data/runs/day/raw.json", "external": row}) + "\n")
    capture.tree_manifest(root, manifest)
    monkeypatch.setattr(raw_restore.os, "chown", lambda *args, **kwargs: None, raising=False)
    if os.name == "nt":
        native_chmod = os.chmod
        native_utime = os.utime
        monkeypatch.setattr(raw_restore.os, "chmod", lambda path, mode, **kwargs: native_chmod(path, mode))
        monkeypatch.setattr(raw_restore.os, "utime", lambda path, *, ns, **kwargs: native_utime(path, ns=ns))
    full = tmp_path / "full.manifest"
    result = raw_restore.restore_raw(root, restored, mapping, "accepted", manifest, full)
    assert result["files"] == 1 and result["committed_views_used"] is False
    assert (root / "srv/ar-local/data/runs/day/raw.json").read_bytes() == source.read_bytes()
    assert source.read_bytes() != views.read_bytes()
    assert json.loads(full.read_text().splitlines()[-1])["sha256"] == row["sha256"]
    with pytest.raises(ValueError, match="catalog"):
        raw_restore.restore_raw(root, restored, mapping, "different", manifest, tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


def test_raw_map_rejects_committed_view_and_path_mismatch(tmp_path):
    mapping = tmp_path / "map"
    mapping.write_text(json.dumps({"tree": "root", "path": "etc/shadow", "external": {
        "source_relative": "runs/raw", "representation": "sqlite_committed_view"}}))
    with pytest.raises(ValueError, match="exact-source"):
        list(raw_restore.external_files(mapping))


def test_root_metadata_manifest_cannot_escape_image(tmp_path, portable_metadata):
    root = tmp_path / "image"
    root.mkdir()
    manifest = tmp_path / "manifest"
    manifest.write_text(json.dumps({"path": "../outside"}))
    with pytest.raises(ValueError, match="relative path"):
        image.restore_metadata(root, manifest)


@pytest.mark.parametrize("prove_owned", [True, False])
def test_failed_loop_attach_detaches_only_kernel_proved_owned_inode(monkeypatch, tmp_path, prove_owned, portable_metadata):
    import sys
    loop = "/dev/loop41"
    original = tmp_path / "image"
    original.write_bytes(b"only new image")
    info = original.stat()
    calls = []
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(ioctl=lambda *args: 41))
    monkeypatch.setattr(image.os, "open", lambda *args: 901)
    monkeypatch.setattr(image.os, "close", lambda *args: None)
    monkeypatch.setattr(image.os, "fstat", lambda *args: info)
    monkeypatch.setattr(image.os, "mknod", lambda *args: None, raising=False)
    monkeypatch.setattr(image.os, "makedev", lambda *args: 0, raising=False)
    monkeypatch.setattr(image, "write", lambda path, body: path.write_text(json.dumps(body)))
    def run(argv):
        assert (tmp_path / "loop-attach-intent.json").is_file()
        calls.append(argv)
    monkeypatch.setattr(image, "run", run)
    checks = []
    def require(*args):
        checks.append(args)
        if len(checks) == 1 or not prove_owned:
            raise ValueError("injected ownership proof failure")
    monkeypatch.setattr(image, "require_loop", require)
    with pytest.raises(ValueError, match="injected"):
        image.attach_image(original, 902, tmp_path)
    assert any("--detach" in call for call in calls) is prove_owned
    assert calls[0] == ["/usr/sbin/losetup", "--partscan", loop, original]
    receipt = json.loads((tmp_path / "loop-attach-failure.json").read_text())
    assert (receipt["cleanup"] == "OWNED_LOOP_DETACH_REQUESTED") is prove_owned


def test_fat_source_masks_are_explicit_and_independent_of_service_umask():
    source = "24 23 259:1 / /source/boot ro,relatime - vfat /dev/nvme0n1p1 rw,fmask=0022,dmask=0022,codepage=437,iocharset=ascii,shortname=mixed,utf8,errors=remount-ro"
    settings = filesystems.fat_mount("/source/boot", source)
    flags = filesystems.fat_options(settings)
    assert {"uid=0", "gid=0", "fmask=0022", "dmask=0022", "utf8=1", "shortname=mixed"} <= set(flags)
    assert "fmask=0077" not in flags
    with pytest.raises(ValueError, match="option value"):
        filesystems.fat_options({**settings, "iocharset": "ascii,bind"})
    with pytest.raises(ValueError, match="showexec"):
        filesystems.fat_mount("/source/boot", source + ",showexec")


def test_capacity_is_measured_before_payload_copy_and_fails_closed(monkeypatch, tmp_path):
    database = sqlite3.connect(tmp_path / "inventory.sqlite")
    database.execute("CREATE TABLE entries(phase TEXT,tree TEXT,path TEXT,value TEXT)")
    database.execute("INSERT INTO entries VALUES ('baseline','root','unique-private-work',?)", (json.dumps({"source": [1, 2, stat.S_IFREG | 0o600, 100, 0, 0, 0, 0, 1]}),))
    database.commit()
    database.close()
    monkeypatch.setattr(capture.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="measured capacity"):
        capture.capacity_preflight(tmp_path, "baseline")
    receipt = json.loads((tmp_path / "baseline-capacity.json").read_text())
    assert receipt["result"] == "INSUFFICIENT_CAPACITY"
    assert receipt["source_private_bytes"] == 100
    assert not (tmp_path / "frozen").exists()


def test_namespace_rejects_arbitrary_phase_or_source_arguments():
    with pytest.raises(ValueError, match="no additional"):
        namespace.phase_arguments("compress", ["--command", "build"])
    with pytest.raises(ValueError, match="unknown or duplicate"):
        namespace.phase_arguments("baseline", ["--command", "build"] * 4)
    args = ["--layout", "/source/root/protected/layout.json", "--catalog", "/source/root/protected/catalog.json",
            "--file-index", "/source/root/protected/index.jsonl", "--catalog-sha256", "a" * 64]
    assert namespace.phase_arguments("baseline", args) == args
    args[1] = "/source/root/../etc/shadow"
    with pytest.raises(ValueError, match="canonical"):
        namespace.phase_arguments("baseline", args)


def test_native_package_lock_descriptors_are_held_through_phase_and_released(monkeypatch, tmp_path, portable_metadata):
    import sys
    locks = []
    for number in range(4):
        path = tmp_path / str(number)
        path.write_bytes(b"original lock bytes unchanged")
        locks.append(str(path))
    status, boot = tmp_path / "status", tmp_path / "boot-id"
    status.write_text("captured package database")
    boot.write_text("current-boot")
    real_path = Path
    def mapped(value):
        return status if str(value) == "/var/lib/dpkg/status" else boot if str(value) == "/proc/sys/kernel/random/boot_id" else real_path(value)
    monkeypatch.setattr(namespace, "Path", mapped)
    monkeypatch.setattr(namespace, "PACKAGE_LOCKS", locks)
    monkeypatch.setattr(namespace, "writer_states", lambda plan: {unit: "inactive" for unit in plan["application_writers"]})
    monkeypatch.setattr(namespace, "runtime_directories", lambda: {name: {"mode": 0o1777 if name == "tmp" else 0o755} for name in capture.RUNTIME})
    monkeypatch.setattr(namespace.subprocess, "check_output", lambda *args, **kwargs: "")
    # Hosted Linux runs as an unprivileged runner. Model only ownership of the
    # private fixture lock inodes; keep real descriptors, bytes and close checks.
    fixture_inodes = {(Path(name).stat().st_dev, Path(name).stat().st_ino) for name in locks}
    real_fstat = os.fstat
    def root_fixture_stat(descriptor):
        info = real_fstat(descriptor)
        if (info.st_dev, info.st_ino) not in fixture_inodes:
            return info
        fields = list(info)
        fields[4] = 0
        return os.stat_result(fields)
    monkeypatch.setattr(namespace.os, "fstat", root_fixture_stat)
    descriptors = []
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(LOCK_EX=1, LOCK_NB=4, lockf=lambda descriptor, flags: descriptors.append(descriptor)))
    with namespace.package_lockset({"package_writers": sorted(namespace.PACKAGE_UNITS)}) as proof:
        assert len(proof["locks"]) == 4 and len(descriptors) == 4
        assert proof["dpkg_status_sha256"] == capture.sha(status)
        for descriptor in descriptors:
            assert os.fstat(descriptor).st_size == len(b"original lock bytes unchanged")
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert all(Path(path).read_bytes() == b"original lock bytes unchanged" for path in locks)


@pytest.mark.skipif(os.name != "posix", reason="actual POSIX sticky mode and xattrs")
def test_premask_runtime_directory_metadata_survives_private_mask_defaults(tmp_path, monkeypatch):
    source, work = tmp_path / "host", tmp_path / "work"
    frozen = work / "frozen/root"
    source.mkdir()
    frozen.mkdir(parents=True)
    for name in capture.RUNTIME:
        (source / name).mkdir(mode=0o755)
        (frozen / name).mkdir(mode=0o700)
    (source / "tmp").chmod(0o1777)
    os.setxattr(source / "tmp", "user.capture-test", b"exact attribute")
    real_path = Path
    monkeypatch.setattr(namespace, "Path", lambda value: source if value == "/" else real_path(value))
    monkeypatch.setattr(namespace, "runtime_mounts", lambda mountinfo: None)
    rows = namespace.runtime_directories()
    capture.restore_runtime_directories(work, {"runtime_directories_before_mask": rows})
    assert (frozen / "tmp").stat().st_mode & 0o7777 == 0o1777
    assert os.getxattr(frozen / "tmp", "user.capture-test") == b"exact attribute"
    for name in capture.RUNTIME:
        original, restored = (source / name).stat(), (frozen / name).stat()
        assert (restored.st_uid, restored.st_gid, restored.st_mtime_ns) == (original.st_uid, original.st_gid, original.st_mtime_ns)


def test_runtime_exclusion_never_silently_discards_persistent_tmp():
    lines = [f"1 0 0:1 / /{name} rw - {kind} source rw" for name, kind in
             (("dev", "devtmpfs"), ("proc", "proc"), ("sys", "sysfs"), ("run", "tmpfs"), ("tmp", "tmpfs"))]
    namespace.runtime_mounts("\n".join(lines))
    with pytest.raises(ValueError, match="persistent"):
        namespace.runtime_mounts("\n".join(lines[:-1]))


def test_restore_verifier_uses_private_scratch_with_readonly_metadata_input(tmp_path, portable_metadata):
    tree, readonly, scratch = tmp_path / "tree", tmp_path / "metadata", tmp_path / "scratch"
    tree.mkdir()
    readonly.mkdir()
    scratch.mkdir()
    (tree / "file").write_bytes(b"exact actual file-only proof")
    manifest = readonly / "root.manifest.jsonl"
    capture.tree_manifest(tree, manifest)
    readonly.chmod(0o555)
    try:
        assert image.verify_tree(tree, manifest, scratch=scratch)["result"] == "PASS"
        assert [path.name for path in readonly.iterdir()] == [manifest.name]
    finally:
        readonly.chmod(0o755)


def test_new_filesystem_uuid_is_read_back_from_only_owned_loop_partition(monkeypatch, tmp_path):
    checks = []
    def partition(loop, number, image_path, descriptor):
        checks.append((loop, number, image_path, descriptor))
        return Path(loop + "p" + str(number))
    monkeypatch.setattr(image, "require_partition", partition)
    monkeypatch.setattr(image.subprocess, "check_output", lambda argv, **kwargs: "AABB-CCDD\n")
    assert image.verify_filesystem_identity("/dev/loop9", 1, tmp_path / "new-image", 10, "AABB-CCDD")["result"] == "PASS"
    assert checks == [("/dev/loop9", 1, tmp_path / "new-image", 10)]
    with pytest.raises(ValueError, match="UUID differs"):
        image.verify_filesystem_identity("/dev/loop9", 1, tmp_path / "new-image", 10, "wrong")


def test_readonly_filesystem_checks_reprove_each_loop_partition(monkeypatch, tmp_path):
    checked, commands = [], []
    def partition(loop, number, *args):
        checked.append(number)
        return Path(loop + "p" + str(number))
    monkeypatch.setattr(image, "require_partition", partition)
    monkeypatch.setattr(image, "run", lambda argv: commands.append(argv))
    assert image.check_unmounted_filesystems("/dev/loop9", tmp_path / "new-image", 10)["result"] == "PASS"
    assert checked == [1, 2]
    assert commands == [["/usr/sbin/fsck.vfat", "-n", Path("/dev/loop9p1")], ["/usr/sbin/e2fsck", "-f", "-n", Path("/dev/loop9p2")]]
