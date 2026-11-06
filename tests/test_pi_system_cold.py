"""Generic-byte cold recovery and private-image custody tests; no Pi/Drive acceptance."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

import pi_system_cold as cold
import pi_system_cold_normalize as normalize
import pi_system_guard_cold as guard
import pi_system_guard_policy as policy
import pi_system_guard_host as host
import pi_system_capture as capture
import pi_system_image as image
from tests.test_pi_plain_backup_restore import make_recovery
from tests.test_pi_system_image_restore import fixture_set
from tests.test_pi_system_guard import packet, NONCE, NOW


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def cold_packet(phase="fetch"):
    value = packet(phase)
    value.update(cold_plan_sha256="d" * 64, cold_vendor={"zstandard/__init__.py": "e" * 64},
                 cold_vendor_sha256="f" * 64)
    if phase == "fetch":
        value.update(manual_image_drive_read=True, credential_sha256="1" * 64)
    else:
        value["previous_phase_nonce"] = "2" * 32
    if phase == "rejoin":
        value["recovery_set_sha256"] = "3" * 64
    return value


@pytest.mark.parametrize("phase", ["fetch", "restore", "rejoin"])
def test_cold_phases_require_independent_plan_vendor_and_actual_predecessor(phase):
    value = cold_packet(phase)
    policy.validate(value, NONCE, NOW)
    value["cold_plan_sha256"] = ""
    with pytest.raises(policy.Blocked, match="cold"):
        policy.validate(value, NONCE, NOW)


def test_cold_fetch_read_authority_never_implies_drive_write_or_missing_copy():
    value = cold_packet()
    value["manual_image_drive_write"] = True
    with pytest.raises(policy.Blocked, match="readonly"):
        policy.validate(value, NONCE, NOW)
    value.pop("manual_image_drive_write")
    value.pop("credential_sha256")
    with pytest.raises(policy.Blocked, match="readonly"):
        policy.validate(value, NONCE, NOW)


@pytest.mark.parametrize("phase", ["fetch", "restore", "rejoin"])
def test_cold_namespace_has_no_source_alias_or_physical_device_or_sibling_directory(phase):
    args = guard.command(cold_packet(phase))
    assert "/source/root" not in args and "/dev/sda" not in args and "/dev/nvme0n1" not in args
    assert "--preserve-fds" not in args
    assert str(guard.ROOT) not in args and str(guard.PLAIN / "source") not in args
    assert "--unshare-pid" in args and "--no-new-privs" in args
    if phase == "fetch":
        assert "--unshare-net" not in args and "/credential.conf" in args
        assert "--bounding-set=-all" in args and "CAP_SYS_ADMIN" not in args and "/dev/loop-control" not in args
    elif phase == "restore":
        assert "--unshare-net" in args and "/credential.conf" not in args and "/mirror" in args
        assert "--bounding-set=-all" in args and "CAP_SYS_ADMIN" not in args and "/dev/loop-control" not in args
    else:
        assert "CAP_SYS_ADMIN" in args and "/dev/loop-control" in args and "/restored-raw" in args
        assert "/code/pi_system_cold_normalize.py" in args


def test_independent_root_restorer_rejects_every_nonzero_capability(monkeypatch):
    value = cold_packet("restore")
    controller = host.ImageHost(NONCE)
    group = "/system.slice/" + value["unit"]
    command = guard.command(value)
    import pi_system_guard_launch as launch
    monkeypatch.setattr(launch, "sandbox_command", lambda packet: command)
    monkeypatch.setattr(controller, "process_identity", lambda pid: {"namespaces": {"pid": 1, "mnt": 2, "user": 3}})
    monkeypatch.setattr(host, "identity", lambda pid: {"pid": 444, "ppid": 0, "cgroup": group})
    item = {"pid": 445, "ppid": 444, "uids": [0] * 4, "gids": [0] * 4, "exe": str(Path("/usr/bin/python3").resolve()),
            "argv": command[command.index("/usr/bin/python3"):], "cgroup": group,
            "namespaces": {"pid": 11, "mnt": 12, "user": 3}, "caps": {key: 0 for key in ("CapEff", "CapBnd", "CapPrm", "CapAmb", "CapInh")}}
    assert controller.allowed_worker(item, {"uid": 0, "nnp": 1}, 444, value)
    for key in item["caps"]:
        item["caps"][key] = 1
        assert not controller.allowed_worker(item, {"uid": 0, "nnp": 1}, 444, value)
        item["caps"][key] = 0


def mirrors(tmp_path):
    raw_base, image_base = tmp_path / "raw-source", tmp_path / "image-source"
    raw_base.mkdir(); image_base.mkdir()
    raw, raw_catalog, values = make_recovery(raw_base)
    parts, recovery, body, image_bytes = fixture_set(image_base)
    raw_sha = sha(raw_catalog.read_bytes())
    body["catalog_sha256"] = raw_sha
    recovery.write_text(json.dumps(body))
    identity = sha(recovery.read_bytes())
    objects = {}
    rows = []
    from pi_system_drive_transport import METADATA
    for name in sorted(METADATA | {"recovery-set.json"} | {item["path"] for item in body["compressed_parts"]}):
        content = (parts / name).read_bytes() if (parts / name).exists() else ("GENERIC_TEST_ONLY " + name).encode()
        digest = sha(content)
        suffix = "frames/" + name if name.startswith("recovery.img.part") else "recovery-set.json" if name == "recovery-set.json" else "metadata/" + digest + Path(name).suffix
        remote = "system-images/sets/" + identity + "/" + suffix
        rows.append({"source": name, "path": remote, "sha256": digest, "bytes": len(content)})
        objects[remote] = content
    catalog = {"schema": "ar-local-offsite-system-image-v1", "recovery_set_sha256": identity, "objects": rows,
               "raw_catalog_sha256": raw_sha, "raw_restore_required": True, "boot_test": "NOT_TESTED"}
    catalog_bytes = json.dumps(catalog).encode()
    catalog_sha = sha(catalog_bytes)
    objects["system-images/catalogs/" + catalog_sha + ".json"] = catalog_bytes
    objects["catalogs/" + raw_sha + ".json"] = raw_catalog.read_bytes()
    for path in raw.rglob("*"):
        if path.is_file() and path != raw_catalog:
            objects[path.relative_to(raw).as_posix()] = path.read_bytes()
    plan = {"schema": "ar-local-system-cold-plan-v1", "raw_catalog_sha256": raw_sha, "raw_catalog_bytes": raw_catalog.stat().st_size,
            "image_catalog_sha256": catalog_sha, "image_catalog_bytes": len(catalog_bytes)}
    return objects, plan, values, image_bytes


def fake_read_transport(tmp_path, monkeypatch, objects):
    import pi_plain_backup_attestation as attestation
    from pi_plain_backup_transport import Rclone
    from pi_system_drive_transport import ImageRclone
    executable = tmp_path / "read-only-fixture-rclone"
    executable.write_bytes(b"never executed")
    calls = []
    class Store:
        config, root_folder_id, remote = Path("/readonly/fixture.conf"), "fixture-private-folder", "fixture:plaintext-recovery"
        def __init__(self, image): self.image, self.executable = image, str(executable)
        def path(self, relative):
            return (ImageRclone.path if self.image else Rclone.path)(self, relative)
    class Child:
        def __init__(self, argv, **kwargs):
            assert argv[3] == "cat" and "--count" in argv and "--bwlimit" in argv
            calls.append(argv)
            name = argv[4].split("plaintext-recovery/", 1)[1]
            self.stdout = io.BytesIO(objects[name][:int(argv[argv.index("--count") + 1])])
        def wait(self, **kwargs): return 0
        def poll(self): return 0
    monkeypatch.setattr(attestation, "protected_file", lambda path: None)
    monkeypatch.setattr(cold.subprocess, "Popen", Child)
    return Store(False), Store(True), calls


def test_actual_raw_sqlite_and_zstd_frames_cold_fetch_restore_and_resume(tmp_path, monkeypatch):
    objects, plan, original, image_bytes = mirrors(tmp_path)
    raw, image_store, calls = fake_read_transport(tmp_path, monkeypatch, objects)
    downloaded = tmp_path / "cold-download"
    downloaded.mkdir()
    result = cold.fetch(downloaded, plan, raw, image_store, lambda: None)
    assert result["cloud_writes"] is False and result["independent_root_restore"] == "REQUIRED"
    transfers = len(calls)
    cold.fetch(downloaded, plan, raw, image_store, lambda: None)
    assert len(calls) == transfers  # Reuse only independently rehashed whole objects.
    restored = tmp_path / "new-cold-restored"
    restored.mkdir()
    result = cold.restore(restored, downloaded, plan, lambda: None)
    assert result["result"] == "COLD_RAW_AND_IMAGE_RESTORED_VERIFIED" and result["raw_rejoin_required"] is True
    assert (restored / "image/recovery.img").read_bytes() == image_bytes
    assert (restored / "raw/data/state/control.sqlite-wal").read_bytes() == original["sqlite-original/data/state/control.sqlite-wal"]
    assert (restored / "raw/committed-view/state/control.sqlite").read_bytes() == original["data/state/control.sqlite"]
    assert result["boot_test"] == "NOT_TESTED" and result["cloud_writes"] is False


def test_root_restore_rechecks_objects_instead_of_accepting_pi_fetch_verdict(tmp_path, monkeypatch):
    objects, plan, _, _ = mirrors(tmp_path)
    raw, image_store, _ = fake_read_transport(tmp_path, monkeypatch, objects)
    downloaded = tmp_path / "cold-download"
    downloaded.mkdir()
    cold.fetch(downloaded, plan, raw, image_store, lambda: None)
    archive = next((downloaded / "raw/packs").rglob("archive.tar.zst"))
    archive.write_bytes(b"changed after Pi worker PASS")
    restored = tmp_path / "must-remain-empty"
    restored.mkdir()
    with pytest.raises(ValueError, match="SHA"):
        cold.restore(restored, downloaded, plan, lambda: None)
    assert not list(restored.iterdir()) and archive.read_bytes().startswith(b"changed")


def custody_fixture(tmp_path, monkeypatch):
    root = tmp_path / "new-offline-image"
    root.mkdir()
    monkeypatch.setattr(normalize, "IMAGE_ROOT", root)
    monkeypatch.setattr(normalize, "OWNER_UID", root.stat().st_uid)
    monkeypatch.setattr(normalize, "OWNER_GID", root.stat().st_gid)
    if not hasattr(os, "chown"):
        monkeypatch.setattr(os, "chown", lambda *a, **kw: None, raising=False)
    if not hasattr(os, "listxattr"):
        monkeypatch.setattr(os, "listxattr", lambda *a, **kw: [], raising=False)
    if os.name != "posix":
        original_utime = os.utime
        monkeypatch.setattr(os, "utime", lambda path, **kwargs: original_utime(path, **{key: value for key, value in kwargs.items() if key != "follow_symlinks"}))
    nonce = "a" * 32
    boot = tmp_path / "new-offline-boot"
    boot.mkdir()
    (boot / "cmdline.txt").write_text("console=tty1 root=PARTUUID=12345678-02 rootwait\n")
    monkeypatch.setattr(normalize, "BOOT_ROOT", boot)
    (root / "etc/sysctl.d").mkdir(parents=True)
    unit = "ar-local-plain-backup-" + nonce + ".service"
    job = {"id": "captured-owner", "unit": unit, "state": "running", "pid": 4242, "boot_id": "old-captured-boot",
           "start_ticks": 1234, "invocation_id": "c" * 32,
           "project": "ar-local", "resources": ["ar-local", "host"], "mode": "exclusive", "sequence": 7, "cpu_slots": 1,
           "max_duration_seconds": 120, "ready_since": NOW.isoformat()}
    queue = {"version": 1, "next_sequence": 8, "jobs": [job]}
    source_name = "/usr/local/lib/ar-local-system-recovery/broker.py"
    code = b"# exact captured approved source, never executed\n"
    closure = {source_name: sha(code)}
    closure_sha = sha(json.dumps(closure, sort_keys=True, separators=(",", ":")).encode())
    authority = {"schema": "ar-local-system-recovery-authority-v1", "nonce": nonce, "unit": unit, "phase": "finalize",
                 "mode": "RUN_ARCHIVE", "manual_system_recovery": True, "source_closure_sha256": closure_sha}
    source_packet = {**authority, "schema": "ar-local-system-recovery-packet-v1"}
    files = {normalize.QUEUE: json.dumps(queue).encode(), normalize.LEASE:
             b"pid=4242\nboot_id=old-captured-boot\nrole=shared-pi-host-task:captured-owner\nrecovery=manual\n",
             "var/lib/ar-local-system-recovery-control/" + nonce + "/intent.json":
             json.dumps({"nonce": nonce, "phase": "ACTIVE", "unit": unit, "source_closure_sha256": closure_sha, "identity":
                         {"owner_pid": 4242, "owner_ticks": 1234, "boot_id": job["boot_id"], "job_id": job["id"],
                          "unit": unit, "invocation": job["invocation_id"]}}).encode(),
             "var/lib/ar-local-system-recovery-control/" + nonce + "/packet.json": json.dumps(source_packet).encode(),
             "var/lib/ar-local-system-recovery-handoff/" + nonce + "/approval.json": json.dumps(authority).encode(),
             source_name.removeprefix("/"): code,
             "usr/local/lib/ar-local-system-recovery/root-control-manifest.json": json.dumps(closure).encode(),
             "usr/lib/systemd/system/systemd-sysctl.service": b"[Service]\nType=oneshot\nExecStart=/usr/lib/systemd/systemd-sysctl\n",
             "var/lib/ar-local-plain-backup-control/" + ("b" * 32) + "/intent.json": b'{"phase":"RESTORED","result":"PASS"}',
             "etc/unique-private-work": b"preserve unrelated unique data"}
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    manifest = tmp_path / "captured-root.manifest.jsonl"
    capture.tree_manifest(root, manifest)
    return root, manifest, files, nonce, job


def test_active_captured_claim_with_missing_workspace_is_retired_only_in_new_image(tmp_path, monkeypatch):
    from pi_shared_queue_policy import admission
    root, manifest, originals, nonce, old_job = custody_fixture(tmp_path, monkeypatch)
    candidate = {**old_job, "id": "fresh-recovery-job", "state": "waiting", "sequence": 8}
    assert admission(candidate, [old_job], NOW)[0] is False
    assert not (root / "var/lib/ar-local-system-recovery").exists()  # Capture workspace was excluded.
    expected = tmp_path / "normalized-root.manifest.jsonl"
    result = normalize.normalize(root, manifest, expected, "d" * 64)
    image.restore_metadata(root, expected)
    assert image.verify_tree(root, expected)["result"] == "PASS"
    queue = json.loads((root / normalize.QUEUE).read_bytes())
    assert queue == {"version": 1, "next_sequence": 8, "jobs": []}
    assert admission(candidate, queue["jobs"], NOW) == (True, "admitted")
    assert not (root / normalize.LEASE).exists()
    assert not (root / "var/lib/ar-local-system-recovery-control" / nonce).exists()
    audit = root / "var/lib/ar-local-recovery-normalization" / ("d" * 64)
    for name, raw in originals.items():
        if name.startswith("var/lib/ar-local-system-recovery-") or name == normalize.LEASE or name == normalize.QUEUE:
            assert (audit / "original" / name).read_bytes() == raw
        else:
            assert (root / name).read_bytes() == raw
    assert (root / "etc/unique-private-work").read_bytes() == originals["etc/unique-private-work"]
    receipt = json.loads((audit / "receipt.json").read_bytes())
    assert receipt["automatic_work_started"] is False and receipt["persistent_schedules"] == "UNCHANGED"
    assert receipt["persistent_boot_policy"]["original_path_state"] == "ABSENT"
    assert receipt["persistent_boot_policy"]["runtime_proc_value_used"] is False
    assert (root / normalize.BOOT_POLICY).read_text().endswith("vm.swappiness = 60\n")
    assert result["original_manifest_sha256"] == sha(manifest.read_bytes()) and result["boot_test"] == "NOT_TESTED"


def test_captured_custody_hash_change_refuses_before_any_normalization_write(tmp_path, monkeypatch):
    root, manifest, _, nonce, _ = custody_fixture(tmp_path, monkeypatch)
    path = root / "var/lib/ar-local-system-recovery-control" / nonce / "intent.json"
    value = json.loads(path.read_bytes())
    value["phase"] = "RESTORING"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="bytes differ"):
        normalize.normalize(root, manifest, tmp_path / "must-not-write.jsonl", "d" * 64)
    assert not (root / "var/lib/ar-local-recovery-normalization").exists()
    assert (root / normalize.LEASE).exists() and path.exists()


@pytest.mark.parametrize("change", ["foreign-lease", "owner-ticks", "source-code", "authority-closure", "boot-override", "persistent-override", "credential", "legacy-custody", "foreign-job-boot", "missing-job-boot"])
def test_ambiguous_cold_boot_custody_or_policy_refuses_before_transform(tmp_path, monkeypatch, change):
    root, manifest, _, nonce, _ = custody_fixture(tmp_path, monkeypatch)
    if change == "foreign-lease":
        path = root / normalize.LEASE
        path.write_bytes(path.read_bytes().replace(b"pid=4242", b"pid=9999"))
    elif change == "owner-ticks":
        path = root / normalize.QUEUE
        queue = json.loads(path.read_bytes()); queue["jobs"][0]["start_ticks"] += 1
        path.write_text(json.dumps(queue))
    elif change == "source-code":
        (root / "usr/local/lib/ar-local-system-recovery/broker.py").write_bytes(b"unapproved source")
    elif change == "authority-closure":
        path = root / "var/lib/ar-local-system-recovery-handoff" / nonce / "approval.json"
        value = json.loads(path.read_bytes()); value["source_closure_sha256"] = "0" * 64
        path.write_text(json.dumps(value))
    elif change == "boot-override":
        (normalize.BOOT_ROOT / "cmdline.txt").write_text("root=PARTUUID=12345678-02 sysctl.vm.swappiness=0\n")
    elif change == "persistent-override":
        (root / "etc/sysctl.d/99-custom.conf").write_text("vm.swappiness=0\n")
    elif change == "credential":
        (root / "etc/credstore").mkdir()
        (root / "etc/credstore/sysctl.extra").write_text("vm.swappiness=0\n")
    elif change == "legacy-custody":
        path = root / "var/lib/ar-local-drive-reclaim/current.json"
        path.parent.mkdir(); path.write_text('{"unknown":"preserve"}')
    else:
        path = root / normalize.QUEUE
        queue = json.loads(path.read_bytes())
        additional = {**queue["jobs"][0], "id": "other-captured-request", "state": "waiting"}
        if change == "foreign-job-boot": additional["boot_id"] = "foreign-boot"
        else: additional.pop("boot_id")
        queue["jobs"].append(additional); path.write_text(json.dumps(queue))
    # Even if the changed bytes belonged to the accepted source manifest, an
    # ambiguous owner/policy must not be normalized into an apparently clean OS.
    manifest.unlink(); capture.tree_manifest(root, manifest)
    with pytest.raises(ValueError):
        normalize.normalize(root, manifest, tmp_path / "must-not-transform.jsonl", "d" * 64)
    assert not (root / "var/lib/ar-local-recovery-normalization").exists()
    assert (root / normalize.LEASE).exists() and not (root / normalize.BOOT_POLICY).exists()
    if change == "legacy-custody":
        assert (root / "var/lib/ar-local-drive-reclaim/current.json").read_bytes() == b'{"unknown":"preserve"}'


def test_same_boot_waiting_requests_are_audited_without_fabricated_completion(tmp_path, monkeypatch):
    root, manifest, _, _, owner = custody_fixture(tmp_path, monkeypatch)
    path = root / normalize.QUEUE
    queue = json.loads(path.read_bytes())
    queue["jobs"].append({**owner, "id": "old-waiting", "state": "waiting"})
    queue["jobs"].append({**owner, "id": "old-quarantined", "state": "quarantined"})
    original = json.dumps(queue).encode(); path.write_bytes(original)
    manifest.unlink(); capture.tree_manifest(root, manifest)
    normalize.normalize(root, manifest, tmp_path / "normalized.jsonl", "d" * 64)
    audit = root / "var/lib/ar-local-recovery-normalization" / ("d" * 64)
    receipt = json.loads((audit / "receipt.json").read_bytes())
    assert len(receipt["retired_queue_jobs"]) == 3
    assert all(item["boot_id"] == owner["boot_id"] for item in receipt["retired_queue_jobs"])
    assert (audit / "original" / normalize.QUEUE).read_bytes() == original
    assert json.loads(path.read_bytes())["next_sequence"] == 8
    assert not any("result" in item for item in receipt["retired_queue_jobs"])


def test_cold_predecessor_requires_root_completion_resources_and_quarantined_copy(monkeypatch):
    value = cold_packet("restore")
    old = {**value, "nonce": value["previous_phase_nonce"], "phase": "fetch"}
    completion = {"schema": "ar-local-system-recovery-root-completion-v1", "nonce": old["nonce"], "unit": old["unit"],
                  "phase": "fetch", "result": "RESTORED", "resource_acceptance": "PASS", "stop_post_verified": True,
                  "readback": 60, "credential_custody": "QUARANTINED", "untrusted_processes_gone": True,
                  "owned_loop_terminal": True, "writers_restored": True,
                  **{key: value[key] for key in ("source_closure_sha256", "cold_plan_sha256", "cold_vendor_sha256",
                                                "root_control_manifest_sha256", "queue_closure_sha256")}}
    resources = {"schema": "ar-local-system-recovery-resources-v1", "phase": "fetch", "result": "PASS", "group_clean": True}
    lookup = {"packet.json": old, "completion.json": completion, "resources.json": resources}
    monkeypatch.setattr(guard, "protected", lambda path, **kwargs: json.dumps(lookup[path.name]).encode())
    guard.predecessor(value)
    for key, bad in (("credential_custody", "PRESENT"), ("stop_post_verified", False), ("readback", 0), ("cold_vendor_sha256", "0" * 64)):
        original = completion[key]; completion[key] = bad
        with pytest.raises(RuntimeError): guard.predecessor(value)
        completion[key] = original
    for key in ("root_control_manifest_sha256", "queue_closure_sha256"):
        original = completion[key]; completion[key] = "0" * 64
        with pytest.raises(RuntimeError): guard.predecessor(value)
        completion[key] = original
        original = old[key]; old[key] = "0" * 64
        with pytest.raises(RuntimeError): guard.predecessor(value)
        old[key] = original
    resources["group_clean"] = False
    with pytest.raises(RuntimeError): guard.predecessor(value)


@pytest.mark.parametrize("phase", ["PROBE", "baseline", "prepare", "finalize", "archive", "build", "compress", "restore", "rejoin"])
def test_image_admission_does_not_require_credentials_for_non_drive_phases(phase):
    controller = object.__new__(host.ImageHost)
    controller.check_staged_credential({"phase": phase})


@pytest.mark.parametrize("phase", ["upload", "fetch"])
def test_image_drive_admission_requires_bound_staged_credential(phase):
    controller = object.__new__(host.ImageHost)
    with pytest.raises(policy.Blocked, match="credential binding"):
        controller.check_staged_credential({"phase": phase})
