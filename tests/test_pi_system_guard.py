"""Pure admission/effect tests; no Pi, process signalling, mount or Drive writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_system_guard_entry as entry
import pi_system_guard_install as installer
import pi_system_guard_plan as service
import pi_system_guard_policy as policy
import pi_system_guard_writers as writers
import pi_system_guard_host as linux
import pi_system_drive_transport as transport

NONCE = "a" * 32
NOW = datetime(2026, 10, 24, 7, tzinfo=timezone.utc)


def packet(phase="PROBE"):
    value = {"schema": "ar-local-system-recovery-packet-v1", "manual_system_recovery": True, "phase": phase,
             "mode": "PROBE" if phase == "PROBE" else "RUN_ARCHIVE", "nonce": NONCE, "workspace_id": "b" * 32,
             "unit": "ar-local-plain-backup-" + NONCE + ".service", "uid": 1000, "gid": 1000,
             "created_at": NOW.isoformat(), "expires_at": (NOW + timedelta(seconds=120)).isoformat()}
    for key in ("source_closure_sha256", "queue_closure_sha256", "parent_sha256", "resources_sha256", "broker_sha256", "bwrap_sha256",
                "setpriv_sha256", "backend_approval_sha256", "queue_argv_sha256", "reconcile_registry_sha256", "reconcile_wrapper_sha256", "global_hold_sha256", "sudo_sha256"):
        value[key] = "c" * 64
    return value


def test_image_service_fixed_root_helper_and_plain_whitelist_unchanged():
    plan = service.service_plan(NONCE, "build")
    assert plan["argv"][-7:] == ["--", "/usr/bin/python3", "-I", "-S", "-B", service.ROOT + "/parent.py", NONCE]
    assert plan["properties"]["ExecStopPost"] == "+/usr/bin/python3 -I -S -B " + service.ROOT + "/broker.py recover " + NONCE
    assert plan["properties"]["RuntimeMaxSec"] == "21600"
    assert all(item.split()[-2] != "recover" for item in plan["sudoers_exact_commands"])
    import pi_plain_backup_core as plain
    with pytest.raises(plain.Blocked):
        plain.validate_packet(packet(), NONCE, NOW)


@pytest.mark.parametrize("field,value", [("nonce", "x"), ("phase", "shell"), ("mode", "ROOT"), ("uid", 0), ("manual_system_recovery", False), ("global_hold_sha256", "")])
def test_image_packet_rejects_scope_or_binding_change(field, value):
    body = packet()
    body[field] = value
    with pytest.raises(policy.Blocked):
        policy.validate(body, NONCE, NOW)


def test_quiet_window_cannot_be_crossed_with_both_endpoints_outside():
    body = packet("baseline")
    start = datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc)  # Hobart00:00.
    body.update(created_at=start.isoformat(), expires_at=(start + timedelta(hours=4)).isoformat())
    with pytest.raises(policy.Blocked, match="quiet"):
        policy.validate(body, NONCE, start)


def test_image_upload_requires_both_specific_write_and_sealed_objects():
    body = packet("upload")
    with pytest.raises(policy.Blocked, match="write"):
        policy.validate(body, NONCE, NOW)
    body["manual_image_drive_write"] = True
    with pytest.raises(policy.Blocked, match="sealed"):
        policy.validate(body, NONCE, NOW)
    body.update(upload_plan_sha256="d" * 64, credential_sha256="e" * 64)
    policy.validate(body, NONCE, NOW)


class Host:
    def __init__(self, recheck_fail=False):
        self.saved, self.events, self.current, self.recheck_fail = None, [], 60, recheck_fail
    def packet(self, nonce): return packet()
    def now(self): return NOW
    def boot(self): return "same-boot"
    def intent(self, nonce): return self.saved
    def value(self): return self.current
    def admission(self, body): return {"unit": body["unit"]}
    def save_intent(self, nonce, value, create=False):
        self.events.append(("save", value["phase"], create))
        self.saved = deepcopy(value)
    def recheck(self, body, expected):
        if self.recheck_fail: raise policy.Blocked("changed admission")
    def set_value(self, value):
        assert self.saved["phase"] == "PREPARED" and self.saved["restore_required"]
        self.events.append(("set", value))
        self.current = value
    def write_handoff(self, body, expected): self.events.append(("handoff",))


def test_durable_prepared_ownership_precedes_temporary_zero():
    host = Host()
    assert policy.acquire(host, NONCE)["readback"] == 0
    assert host.events[:2] == [("save", "PREPARED", True), ("set", 0)]
    assert host.saved["phase"] == "ACTIVE"
    with pytest.raises(policy.Blocked, match="fresh"):
        policy.acquire(host, NONCE)


def test_admission_race_preserves_prepared_intent_without_policy_mutation():
    host = Host(recheck_fail=True)
    with pytest.raises(policy.Blocked, match="changed"):
        policy.acquire(host, NONCE)
    assert host.current == 60 and host.saved["phase"] == "PREPARED"
    assert host.events == [("save", "PREPARED", True)]


def test_install_and_bootstrap_exact_closures_agree():
    assert installer.ALIASES | installer.MODULES == entry.IMAGE_FILES
    assert installer.PLAIN_FILES == entry.PLAIN_FILES
    root = Path(__file__).resolve().parents[1]
    for name in installer.MODULES:
        assert (root / name).is_file()


def test_root_module_registry_exposes_only_verified_names_without_search_path(tmp_path, monkeypatch):
    import sys
    search = list(sys.path)
    monkeypatch.setattr(sys, "meta_path", list(sys.meta_path))
    trusted = tmp_path / "pi_system_verified.py"
    trusted.write_text("VALUE = 1")
    (tmp_path / "subprocess.py").write_text("raise RuntimeError('unreviewed')")
    entry.register_modules({str(trusted): trusted.read_bytes()})
    finder = sys.meta_path[0]
    assert finder.find_spec("pi_system_verified").origin == str(trusted)
    assert finder.find_spec("subprocess") is None
    assert finder.find_spec("pi_system_unreviewed") is None
    assert sys.path == search


def test_timestamp_valid_unapproved_pyc_cannot_replace_verified_source_snapshot(tmp_path, monkeypatch):
    import importlib
    import py_compile
    import sys
    monkeypatch.setattr(sys, "meta_path", list(sys.meta_path))
    name = "pi_system_cached_fixture"
    source = tmp_path / (name + ".py")
    source.write_bytes(b"VALUE = 'bad'\n")
    original = source.stat()
    cached = py_compile.compile(str(source), doraise=True)
    source.write_bytes(b"VALUE = 'new'\n")
    os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert Path(cached).is_file() and source.stat().st_size == original.st_size
    entry.register_modules({str(source): source.read_bytes()})
    try:
        loaded = importlib.import_module(name)
        assert loaded.VALUE == "new"
    finally:
        sys.modules.pop(name, None)


def test_callback_deadline_caps_subprocess_effects(monkeypatch):
    host = linux.ImageHost(NONCE)
    monkeypatch.setattr(linux.time, "monotonic", lambda: 100)
    host.deadline = 102.5
    assert host.remaining_timeout(30) == 2.5
    host.deadline = 100
    with pytest.raises(policy.Blocked, match="deadline"):
        host.remaining_timeout(30)


def test_controller_accepts_only_measured_setuid_sudo_matrix(monkeypatch):
    body, host = packet(), linux.ImageHost(NONCE)
    group = "/system.slice/" + body["unit"]
    sudo = {"pid": 123, "ppid": 100, "uids": [1000, 0, 0, 0], "gids": [0] * 4, "nnp": 0, "cgroup": group,
            "exe": str(Path("/usr/bin/sudo").resolve()),
            "argv": ["/usr/bin/sudo", "-n", "/usr/bin/python3", "-I", "-S", "-B", str(linux.ROOT / "broker.py"), "acquire", NONCE]}
    parent = {"pid": 100, "ppid": 99, "uids": [1000] * 4, "gids": [1000] * 4, "nnp": 0, "cgroup": group,
              "argv": ["/usr/bin/python3", "-I", "-S", "-B", str(linux.ROOT / "parent.py"), NONCE]}
    monkeypatch.setattr(linux.os, "getppid", lambda: 123)
    monkeypatch.setattr(host, "process_identity", lambda pid: deepcopy(sudo if pid == 123 else parent))
    monkeypatch.setattr(linux, "digest", lambda path: "c" * 64)
    accepted, intermediates = host._controller(body)
    assert accepted["pid"] == 100 and intermediates[0]["uids"] == [1000, 0, 0, 0]
    sudo["uids"] = [0] * 4
    with pytest.raises(policy.Blocked, match="ancestry"):
        host._controller(body)


def test_native_observer_failure_is_independent_of_resource_sampler():
    import pi_system_guard_resources as resources
    owner = {"owner_pid": 11, "owner_ticks": 12, "boot_id": "boot", "job_id": "job", "invocation": "invocation", "device": 2, "inode": 3}
    class Native:
        calls = 0
        def _job(self, body):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("native DBus observation failed")
            return {"pid": 11, "start_ticks": 12, "boot_id": "boot", "id": "job", "invocation_id": "invocation"}, {}
        def _lease(self, job): return SimpleNamespace(st_dev=2, st_ino=3)
        def value(self): return 0
    host = Native()
    observer = resources.NativeObserver(host, packet(), owner)
    try:
        assert observer.first.wait(1)
        observer.check()
        observer.thread.join(timeout=1)
        assert not observer.thread.is_alive()
        with pytest.raises(RuntimeError, match="DBus"):
            observer.check()
        assert host.native_timeout == 0.75
    finally:
        observer.close()


def writer_fixture(monkeypatch, tmp_path):
    state, events, saved = {"custom.service": "active", "custom.timer": "inactive"}, [], {}
    host = SimpleNamespace(private=tmp_path, boot=lambda: "same", remaining_timeout=lambda limit: min(limit, 4))
    plan = {"application_writers": ["custom.service"], "package_writers": ["custom.service", "custom.timer"],
            "restore_existing_writers": True, "restore_existing_timer_units": []}
    monkeypatch.setattr(writers, "plan_for", lambda body: plan)
    def save(path, body, **kwargs):
        saved.update(deepcopy(body))
        path.touch(exist_ok=True)
        events.append(("intent", body["phase"]))
    monkeypatch.setattr(writers, "atomic", save)
    monkeypatch.setattr(writers, "root_json", lambda path: deepcopy(saved))
    monkeypatch.setattr(writers.subprocess, "check_output", lambda argv, **kwargs: state[argv[2]] + "\n")
    def effect(argv, **kwargs):
        assert saved["phase"] in {"STOPPING", "RESTORING"}
        assert kwargs["timeout"] == 4
        events.append((argv[1], argv[2]))
        state[argv[2]] = "inactive" if argv[1] == "stop" else "active"
    monkeypatch.setattr(writers.subprocess, "run", effect)
    return host, plan, state, events


def test_original_writers_restore_exactly_with_durable_pre_stop_record(monkeypatch, tmp_path):
    host, plan, state, events = writer_fixture(monkeypatch, tmp_path)
    body = packet("finalize")
    writers.quiesce(host, body)
    assert events[:2] == [("intent", "STOPPING"), ("stop", "custom.service")]
    assert writers.restore(host, body) is True
    assert state == {"custom.service": "active", "custom.timer": "inactive"}
    assert writers.restore(host, body) is True
    assert events.count(("start", "custom.service")) == 1


def test_existing_active_timer_requires_exact_restore_authority(monkeypatch, tmp_path):
    host, _, state, events = writer_fixture(monkeypatch, tmp_path)
    state["custom.timer"] = "active"
    with pytest.raises(RuntimeError, match="timer"):
        writers.quiesce(host, packet("prepare"))
    assert not events


@pytest.mark.parametrize("unit", ["ar-local-daily.timer", "tailscaled.service", "ssh.service", "../danger.service"])
def test_natural_ingest_and_access_services_cannot_be_quiesced(unit):
    with pytest.raises(RuntimeError, match="cannot"):
        writers.active(unit, SimpleNamespace(remaining_timeout=lambda limit: limit))


class Store:
    def __init__(self): self.objects, self.writes = {}, []
    def verify(self, name, digest, size):
        if name not in self.objects: return None
        body = self.objects[name]
        if len(body) != size or hashlib.sha256(body).hexdigest() != digest: raise ValueError("existing bytes differ")
        return True
    def upload(self, name, source):
        assert name not in self.objects
        self.objects[name] = Path(source).read_bytes()
        self.writes.append(name)


def test_create_only_object_reuse_requires_complete_hash_readback(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(bytes(range(256)) * 10)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    store = Store()
    assert transport.put_verified(store, "object", source, expected, source.stat().st_size, lambda: None) == "CREATED_READBACK_VERIFIED"
    assert transport.put_verified(store, "object", source, expected, source.stat().st_size, lambda: None) == "REUSED_VERIFIED"
    assert store.writes == ["object"]
    store.objects["object"] = b"invalid"
    with pytest.raises(ValueError, match="existing"):
        transport.put_verified(store, "object", source, expected, source.stat().st_size, lambda: None)
    assert store.writes == ["object"]


@pytest.mark.parametrize("name", ["packs/" + "a" * 64 + "/archive.tar.zst", "system-images/../secret", "system-images/sets/" + "a" * 64 + "/root.part000001.tar.zst", "/dev/sda"])
def test_image_object_whitelist_cannot_write_raw_or_duplicate_os_archives(name):
    store = transport.ImageRclone.__new__(transport.ImageRclone)
    store.remote = "approved:plaintext-recovery"
    with pytest.raises(ValueError): store.path(name)


def test_incomplete_upload_plan_has_no_remote_mutation(tmp_path):
    store = Store()
    body = {"schema": "ar-local-system-image-upload-plan-v1", "recovery_set_sha256": "a" * 64,
            "raw_catalog_sha256": "b" * 64, "raw_restore_required": True, "objects": []}
    with pytest.raises(ValueError): transport.upload_plan(tmp_path, body, store, tmp_path, lambda: None)
    assert not store.writes


def test_complete_image_objects_readback_before_catalog_and_preserve_raw_requirement(tmp_path):
    root, work = tmp_path / "input", tmp_path / "scratch"
    root.mkdir()
    work.mkdir()
    body = b"independently verified recovery set bytes"
    identity = hashlib.sha256(body).hexdigest()
    prefix = "system-images/sets/" + identity + "/"
    rows = []
    for name in sorted(transport.METADATA | {"recovery-set.json", "recovery.img.part000001.zst"}):
        content = body if name == "recovery-set.json" else (name + " test-only content").encode()
        (root / name).write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        target = ("metadata/" + checksum + Path(name).suffix if name in transport.METADATA else
                  "frames/" + name if name.startswith("recovery.img") else name)
        rows.append({"source": name, "path": prefix + target, "sha256": checksum, "bytes": len(content)})
    plan = {"schema": "ar-local-system-image-upload-plan-v1", "recovery_set_sha256": identity,
            "raw_catalog_sha256": "b" * 64, "raw_restore_required": True, "objects": rows}
    store = Store()
    result = transport.upload_plan(root, plan, store, work, lambda: None)
    assert result["result"] == "IMAGE_OBJECTS_FULL_READBACK_VERIFIED" and result["raw_restore_required"] is True
    assert store.writes[-1] == result["catalog_path"]
    assert all(item["result"] == "CREATED_READBACK_VERIFIED" for item in result["objects"])
    bad = deepcopy(plan)
    bad["objects"][-1]["path"] = prefix + "metadata/" + "f" * 64 + ".json"
    unused = Store()
    with pytest.raises(ValueError, match="role"):
        transport.upload_plan(root, bad, unused, work, lambda: None)
    assert not unused.writes


def test_privileged_build_rejects_unapproved_caps_or_host_namespace(monkeypatch):
    host = linux.ImageHost(NONCE)
    body = packet("build")
    group = "/system.slice/" + body["unit"]
    command = ["/usr/bin/bwrap", "--", "/usr/bin/python3", "-E", "-s", "-S", "-B", "/code/pi_system_image.py"]
    import pi_system_guard_launch as launch
    monkeypatch.setattr(launch, "sandbox_command", lambda body: command)
    monitor = {"pid": 1, "mnt": 2, "user": 3}
    monkeypatch.setattr(host, "process_identity", lambda pid: {"namespaces": monitor})
    monkeypatch.setattr(linux, "identity", lambda pid: {"pid": 444, "ppid": 0, "cgroup": group})
    allowed = sum(1 << bit for bit in linux.BASE_CAPS | {21})
    item = {"pid": 445, "ppid": 444, "uids": [0] * 4, "gids": [0] * 4, "exe": str(Path("/usr/bin/python3").resolve()), "argv": command[2:], "cgroup": group,
            "namespaces": {"pid": 11, "mnt": 12, "user": 3}, "caps": {key: allowed for key in ("CapEff", "CapBnd", "CapPrm")}}
    memory = {"uid": 0, "nnp": 1}
    assert host.allowed_worker(item, memory, 444, body)
    item["caps"]["CapEff"] |= 1 << 22  # CAP_SYS_BOOT never belongs to backup.
    assert not host.allowed_worker(item, memory, 444, body)
    item["caps"]["CapEff"] = allowed
    item["namespaces"]["pid"] = 1
    assert not host.allowed_worker(item, memory, 444, body)
    item["namespaces"]["pid"] = 11
    assert not host.allowed_worker(item, {"uid": 0, "nnp": 0}, 444, body)


def test_upload_pi_requires_private_namespace_and_zero_caps(monkeypatch):
    host, body = linux.ImageHost(NONCE), packet("upload")
    group = "/system.slice/" + body["unit"]
    monkeypatch.setattr(host, "process_identity", lambda pid: {"namespaces": {"pid": 1, "mnt": 2, "user": 3}})
    monkeypatch.setattr(linux, "identity", lambda pid: {"pid": 444, "ppid": 0, "cgroup": group})
    item = {"pid": 445, "ppid": 444, "uids": [1000] * 4, "gids": [1000] * 4, "exe": "rclone", "cgroup": group, "namespaces": {"pid": 11, "mnt": 12, "user": 3}}
    good = {"uid": 1000, "nnp": 1, "capabilities": 0}
    assert host.allowed_worker(item, good, 444, body)
    assert not host.allowed_worker(item, {**good, "capabilities": 1}, 444, body)
    item["namespaces"]["mnt"] = 2
    assert not host.allowed_worker(item, good, 444, body)


def test_upload_uses_qualified_bwrap_inherited_fd_contract_and_exact_code_files():
    import pi_system_guard_launch as launch
    argv = launch.sandbox_command(packet("upload"))
    assert "--preserve-fds" not in argv  # Absent from the qualified Pi bwrap.
    assert "--no-new-privs" in argv and "--bounding-set=-all" in argv
    bindings = [argv[index + 1:index + 3] for index, value in enumerate(argv[:-2]) if value == "--ro-bind"]
    assert [str(launch.ROOT), "/code"] not in bindings
    assert {target for source, target in bindings if target.startswith("/code/")} == {
        "/code/pi_system_upload_worker.py", "/code/pi_system_drive_transport.py", "/code/pi_plain_backup_transport.py", "/code/pi_plain_backup_attestation.py"}


def test_offline_rejoin_launcher_exposes_only_new_image_and_readonly_inputs():
    import pi_system_image_rejoin_launch as launch
    argv = launch.command(Path("/approved"), Path("/private/new"), Path("/private/metadata"), Path("/private/raw"), "a" * 64)
    assert "/source/root" not in argv and "/dev/nvme0n1" not in argv and "/dev/sda" not in argv
    assert argv[-3:] == ["/code/pi_system_image_rejoin.py", "--recovery-set-sha256", "a" * 64]
    assert ["--ro-bind", str(Path("/private/raw")), "/restored-raw"] in [argv[index:index + 3] for index in range(len(argv))]
    assert ["--ro-bind", str(Path("/private/metadata")), "/input"] in [argv[index:index + 3] for index in range(len(argv))]


@pytest.mark.skipif(os.name != "posix", reason="actual POSIX umask and root ownership proof")
def test_directory_exact_mode_survives_service_umask_0077(tmp_path, monkeypatch):
    if os.geteuid() != 0: pytest.skip("native root custody test")
    from pi_system_guard_files import directory
    old = os.umask(0o077)
    try:
        path = tmp_path / "new-handoff"
        directory(path, 0o750)
        assert path.stat().st_mode & 0o777 == 0o750
        path.chmod(0o700)
        with pytest.raises(RuntimeError, match="existing"):
            directory(path, 0o750)
        assert path.stat().st_mode & 0o777 == 0o700
    finally:
        os.umask(old)
