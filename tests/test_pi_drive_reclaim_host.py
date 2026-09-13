"""Filesystem and systemctl contract checks without privileged host mutations."""
import os
from pathlib import Path
import subprocess

import pytest

import pi_drive_reclaim as lease


def action(executable="/usr/bin/python3", argv=None, ignore="no"):
    argv = argv or f"/usr/bin/python3 -I -B {lease.HELPER} reconcile"
    return f"{{ path={executable} ; argv[]={argv} ; ignore_errors={ignore} ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0 }}"


def test_arm_reads_boot_enablement_cadence_and_exact_root_action_before_return(monkeypatch):
    calls = []
    def command(*args):
        calls.append(args)
        if args[1] == "start":
            return ""
        if "--property=TimersMonotonic" in args:
            return "{ OnBootUSec=15s ; next_elapse=15s }\n{ OnUnitInactiveUSec=30s ; next_elapse=2h }"
        if args[2] == lease.TIMER:
            return ("ActiveState=active\nSubState=waiting\nUnitFileState=enabled\n"
                    f"Unit={lease.RECONCILE}\nAccuracyUSec=1s\nRandomizedDelayUSec=0")
        return "User=root\nExecStart=" + action()
    monkeypatch.setattr(lease, "command", command)
    lease.Host().arm()
    assert calls[0] == ("systemctl", "start", lease.TIMER)
    assert len(calls) == 4


@pytest.mark.parametrize("field,value", [("ActiveState", "inactive"), ("UnitFileState", "disabled"),
                                        ("Unit", "ar-local-drive-backup.service"), ("AccuracyUSec", "1min"),
                                        ("RandomizedDelayUSec", "5min"), ("SubState", "failed")])
def test_unarmed_or_drifted_timer_is_refused(monkeypatch, field, value):
    timer = {"ActiveState": "active", "SubState": "waiting", "UnitFileState": "enabled",
             "Unit": lease.RECONCILE, "AccuracyUSec": "1s", "RandomizedDelayUSec": "0"}
    timer[field] = value
    monkeypatch.setattr(lease, "command", lambda *args: "")
    monkeypatch.setattr(lease.Host, "properties", lambda _, unit: timer if unit == lease.TIMER else {
        "User": "root", "ExecStart": action()})
    with pytest.raises(ValueError, match="not armed"):
        lease.Host().arm()


@pytest.mark.parametrize("value", [
    action("/usr/bin/true", f"/usr/bin/true {lease.HELPER} reconcile"),
    action("/usr/bin/echo", f"/usr/bin/echo {lease.HELPER} reconcile"),
    action(argv=f"/usr/bin/python3 -I -B {lease.HELPER} reconcile --other"),
    action(ignore="yes"), action() + " " + action(),
    f"/usr/bin/python3 -I -B {lease.HELPER} reconcile", "",
])
def test_effective_override_or_multiple_actions_never_arm(value, monkeypatch):
    assert lease.exact_action(value, "reconcile") is False
    timer = {"ActiveState": "active", "SubState": "waiting", "UnitFileState": "enabled",
             "Unit": lease.RECONCILE, "AccuracyUSec": "1s", "RandomizedDelayUSec": "0"}
    monkeypatch.setattr(lease, "command", lambda *args: "")
    monkeypatch.setattr(lease.Host, "properties", lambda _, unit: timer if unit == lease.TIMER else {
        "User": "root", "ExecStart": value})
    with pytest.raises(ValueError, match="not armed"):
        lease.Host().arm()


def test_repeated_execstart_property_lines_cannot_hide_an_earlier_command(monkeypatch):
    monkeypatch.setattr(lease, "command", lambda *args: "User=root\nExecStart=" +
                        action("/usr/bin/true", "/usr/bin/true") + "\nExecStart=" + action())
    with pytest.raises(ValueError, match="multiple effective"):
        lease.Host().properties(lease.RECONCILE)


def test_detached_descendant_blocks_empty_even_with_mainpid_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(lease, "CGROUP", tmp_path)
    monkeypatch.setattr(lease.Host, "properties", lambda *_: {
        "MainPID": "0", "ControlGroup": "/system.slice/" + lease.BACKUP})
    (tmp_path / "cgroup.procs").write_text("")
    child = tmp_path / "child"
    child.mkdir()
    (child / "cgroup.procs").write_text("345\n")
    assert lease.Host().empty() is False
    (child / "cgroup.procs").write_text("")
    assert lease.Host().empty() is True


def test_unexpected_cgroup_refused_instead_of_treating_expected_absence_as_empty(monkeypatch):
    monkeypatch.setattr(lease.Host, "properties", lambda *_: {"MainPID": "0", "ControlGroup": "/other"})
    with pytest.raises(ValueError, match="cgroup differs"):
        lease.Host().empty()


def test_stop_unconditionally_targets_only_both_fixed_units_without_lock(monkeypatch):
    commands = []
    monkeypatch.setattr(lease, "command", lambda *args: commands.append(args))
    monkeypatch.setattr(lease.Host, "terminal", lambda _: True)
    monkeypatch.setattr(lease.Host, "running", lambda _: False)
    monkeypatch.setattr(lease.Host, "empty", lambda _: True)
    lease.Host().stop()
    assert commands == [("systemctl", "stop", "--no-block", lease.BACKUP, lease.LEASE)]


def test_watchdog_health_activation_is_admission_busy_but_does_not_stop_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(lease, "DATA_LOCK", tmp_path / "daily-ingest.lock")
    monkeypatch.setattr(lease, "foreign_ingest", lambda _: False)
    monkeypatch.setattr(lease.Host, "boot", lambda _: "test-boot")
    def props(_, unit):
        return {"LoadState": "loaded", "ActiveState": "activating" if "watchdog" in unit else "inactive",
                "MainPID": "123" if "watchdog" in unit else "0", "Job": "0"}
    monkeypatch.setattr(lease.Host, "properties", props)
    assert lease.Host().priority_active(admission=True)
    assert lease.Host().priority_active() is False


def test_any_existing_lock_blocks_admission_without_reading_or_changing_it(tmp_path, monkeypatch):
    path = tmp_path / "daily-ingest.lock"
    path.write_text("private-owner-record")
    monkeypatch.setattr(lease, "DATA_LOCK", path)
    monkeypatch.setattr(lease.Host, "properties", lambda *_: {"LoadState": "not-found"})
    assert lease.Host().priority_active(admission=True)
    assert path.read_text() == "private-owner-record"


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "pidfd_open"), reason="real Linux pidfd ownership proof")
def test_foreign_ingest_proof_uses_live_pidfd_same_boot_and_role(tmp_path, monkeypatch):
    path = tmp_path / "daily-ingest.lock"
    monkeypatch.setattr(lease, "DATA_LOCK", path)
    boot = lease.Host().boot()
    def write(role="ingest", recorded_boot=None):
        path.write_text(f"pid={os.getpid()}\nrole={role}\nboot_id={recorded_boot or boot}\n")
    write()
    original = path.read_bytes()
    assert lease.foreign_ingest(boot)
    assert path.read_bytes() == original
    write("drive-backup-freeze")
    assert lease.foreign_ingest(boot) is False
    write(recorded_boot="other-boot")
    assert lease.foreign_ingest(boot) is False
    path.write_text("pid=not-a-number\nrole=ingest\nboot_id=" + boot)
    assert lease.foreign_ingest(boot) is False


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "pidfd_open"), reason="real Linux completed-owner proof")
def test_completed_ingest_owner_is_not_live_priority_evidence(tmp_path, monkeypatch):
    import sys
    path = tmp_path / "daily-ingest.lock"
    monkeypatch.setattr(lease, "DATA_LOCK", path)
    boot = lease.Host().boot()
    with subprocess.Popen([sys.executable, "-c", "pass"]) as child:
        child.wait(timeout=5)
        path.write_text(f"pid={child.pid}\nrole=ingest\nboot_id={boot}\n")
        assert lease.foreign_ingest(boot) is False


def test_stop_deadline_remains_bounded_with_living_descendant(monkeypatch):
    monkeypatch.setattr(lease, "command", lambda *args: "")
    monkeypatch.setattr(lease.Host, "terminal", lambda _: True)
    monkeypatch.setattr(lease.Host, "running", lambda _: False)
    monkeypatch.setattr(lease.Host, "empty", lambda _: False)
    ticks = iter([0, 0, 44, 46])
    monkeypatch.setattr(lease.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(lease.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="cleanup budget"):
        lease.Host().stop()


def test_fixed_command_environment_does_not_inherit_python_or_credentials(monkeypatch):
    recorded = {}
    def run(args, **kwargs):
        recorded.update(args=args, **kwargs)
        return subprocess.CompletedProcess(args, 0, "active\n")
    monkeypatch.setattr(lease.subprocess, "run", run)
    assert lease.command("systemctl", "show", lease.BACKUP) == "active"
    assert recorded["timeout"] == 15 and recorded["check"] is True
    assert recorded["env"] == {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and O_NOFOLLOW contract")
def test_real_private_state_lock_rejects_symlink_and_serializes_another_descriptor(tmp_path, monkeypatch):
    import fcntl
    monkeypatch.setattr(lease, "STATE", tmp_path)
    # CI is unprivileged; only root UID validation is replaced, while actual
    # flock/O_NOFOLLOW/fsync/create-once operations run on temporary files.
    monkeypatch.setattr(lease, "trusted", lambda *args, **kwargs: None)
    with lease.locked():
        with (tmp_path / "lock").open("rb") as stream:
            with pytest.raises(BlockingIOError):
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lease.write_json("receipt.json", {"result": "TEST"})
        with pytest.raises(FileExistsError):
            lease.write_json("receipt.json", {"result": "OVERWRITE"})
    (tmp_path / "lock").unlink()
    (tmp_path / "lock").symlink_to(tmp_path / "receipt.json")
    with pytest.raises(OSError):
        with lease.locked():
            pytest.fail("followed lock symlink")


@pytest.mark.skipif(os.name != "posix", reason="POSIX file mode contract")
def test_real_private_record_rejects_group_access_and_hardlinks(tmp_path, monkeypatch):
    path = tmp_path / "record"
    path.write_text("{}")
    # Root ownership itself is checked independently by trusted; CI runs as an
    # ordinary UID, so use the current UID in this controlled stat result.
    actual = Path.lstat
    def root_stat(value):
        info = actual(value)
        return type("Info", (), {"st_uid": 0, "st_mode": info.st_mode, "st_nlink": info.st_nlink})()
    monkeypatch.setattr(Path, "lstat", root_stat)
    path.chmod(0o640)
    with pytest.raises(ValueError, match="untrusted"):
        lease.trusted(path, private=True)
    path.chmod(0o600)
    lease.trusted(path, private=True)
    os.link(path, tmp_path / "other")
    with pytest.raises(ValueError, match="untrusted"):
        lease.trusted(path, private=True)
