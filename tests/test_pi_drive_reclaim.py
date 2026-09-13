"""Lease fault tests model host controls; they do not claim Pi backup acceptance."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

import pi_drive_reclaim as lease


class Host:
    def __init__(self):
        self.clock = datetime(2026, 9, 13, 8, tzinfo=timezone.utc)
        self.boot_id = "11111111-1111-1111-1111-111111111111"
        self.setting = 60
        self.events = []
        self.alive = False
        self.terminal_state = False
        self.empty_group = True
        self.timer_failure = False
        self.stop_failure = False
        self.ingest = False

    def now(self): return self.clock
    def boot(self): return self.boot_id
    def value(self): return self.setting
    def controls(self): return "a" * 64
    def running(self): return self.alive
    def empty(self): return self.empty_group
    def terminal(self): return self.terminal_state
    def priority_active(self, **kwargs): return self.ingest

    def set_value(self, value):
        self.events.append(("set", value))
        self.setting = value

    def arm(self):
        self.events.append(("arm", self.setting))
        assert lease.load_current()["phase"] == "PREPARED"
        if self.timer_failure:
            raise ValueError("timer failed")

    def stop(self):
        self.events.append(("stop", self.setting))
        if self.stop_failure:
            raise ValueError("stop failed")
        self.terminal_state = True
        self.alive = False
        self.empty_group = True


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(lease, "STATE", tmp_path)
    monkeypatch.setattr(lease, "trusted", lambda *args, **kwargs: None)
    monkeypatch.setattr(lease, "fsync_directory", lambda: None)
    @contextmanager
    def locked():
        yield
    monkeypatch.setattr(lease, "locked", locked)
    return Host()


def test_arm_precedes_mutation_and_terminal_restores_create_once(state):
    record = lease.acquire(state)
    assert state.events == [("arm", 60), ("set", 0)]
    assert record["deadline"] == "2026-09-13T14:25:00+00:00"
    state.terminal_state = True
    result = lease.finish(state)
    assert result["result"] == "RESTORED" and state.setting == 60
    assert lease.finish(state) == {"result": "NO_LEASE"}
    assert len(list(lease.STATE.glob("*.restored.json"))) == 1
    assert (lease.STATE / (record["id"] + ".intent.json")).exists()
    assert (lease.STATE / (record["id"] + ".applied.json")).exists()


@pytest.mark.parametrize("setting", [0, 1, 20, 100])
def test_foreign_setting_never_adopted_or_overwritten(state, setting):
    state.setting = setting
    with pytest.raises(ValueError, match="unowned predecessor"):
        lease.acquire(state)
    assert state.events == [] and lease.load_current() is None


def test_failed_timer_never_changes_sysctl_and_stoppost_reconciles_intent(state):
    state.timer_failure = True
    with pytest.raises(ValueError, match="timer failed"):
        lease.acquire(state)
    assert state.setting == 60 and state.events == [("arm", 60)]
    assert lease.load_current()["phase"] == "PREPARED"
    state.terminal_state = True
    assert lease.finish(state)["result"] == "RESTORED"


def test_changed_predecessor_after_timer_arm_never_overwritten(state, monkeypatch):
    monkeypatch.setattr(state, "arm", lambda: setattr(state, "setting", 20))
    with pytest.raises(ValueError, match="changed before"):
        lease.acquire(state)
    assert state.setting == 20 and state.events == []
    state.terminal_state = True
    with pytest.raises(ValueError, match="outside"):
        lease.finish(state)
    assert lease.load_current() is not None


def test_priority_ingest_defers_before_ownership_or_sysctl_mutation(state):
    state.ingest = True
    with pytest.raises(ValueError, match="priority ingest"):
        lease.acquire(state)
    assert lease.load_current() is None and state.setting == 60 and state.events == []


def test_ingest_appearing_during_arm_defers_without_zero(state, monkeypatch):
    monkeypatch.setattr(state, "arm", lambda: setattr(state, "ingest", True))
    with pytest.raises(ValueError, match="appeared"):
        lease.acquire(state)
    assert state.setting == 60 and state.events == []


def test_actual_ingest_during_backup_stops_only_backup_and_restores(state):
    lease.acquire(state)
    state.alive = True
    state.ingest = True
    assert lease.reconcile(state)["result"] == "RESTORED"
    assert state.events[-2:] == [("stop", 0), ("set", 60)]


def test_second_acquisition_never_replaces_live_owner(state):
    before = lease.acquire(state)
    with pytest.raises(ValueError, match="existing reclaim lease"):
        lease.acquire(state)
    assert lease.load_current() == before and state.setting == 0


def test_expiry_stops_before_restoration_and_failed_stop_stays_pending(state):
    lease.acquire(state)
    state.clock += timedelta(hours=8)
    state.alive = True
    state.empty_group = False
    state.stop_failure = True
    with pytest.raises(ValueError, match="stop failed"):
        lease.reconcile(state)
    assert state.setting == 0 and lease.load_current()["phase"] == "RESTORING"
    state.stop_failure = False
    assert lease.reconcile(state)["result"] == "RESTORED"
    assert state.events[-2:] == [("stop", 0), ("set", 60)]


@pytest.mark.parametrize("terminal,empty", [(False, True), (True, False)])
def test_live_dependency_or_descendants_block_terminal_restore(state, terminal, empty):
    lease.acquire(state)
    state.terminal_state, state.empty_group = terminal, empty
    with pytest.raises(ValueError, match="still|while backup"):
        lease.finish(state)
    assert state.setting == 0 and lease.load_current() is not None


def test_active_backup_and_start_grace_are_preserved_orphan_is_stopped(state):
    lease.acquire(state)
    assert lease.reconcile(state)["result"] == "LEASE_ACTIVE"
    state.clock += timedelta(seconds=61)
    state.alive = True
    assert lease.reconcile(state)["result"] == "LEASE_ACTIVE"
    state.alive = False
    assert lease.reconcile(state)["result"] == "RESTORED"
    assert state.events[-2:] == [("stop", 0), ("set", 60)]


@pytest.mark.parametrize("setting,success", [(60, True), (0, False), (20, False)])
def test_reboot_only_reconciles_original_setting_without_adopting_new_zero(state, setting, success):
    lease.acquire(state)
    state.boot_id = "22222222-2222-2222-2222-222222222222"
    state.setting = setting
    if success:
        assert lease.reconcile(state)["result"] == "RESTORED"
    else:
        with pytest.raises(ValueError, match="reboot|outside"):
            lease.reconcile(state)
        assert lease.load_current() is not None
    assert state.setting == setting


def test_old_cleanup_cannot_restore_a_new_owner(state):
    old = lease.acquire(state)
    state.terminal_state = True
    lease.finish(state)
    newer = lease.acquire(state)
    assert lease.finish(state, old["id"])["result"] == "SUPERSEDED"
    assert lease.load_current()["id"] == newer["id"] and state.setting == 0


def test_application_receipt_failure_retains_owned_zero_for_stoppost(state, monkeypatch):
    write = lease.write_json
    def fail(name, value, **kwargs):
        if name.endswith(".applied.json"):
            raise OSError("receipt write")
        return write(name, value, **kwargs)
    monkeypatch.setattr(lease, "write_json", fail)
    with pytest.raises(OSError, match="receipt write"):
        lease.acquire(state)
    assert lease.load_current()["phase"] == "ACTIVE" and state.setting == 0
    state.terminal_state = True
    assert lease.finish(state)["result"] == "RESTORED"


def test_restore_receipt_retry_keeps_original_receipt_and_clears_current(state, monkeypatch):
    record = lease.acquire(state)
    state.terminal_state = True
    original = Path.unlink
    def fail(path, *args, **kwargs):
        if path.name == "current.json":
            raise OSError("unlink fault")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(OSError, match="unlink fault"):
        lease.finish(state)
    receipt = lease.STATE / (record["id"] + ".restored.json")
    before = receipt.read_bytes()
    monkeypatch.setattr(Path, "unlink", original)
    assert lease.finish(state)["result"] == "RESTORED"
    assert receipt.read_bytes() == before and lease.load_current() is None


def test_changed_restore_readback_never_accepts_or_clears_ownership(state, monkeypatch):
    lease.acquire(state)
    state.terminal_state = True
    monkeypatch.setattr(state, "set_value", lambda _: setattr(state, "setting", 20))
    with pytest.raises(ValueError, match="readback changed"):
        lease.finish(state)
    assert lease.load_current() is not None and not list(lease.STATE.glob("*.restored.json"))


@pytest.mark.parametrize("minute", [0, 24, 25, 30, 209])
def test_pre_ingest_window_never_creates_lease(state, minute):
    state.clock = datetime(2026, 9, 13, 14, tzinfo=timezone.utc) + timedelta(minutes=minute)
    with pytest.raises(ValueError, match="before 03:30"):
        lease.acquire(state)
    assert state.events == [] and lease.load_current() is None


def test_maximum_twenty_hours_and_daylight_saving_cutoff():
    start = datetime(2026, 9, 12, 17, 30, tzinfo=timezone.utc)
    assert lease.deadline(start) == start + timedelta(hours=20)
    start = datetime(2026, 10, 3, 17, tzinfo=timezone.utc)  # DST has begun, local04:00.
    assert lease.deadline(start) == datetime(2026, 10, 4, 13, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("patch", [{"previous": 20}, {"phase": "OTHER"}, {"id": "../../x"}, {"deadline": None}])
def test_malformed_lease_fails_closed(state, patch):
    record = lease.acquire(state)
    (lease.STATE / "current.json").write_text(json.dumps({**record, **patch}))
    with pytest.raises(ValueError, match="invalid reclaim lease"):
        lease.reconcile(state)
    assert state.setting == 0


def test_installer_and_unit_privilege_boundary():
    root = Path(__file__).resolve().parents[1]
    backup = (root / "deploy/pi/ar-local-drive-backup.service").read_text()
    service = (root / "deploy/pi/ar-local-drive-reclaim.service").read_text()
    timer = (root / "deploy/pi/ar-local-drive-reclaim-reconcile.timer").read_text()
    installer = (root / "deploy/pi/install-drive-backup.sh").read_text()
    assert "Requires=ar-local-drive-reclaim.service" in backup
    assert "After=network-online.target ar-local-drive-reclaim.service" in backup
    for retained in ("User={{AR_LOCAL_USER}}", "MemorySwapMax=0", "NoNewPrivileges=true", "ProtectSystem=strict"):
        assert retained in backup
    assert "ExecStopPost=" in service and "StopWhenUnneeded=yes" in service
    assert "User=root" in service and "-I -B /usr/local/lib/" in service
    assert "OnUnitInactiveSec=30s" in timer and "OnBootSec=15s" in timer
    assert "systemctl enable --now ar-local-drive-reclaim-reconcile.timer" in installer
    assert "systemctl enable --now ar-local-drive-backup" not in installer
