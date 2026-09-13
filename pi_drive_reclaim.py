"""Root-installed, fixed-scope reclaim lease for the Pi Drive backup service.

This is a host control, not a backup acceptance receipt. Resource guards remain
authoritative; swappiness zero does not disable swap or guarantee no swap-out.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import time
import uuid
from zoneinfo import ZoneInfo

STATE = Path("/var/lib/ar-local-drive-reclaim")
HELPER = Path("/usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py")
PARAMETER = Path("/proc/sys/vm/swappiness")
BACKUP = "ar-local-drive-backup.service"
LEASE = "ar-local-drive-reclaim.service"
RECONCILE = "ar-local-drive-reclaim-reconcile.service"
TIMER = "ar-local-drive-reclaim-reconcile.timer"
CGROUP = Path("/sys/fs/cgroup/system.slice") / BACKUP
UNITS = Path("/etc/systemd/system")
DATA_LOCK = Path("/srv/ar-local/data/state/daily-ingest.lock")
INGEST_UNITS = ("ar-local-daily.service", "ar-local-ingest-now.service")
ADMISSION_UNITS = INGEST_UNITS + ("ar-local-daily-watchdog.service", "ar-local-boot-recovery.service")
UTC = timezone.utc


def trusted(path: Path, *, private: bool = False) -> None:
    info = path.lstat()
    if (info.st_uid != 0 or stat.S_ISLNK(info.st_mode)
            or info.st_mode & (0o077 if private else 0o022)
            or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
            or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
        raise ValueError("untrusted reclaim control: " + str(path))


def fsync_directory() -> None:
    descriptor = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json(name: str, value: dict, *, replace: bool = False) -> None:
    target = STATE / name
    data = (json.dumps(value, sort_keys=True) + "\n").encode()
    if replace:
        trusted(target, private=True)
    temporary = STATE / (".write-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)  # create-once, including retained receipts
            temporary.unlink()
        fsync_directory()
    finally:
        temporary.unlink(missing_ok=True)


def load_current() -> dict | None:
    path = STATE / "current.json"
    if not path.exists() and not path.is_symlink():
        return None
    trusted(path, private=True)
    if path.stat().st_size > 8192:
        raise ValueError("oversized reclaim lease")
    value = json.loads(path.read_text())
    try:
        identity = value["id"]
        valid_id = isinstance(identity, str) and uuid.UUID(hex=identity).hex == identity
        started = datetime.fromisoformat(value["started_at"])
        deadline = datetime.fromisoformat(value["deadline"])
        valid = (valid_id and value["version"] == 1 and value["previous"] == 60
                 and value["phase"] in {"PREPARED", "ACTIVE", "RESTORING"}
                 and uuid.UUID(value["boot_id"]) and started.utcoffset() == timedelta(0)
                 and deadline.utcoffset() == timedelta(0)
                 and timedelta(0) < deadline - started <= timedelta(hours=20)
                 and isinstance(value["controls_sha256"], str)
                 and len(value["controls_sha256"]) == 64
                 and all(c in "0123456789abcdef" for c in value["controls_sha256"]))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ValueError("invalid reclaim lease") from error
    if not valid:
        raise ValueError("invalid reclaim lease")
    return value


@contextmanager
def locked():
    import fcntl
    for parent in reversed(STATE.parents):
        trusted(parent)
    trusted(STATE, private=True)
    descriptor = os.open(STATE / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        trusted(STATE / "lock", private=True)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def command(*arguments: str) -> str:
    return subprocess.run(arguments, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=15,
                          env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}).stdout.strip()


def exact_action(value: str, action: str) -> bool:
    # systemctl's native single ExecCommand representation. Match the executable
    # and complete argv, not an occurrence of the script inside another command.
    match = re.fullmatch(r"\{ path=(\S+) ; argv\[\]=(.*?) ; ignore_errors=(yes|no)(?: ; [^{}]*)? \}", value)
    expected = f"/usr/bin/python3 -I -B {HELPER} {action}"
    return bool(match and match.groups() == ("/usr/bin/python3", expected, "no"))


class Host:
    def now(self):
        return datetime.now(UTC)

    def boot(self):
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()

    def value(self):
        return int(PARAMETER.read_text().strip())

    def set_value(self, value):
        PARAMETER.write_text(str(value) + "\n")
        if self.value() != value:
            raise ValueError("reclaim sysctl readback differs")

    def properties(self, unit):
        output = command("systemctl", "show", unit, "--property=LoadState,ActiveState,SubState,MainPID,Job,ControlGroup,ExecStart,User,UnitFileState,Unit,AccuracyUSec,RandomizedDelayUSec")
        result = {}
        for line in output.splitlines():
            if "=" not in line:
                raise ValueError("malformed effective systemd property")
            key, value = line.split("=", 1)
            if key in result:
                raise ValueError("multiple effective systemd property values")
            result[key] = value
        return result

    def controls(self):
        paths = [HELPER, UNITS / LEASE, UNITS / RECONCILE, UNITS / TIMER]
        digest = hashlib.sha256()
        for path in paths:
            for parent in reversed(path.parents):
                trusted(parent)
            trusted(path)
            digest.update(path.name.encode() + b"\0" + path.read_bytes())
        return digest.hexdigest()

    def arm(self):
        # Boot enablement gives a surviving lease a recovery path after reboot.
        command("systemctl", "start", TIMER)
        timer = self.properties(TIMER)
        service = self.properties(RECONCILE)
        if (timer.get("ActiveState") != "active" or timer.get("SubState") not in {"waiting", "running"}
                or timer.get("UnitFileState") != "enabled"
                or timer.get("Unit") != RECONCILE or timer.get("AccuracyUSec") != "1s"
                or timer.get("RandomizedDelayUSec") != "0"
                or service.get("User") != "root"
                or not exact_action(service.get("ExecStart", ""), "reconcile")):
            raise ValueError("independent reclaim timer is not armed")
        timers = command("systemctl", "show", TIMER, "--property=TimersMonotonic", "--value")
        if "OnUnitInactiveUSec=30s" not in timers or "OnBootUSec=15s" not in timers:
            raise ValueError("reclaim timer cadence differs")

    def empty(self):
        props = self.properties(BACKUP)
        if props.get("MainPID") != "0":
            return False
        actual = props.get("ControlGroup", "")
        if actual and actual != "/system.slice/" + BACKUP:
            raise ValueError("backup cgroup differs from fixed control")
        if CGROUP.exists():
            for path in CGROUP.rglob("cgroup.procs"):
                try:
                    if path.read_text().strip():
                        return False
                except FileNotFoundError:
                    pass  # A removed cgroup cannot retain tasks.
        return True

    def running(self):
        props = self.properties(BACKUP)
        return (props.get("ActiveState") in {"active", "activating", "deactivating"}
                or props.get("MainPID") != "0" or props.get("Job", "") not in {"", "0"})

    def terminal(self):
        return self.properties(LEASE).get("ActiveState") in {"inactive", "failed", "deactivating"}

    def priority_active(self, *, admission=False):
        units = ADMISSION_UNITS if admission else INGEST_UNITS
        for unit in units:
            props = self.properties(unit)
            if props.get("LoadState") == "not-found":
                continue
            if (props.get("ActiveState") not in {"inactive", "failed"}
                    or props.get("MainPID") != "0" or props.get("Job", "") not in {"", "0"}):
                return True
        if admission:
            return DATA_LOCK.exists() or DATA_LOCK.is_symlink()
        # The watchdog normally runs only a health check. Its service activation
        # is not proof of ingest; require its live child's existing lock record.
        return foreign_ingest(self.boot())

    def stop(self):
        # Do not hold the state flock here: ExecStopPost also restores the lease.
        command("systemctl", "stop", "--no-block", BACKUP, LEASE)
        end = time.monotonic() + 45
        while time.monotonic() < end:
            if self.terminal() and not self.running() and self.empty():
                return
            time.sleep(0.2)
        raise ValueError("backup did not stop within reclaim deadline cleanup budget")


def foreign_ingest(boot: str) -> bool:
    """Read-only positive evidence, never adopt/recover/write a producer lock."""
    descriptor = pidfd = None
    try:
        descriptor = os.open(DATA_LOCK, os.O_RDONLY | os.O_NOFOLLOW)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 4096:
            return False
        raw = os.read(descriptor, 4097).decode("ascii")
        rows = [line.split("=", 1) for line in raw.splitlines()]
        if any(len(row) != 2 for row in rows) or len({row[0] for row in rows}) != len(rows):
            return False
        fields = dict(rows)
        if fields.get("role") != "ingest" or fields.get("boot_id") != boot:
            return False
        pid = int(fields["pid"])
        if not 0 < pid <= 4194304:
            return False
        pidfd = os.pidfd_open(pid)
        poller = select.poll()
        poller.register(pidfd, select.POLLIN)
        with Path(f"/proc/{pid}/cgroup").open() as stream:
            membership = stream.read(4097)
        after = DATA_LOCK.stat(follow_symlinks=False)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        return (not poller.poll(0) and identity(before) == identity(after)
                and len(membership) <= 4096 and membership.startswith("0::/")
                and "\n" not in membership.strip()
                and membership.strip() != "0::/system.slice/" + BACKUP
                and not membership.startswith("0::/system.slice/" + BACKUP + "/"))
    except (OSError, ValueError, KeyError, AttributeError, UnicodeError):
        return False  # No positive foreign-ingest proof; worker locks still rule.
    finally:
        if pidfd is not None:
            os.close(pidfd)
        if descriptor is not None:
            os.close(descriptor)


def deadline(now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo("Australia/Hobart"))
    minute = local.hour * 60 + local.minute
    if minute < 210:  # Also avoids starting a lease just before the quiet window.
        raise ValueError("backup reclaim lease unavailable before 03:30 Hobart")
    cutoff = (local + timedelta(days=1)).replace(hour=0, minute=25, second=0, microsecond=0)
    return min(now + timedelta(hours=20), cutoff.astimezone(UTC))


def acquire(host: Host):
    with locked():
        if load_current() is not None:
            raise ValueError("existing reclaim lease requires reconciliation")
        if host.priority_active(admission=True):
            raise ValueError("priority ingest or production lock is active")
        if host.value() != 60:
            raise ValueError("reclaim lease requires unowned predecessor swappiness 60")
        now = host.now()
        record = {"version": 1, "id": uuid.uuid4().hex, "phase": "PREPARED",
                  "started_at": now.isoformat(), "deadline": deadline(now).isoformat(),
                  "boot_id": host.boot(), "previous": 60, "controls_sha256": host.controls()}
        write_json("current.json", record)
        write_json(record["id"] + ".intent.json", record)
        host.arm()
        if host.priority_active(admission=True):
            raise ValueError("priority ingest appeared before reclaim application")
        if host.value() != record["previous"]:
            raise ValueError("swappiness changed before reclaim lease application")
        host.set_value(0)
        record["phase"] = "ACTIVE"
        write_json("current.json", record, replace=True)
        write_json(record["id"] + ".applied.json", record)
        return record


def finish(host: Host, expected_id: str | None = None):
    with locked():
        record = load_current()
        if record is None:
            return {"result": "NO_LEASE"}
        if expected_id is not None and record["id"] != expected_id:
            return {"result": "SUPERSEDED", "id": expected_id}
        if not host.terminal() or not host.empty():
            raise ValueError("cannot restore reclaim lease while backup or dependency is live")
        current = host.value()
        if current not in {0, record["previous"]}:
            raise ValueError("swappiness changed outside reclaim lease")
        if record["boot_id"] != host.boot() and current != record["previous"]:
            raise ValueError("cannot attribute changed swappiness after reboot")
        if current != record["previous"]:
            host.set_value(record["previous"])
        readback = host.value()
        if readback != record["previous"]:
            raise ValueError("restoration readback changed before receipt")
        receipt = {**record, "result": "RESTORED", "readback": readback,
                   "restored_at": host.now().isoformat(), "restored_boot_id": host.boot()}
        path = STATE / (record["id"] + ".restored.json")
        if not path.exists():
            write_json(path.name, receipt)
        else:
            trusted(path, private=True)
            old = json.loads(path.read_text())
            binding = ("id", "previous", "boot_id", "started_at", "deadline", "controls_sha256")
            if (any(old.get(key) != record[key] for key in binding)
                    or old.get("result") != "RESTORED" or old.get("readback") != 60):
                raise ValueError("existing restoration receipt differs")
        (STATE / "current.json").unlink()
        fsync_directory()
        return receipt


def reconcile(host: Host):
    with locked():
        record = load_current()
        if record is None:
            return {"result": "NO_LEASE"}
        now = host.now()
        due = (record["boot_id"] != host.boot() or now >= datetime.fromisoformat(record["deadline"])
               or host.priority_active()
               or record["phase"] == "RESTORING"
               or (now - datetime.fromisoformat(record["started_at"]) >= timedelta(seconds=60)
                   and not host.running()))
        if not due:
            return {"result": "LEASE_ACTIVE", "id": record["id"]}
        record["phase"] = "RESTORING"
        write_json("current.json", record, replace=True)
    host.stop()
    return finish(host, record["id"])


def record_failure(host: Host, action: str, error: BaseException) -> None:
    """Keep first evidence and bounded latest/count state for each lease/action."""
    with locked():
        try:
            current = load_current()
        except (OSError, ValueError, TypeError):
            current = None  # Malformed ownership still fails; never invent an ID.
        identity = current["id"] if current is not None else "unattributed"
        prefix = identity + "." + action
        first = STATE / (prefix + ".failure.json")
        latest = STATE / (prefix + ".failure-latest.json")
        value = {"result": "FAIL", "command": action, "lease_id": current["id"] if current else None,
                 "at": host.now().isoformat(), "error_type": type(error).__name__, "reason": str(error)[:512]}
        if not first.exists() and not first.is_symlink():
            write_json(first.name, value)
        trusted(first, private=True)
        if first.stat().st_size > 8192:
            raise ValueError("oversized first reclaim failure")
        first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
        count = 0
        if latest.exists() or latest.is_symlink():
            trusted(latest, private=True)
            if latest.stat().st_size > 8192:
                raise ValueError("oversized latest reclaim failure")
            previous = json.loads(latest.read_text())
            count = previous.get("attempts")
            if (type(count) is not int or count < 1 or previous.get("first_sha256") != first_hash
                    or previous.get("command") != action or previous.get("lease_id") != value["lease_id"]):
                raise ValueError("reclaim failure summary binding differs")
        write_json(latest.name, {**value, "attempts": count + 1, "first_sha256": first_hash}, replace=count > 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("acquire", "finish", "reconcile"))
    arguments = parser.parse_args()
    if os.geteuid() != 0 or Path(__file__).resolve() != HELPER:
        raise ValueError("reclaim control requires its fixed root-installed entrypoint")
    os.umask(0o077)
    host = Host()
    host.controls()
    try:
        result = globals()[arguments.command](host)
    except BaseException as error:
        # Retain a safe, immutable control failure without masking its exception.
        try:
            record_failure(host, arguments.command, error)
        except BaseException:
            pass
        raise
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
