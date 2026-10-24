"""Image-specific root effects; reuse queue custody and restoration, not plain dispatch."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import stat
import subprocess
import struct
import time

from pi_plain_backup_linux import Host as PlainHost, atomic, digest, identity
from pi_plain_backup_core import Blocked
from pi_shared_queue_post_hooks import approval, root_json, verify_plain_service

ROOT = Path("/usr/local/lib/ar-local-system-recovery")
STATE = Path("/var/lib/ar-local-system-recovery-control")
HANDOFF = Path("/var/lib/ar-local-system-recovery-handoff")
WORK = Path("/var/lib/ar-local-system-recovery")
PLAIN = Path("/usr/local/lib/ar-local-plain-backup")
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", "HOME": "/root"}
BASE_CAPS = {0, 1, 2, 3, 4, 27, 31}  # CHOWN,DAC_OVERRIDE,DAC_READ_SEARCH,FOWNER,FSETID,MKNOD,SETFCAP
SHOW_FIELDS = "Id,LoadState,ActiveState,SubState,MainPID,ControlPID,InvocationID,ControlGroup,User,NoNewPrivileges,Type,KillMode,NeedDaemonReload,CPUQuotaPerSecUSec,TasksMax,IOWeight,RuntimeMaxUSec"
TOOLS = {"baseline": {"rsync"}, "prepare": {"rsync"}, "finalize": {"rsync"},
         "archive": {"zstd"}, "compress": {"zstd"},
         "build": {"losetup", "mkfs.vfat", "mkfs.ext4", "blkid", "mount", "umount", "tar", "zstd", "fsck.vfat", "e2fsck"}}


class ImageHost(PlainHost):
    def __init__(self, nonce):
        super().__init__(nonce)
        self.private, self.public = STATE / nonce, HANDOFF / nonce
        self.deadline = None
        self.native_timeout = 10

    def remaining_timeout(self, limit):
        remaining = limit if self.deadline is None else min(limit, self.deadline - time.monotonic())
        if remaining <= 0:
            raise Blocked("bounded image recovery effect deadline reached")
        return remaining

    def _show(self, unit):
        from pi_plain_backup_linux import pairs
        fields = SHOW_FIELDS
        result = subprocess.run(["/usr/bin/systemctl", "show", unit, "--no-pager", "--property=" + fields],
                                capture_output=True, text=True, timeout=self.remaining_timeout(self.native_timeout), env=ENV)
        value = pairs(line.split("=", 1) for line in result.stdout.splitlines() if line)
        if set(value) != set(fields.split(",")) or value["Id"] != unit:
            raise Blocked("incomplete native image service identity")
        if result.returncode and not (result.returncode == 1 and value["LoadState"] == "not-found"):
            raise Blocked("native image service identity unavailable")
        return value

    def _controller(self, packet):
        current, intermediates = os.getppid(), []
        expected = ["/usr/bin/python3", "-I", "-S", "-B", str(ROOT / "parent.py"), self.nonce]
        for _ in range(4):
            item = self.process_identity(current)
            if item["cgroup"] != "/system.slice/" + packet["unit"]:
                raise Blocked("image control ancestry escaped native cgroup")
            if item["argv"] == expected:
                if (item["uids"] != [packet["uid"]] * 4 or item["gids"] != [packet["gid"]] * 4 or item["nnp"] != 0
                        or digest(ROOT / "parent.py") != packet["parent_sha256"]):
                    raise Blocked("fixed image controller differs")
                return item, intermediates
            sudo = ["/usr/bin/sudo", "-n", "/usr/bin/python3", "-I", "-S", "-B", str(ROOT / "broker.py")]
            if (item["uids"] != [packet["uid"], 0, 0, 0] or item["gids"] != [0] * 4 or item["nnp"] != 0
                    or item["exe"] != str(Path("/usr/bin/sudo").resolve()) or digest(Path(item["exe"])) != packet["sudo_sha256"]
                    or item["argv"][:7] != sudo or item["argv"][-2:] not in (["acquire", self.nonce], ["finish", self.nonce])):
                raise Blocked("unexpected image privileged ancestry")
            intermediates.append(item)
            current = item["ppid"]
        raise Blocked("fixed image parent absent")

    def _controls(self, packet):
        authority = approval(packet["unit"], current=True)
        if (authority["schema"] != "ar-local-system-recovery-authority-v1" or authority["phase"] != packet["phase"]
                or authority["source_closure_sha256"] != packet["source_closure_sha256"]):
            raise Blocked("distinct image authority differs")
        verify_plain_service(packet["unit"])
        closure = root_json(ROOT / "root-control-manifest.json")
        encoded = json.dumps(closure, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != packet["source_closure_sha256"]:
            raise Blocked("independently approved image root closure differs")
        for name, expected in closure.items():
            if digest(Path(name)) != expected:
                raise Blocked("image root source changed")
        for filename, key in (("parent.py", "parent_sha256"), ("broker.py", "broker_sha256"), ("pi_system_guard_resources.py", "resources_sha256")):
            if digest(ROOT / filename) != packet[key] or authority[key] != packet[key]:
                raise Blocked("fixed image control binding differs")
        for filename, key in (("/usr/bin/bwrap", "bwrap_sha256"), ("/usr/bin/setpriv", "setpriv_sha256"), ("/usr/bin/sudo", "sudo_sha256")):
            if digest(Path(filename).resolve()) != packet[key]:
                raise Blocked("image sandbox executable differs")
        modules = {"pi_shared_queue.py", "pi_shared_queue_store.py", "pi_shared_queue_policy.py", "pi_shared_queue_native.py", "pi_shared_queue_post_hooks.py"}
        queue = packet["queue_closure"]
        if (set(queue) != modules or hashlib.sha256(json.dumps(queue, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != packet["queue_closure_sha256"]
                or any(digest(Path("/usr/local/lib/shared-pi-queue") / name) != checksum for name, checksum in queue.items())):
            raise Blocked("image native queue bridge differs")
        import pwd
        account = pwd.getpwnam("pi")
        if (account.pw_uid, account.pw_gid) != (packet["uid"], packet["gid"]) or account.pw_uid == 0:
            raise Blocked("fixed image account differs")
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            left, right = line.split(" - ", 1)
            if right.split()[0] == "proc" and left.split()[4] != "/proc":
                raise Blocked("alternate host proc mount exposed")
        if digest(ROOT / "backend-approval.json") != packet["backend_approval_sha256"]:
            raise Blocked("image backend review binding differs")
        if digest(Path("/etc/ar-local/drive-write-hold.json")) != packet["global_hold_sha256"]:
            raise Blocked("global Drive hold changed outside this specific manual authority")
        self._recovery_controls(packet)
        self.space_guard(packet)
        if packet["phase"] != "PROBE":
            prior = packet.get("coupled_probe_nonce", "")
            if not re.fullmatch(r"[a-f0-9]{32}", prior) or prior == self.nonce:
                raise Blocked("distinct native image commissioning proof required")
            proof = root_json(HANDOFF / prior / "coupled-probe.json")
            if (proof.get("result") != "IMAGE_PROBE_PASS" or proof.get("boot_id") != self.boot()
                    or proof.get("source_closure_sha256") != packet["source_closure_sha256"]
                    or proof.get("root_completion_verified") is not True):
                raise Blocked("native image closure has no accepted coupled probe")

    def _recovery_controls(self, packet):
        registry = Path("/etc/ar-local/system-recovery-reconcile.json")
        if digest(registry) != packet["reconcile_registry_sha256"]:
            raise Blocked("independent image recovery registry differs")
        value = root_json(registry)
        wrapper = Path("/usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py")
        if (value.get("schema") != "ar-local-system-recovery-reconcile-v1" or value.get("callback") != str(ROOT / "reconcile.py")
                or value.get("callback_sha256") != digest(ROOT / "reconcile.py")
                or value.get("source_closure_sha256") != packet["source_closure_sha256"]
                or value.get("wrapper_sha256") != digest(wrapper) or value["wrapper_sha256"] != packet["reconcile_wrapper_sha256"]):
            raise Blocked("loaded independent image recovery callback differs")
        result = subprocess.run(["/usr/bin/systemctl", "show", "ar-local-drive-reclaim-reconcile.timer", "--property=LoadState,ActiveState,UnitFileState", "--no-pager"],
                                capture_output=True, text=True, check=True, timeout=10, env=ENV)
        if dict(line.split("=", 1) for line in result.stdout.splitlines()) != {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled"}:
            raise Blocked("existing independent recovery timer is not enabled and active")
        from pi_shared_queue_post_hooks import _native
        native = _native("ar-local-drive-reclaim-reconcile.service", "ExecStartEx", subprocess.run)
        fixed = ["/usr/bin/python3", "-I", "-B", str(wrapper), "reconcile"]
        if len(native) != 1 or native[0][:3] != [fixed[0], fixed, []]:
            raise Blocked("existing loaded independent recovery entry differs")
        state = subprocess.check_output(["/usr/bin/systemctl", "show", "ar-local-drive-reclaim-reconcile.service", "--property=User,NoNewPrivileges", "--no-pager"],
                                        text=True, timeout=self.remaining_timeout(10), env=ENV)
        if dict(line.split("=", 1) for line in state.splitlines()) != {"User": "root", "NoNewPrivileges": "yes"}:
            raise Blocked("independent recovery must remain root with NNP")

    def process_identity(self, pid):
        item = identity(pid)
        original = dict(item)
        handle = os.pidfd_open(pid)
        try:
            poll = select.poll()
            poll.register(handle, select.POLLIN)
            root = Path("/proc") / str(pid)
            status = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines())
            item["caps"] = {key: int(status[key].strip(), 16) for key in ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd")}
            item["uids"] = [int(value) for value in status["Uid"].split()]
            item["gids"] = [int(value) for value in status["Gid"].split()]
            item["namespaces"] = {key: (root / "ns" / key).stat().st_ino for key in ("pid", "mnt", "user")}
            if poll.poll(0) or identity(pid) != original:
                raise Blocked("image process changed during kernel privilege observation")
            return item
        finally:
            os.close(handle)

    def allowed_worker(self, item, memory, child, packet):
        phase = packet["phase"]
        if item["cgroup"] != "/system.slice/" + packet["unit"]:
            return False
        current = item
        for _ in range(12):
            if current["pid"] == child:
                break
            current = identity(current["ppid"])
            if current["cgroup"] != item["cgroup"]:
                return False
        else:
            return False
        python = str(Path("/usr/bin/python3").resolve())
        launch = ["/usr/bin/python3", "-I", "-S", "-B", str(ROOT / "launch.py"), self.nonce]
        if item["pid"] == child and item["exe"] == python:
            return item["uids"] == [0] * 4 and item["gids"] == [0] * 4 and item["argv"] in (launch, identity(os.getpid())["argv"])
        if memory["uid"] != 0:
            monitor = self.process_identity(os.getpid())
            return (phase == "upload" and item["uids"] == [packet["uid"]] * 4 and item["gids"] == [packet["gid"]] * 4
                    and memory["uid"] == packet["uid"] and memory["nnp"] == 1 and memory["capabilities"] == 0
                    and item["namespaces"]["pid"] != monitor["namespaces"]["pid"]
                    and item["namespaces"]["mnt"] != monitor["namespaces"]["mnt"]
                    and item["namespaces"]["user"] == monitor["namespaces"]["user"])
        from pi_system_guard_launch import sandbox_command
        command = sandbox_command(packet)
        if item["exe"] == str(Path("/usr/bin/bwrap").resolve()):
            return item["argv"] == command
        if item["exe"] == str(Path("/usr/bin/setpriv").resolve()):
            return item["argv"] == command[command.index("/usr/bin/setpriv"):]
        if item["uids"] != [0] * 4 or item["gids"] != [0] * 4:
            return False
        # Capture's root launcher observes only fixed read-only systemd/dpkg
        # commands outside its private child; no generic host-root executable.
        if item["exe"] == str(Path("/usr/bin/dpkg").resolve()):
            return phase in {"baseline", "prepare", "finalize"} and item["argv"] == ["/usr/bin/dpkg", "--audit"]
        if item["exe"] == str(Path("/usr/bin/systemctl").resolve()):
            if phase not in {"baseline", "prepare", "finalize"}:
                return False
            plan = root_json(Path("/var/lib/ar-local-system-recovery-inputs") / packet["workspace_id"] / "writer-plan.json")
            units = set(plan.get("application_writers", [])) | set(plan.get("package_writers", []))
            if len(item["argv"]) == 3 and item["argv"][:2] in (["/usr/bin/systemctl", "stop"], ["/usr/bin/systemctl", "start"]):
                original = root_json(self.private / "writer-state.json")
                return item["argv"][2] in units and original["original"].get(item["argv"][2]) == "active"
            return len(item["argv"]) == 5 and item["argv"][:2] == ["/usr/bin/systemctl", "show"] and item["argv"][2] in units and item["argv"][3:] == ["--property=ActiveState", "--value"]
        monitor = self.process_identity(os.getpid())
        if (item["namespaces"]["pid"] == monitor["namespaces"]["pid"] or item["namespaces"]["mnt"] == monitor["namespaces"]["mnt"]
                or item["namespaces"]["user"] != monitor["namespaces"]["user"] or memory["nnp"] != 1):
            return False
        mask = sum(1 << bit for bit in BASE_CAPS | ({21} if phase in {"build", "PROBE"} else set()))
        if any(value & ~mask for value in item["caps"].values()):
            return False
        if item["exe"] == python:
            return item["argv"] == command[command.index("/usr/bin/python3"):]
        tools = TOOLS["build"] if phase == "PROBE" else TOOLS.get(phase, set())
        return item["exe"] in {str(Path("/usr/sbin" if name in {"losetup", "mkfs.vfat", "mkfs.ext4", "blkid", "fsck.vfat", "e2fsck"} else "/usr/bin", name).resolve()) for name in tools}

    def trusted_observer(self, item, packet):
        if (item["ppid"] != os.getpid() or item["cgroup"] != "/system.slice/" + packet["unit"]
                or item["uids"] != [0] * 4 or item["gids"] != [0] * 4 or item["nnp"] != 0):
            return False
        expected = ["/usr/bin/systemctl", "show", packet["unit"], "--no-pager", "--property=" + SHOW_FIELDS]
        if item["exe"] == str(Path("/usr/bin/systemctl").resolve()):
            return item["argv"] == expected
        # Account the monitor's own fixed fork/exec transition without treating
        # arbitrary worker-root Python as trusted observer code.
        return item["exe"] == str(Path("/usr/bin/python3").resolve()) and item["argv"] == identity(os.getpid())["argv"]

    def space_guard(self, packet):
        root = WORK / packet["workspace_id"]
        target = root if root.exists() else WORK
        if shutil.disk_usage(target).free < 10 * 1024 ** 3 or os.statvfs(target).f_favail < 100000:
            raise Blocked("image workspace free-byte/inode reserve reached")

    def run_worker(self, packet, expected):
        from pi_system_guard_resources import supervise
        result = supervise(self, packet, expected)
        atomic(self.private / "resources.json", result)
        if result["result"] != "PASS" or result["group_clean"] is not True:
            raise Blocked("image worker failed its unchanged resource budgets")

    def quarantine_credential(self, packet):
        if packet["phase"] == "upload":
            return super().quarantine_credential(packet)

    def complete(self, packet, expected, *, result, readback):
        if readback != 60 or self.value() != 60:
            raise Blocked("terminal image policy60 readback absent")
        from pi_system_guard_writers import restore
        if not self.owned_loop_terminal(packet) or restore(self, packet) is not True:
            raise Blocked("owned image loop or original writers are not terminal")
        resources = root_json(self.private / "resources.json") if (self.private / "resources.json").exists() else {}
        terminal = root_json(self.private / "terminal-resources.json") if (self.private / "terminal-resources.json").exists() else {}
        observations = terminal.get("observations", [])
        accepted = (resources.get("result") == "PASS" and resources.get("group_clean") is True and len(observations) == 2
                    and [item["stage"] for item in observations] == ["before_restore", "after_restore"]
                    and all(item.get("violation") is None for item in observations) and observations[-1].get("readback") == 60)
        body = {"schema": "ar-local-system-recovery-root-completion-v1", "nonce": self.nonce, "phase": packet["phase"],
                "source_closure_sha256": packet["source_closure_sha256"], **{key: expected[key] for key in ("owner_pid", "owner_ticks", "boot_id", "job_id", "unit", "invocation")},
                "result": result, "readback": 60, "untrusted_processes_gone": True,
                "credential_custody": "QUARANTINED" if packet["phase"] == "upload" else "NOT_EXPOSED",
                "stop_post_verified": self.stop_post_verified, "resource_acceptance": "PASS" if accepted else "FAIL_OR_NOT_RUN"}
        body.update(owned_loop_terminal=True, writers_restored=True)
        target = self.public / "completion.json"
        if target.exists():
            old = root_json(target)
            if any(old.get(key) != value for key, value in body.items() if key != "stop_post_verified"):
                raise Blocked("existing image completion differs")
            body["stop_post_verified"] = body["stop_post_verified"] or old.get("stop_post_verified") is True
        atomic(target, body, replace=target.exists(), mode=0o640)
        os.chown(target, 0, packet["gid"])
        if packet["phase"] == "PROBE" and accepted and body["stop_post_verified"]:
            native = root_json(WORK / packet["workspace_id"] / "probe-result.json")
            if (native.get("result") != "IMAGE_PRIVATE_FIXTURE_PROBE_PASS" or native.get("native_filesystems_verified") is not True
                    or native.get("umask_permissions_verified") is not True
                    or native.get("scope") != "NO_REAL_PI_SOURCE_NO_DRIVE_WRITES"):
                raise Blocked("actual native private image restore result absent")
            proof = {"schema": "ar-local-system-recovery-coupled-probe-v1", "result": "IMAGE_PROBE_PASS", "boot_id": self.boot(),
                     "nonce": self.nonce, "source_closure_sha256": packet["source_closure_sha256"], "root_completion_verified": True}
            target = self.public / "coupled-probe.json"
            if target.exists() and root_json(target) != proof:
                raise Blocked("existing image commissioning proof differs")
            if not target.exists():
                atomic(target, proof, mode=0o640)
            os.chown(self.public / "coupled-probe.json", 0, packet["gid"])

    def owned_loop_terminal(self, packet):
        import errno
        import fcntl
        work = WORK / packet["workspace_id"]
        intent = work / "loop-attach-intent.json"
        if not intent.exists():
            return True
        value = root_json(intent)
        match = re.fullmatch(r"/dev/loop([0-9]{1,6})", value["loop"])
        if not match:
            raise Blocked("recorded image loop identity is malformed")
        image = work / "recovery.img"
        info = image.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or image.resolve() != image
                or (info.st_dev, info.st_ino) != (value["device"], value["inode"])):
            raise Blocked("owned image inode changed before terminal proof")
        proof_path = work / "loop-terminal.json"
        proof = {"schema": "ar-local-system-owned-loop-terminal-v1", "boot_id": self.boot(),
                 "device": info.st_dev, "inode": info.st_ino, "loop": value["loop"],
                 "intent_sha256": hashlib.sha256(intent.read_bytes()).hexdigest()}
        if proof_path.exists() and root_json(proof_path) == proof:
            # Later fixed compression/upload phases never attach a loop. A
            # previously detached minor may now legitimately belong elsewhere.
            return True
        def terminal():
            atomic(proof_path, proof, replace=proof_path.exists())
            return True
        name = "loop" + match[1]
        kernel = Path("/sys/class/block") / name
        if not kernel.exists():
            return terminal()
        node = self.private / name
        if not node.exists():
            os.mknod(node, stat.S_IFBLK | 0o600, os.makedev(7, int(match[1])))
        device = node.lstat()
        if not stat.S_ISBLK(device.st_mode) or device.st_rdev != os.makedev(7, int(match[1])) or device.st_uid != 0:
            raise Blocked("private loop proof node changed")
        descriptor = os.open(node, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            status = bytearray(232)
            try:
                fcntl.ioctl(descriptor, 0x4C05, status, True)
            except OSError as error:
                if error.errno == errno.ENXIO:
                    return terminal()
                raise
            dev, inode, _, offset, limit = struct.unpack_from("<QQQQQ", status)
            if (dev, inode) != (info.st_dev, info.st_ino) or offset or limit:
                raise Blocked("loop is foreign or ambiguous; never detach it")
            subprocess.run(["/usr/sbin/losetup", "--detach", str(node)], check=True, timeout=self.remaining_timeout(10), env=ENV)
        finally:
            os.close(descriptor)
        # A second open proves the detach rather than treating exit0 as proof.
        descriptor = os.open(node, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            try:
                fcntl.ioctl(descriptor, 0x4C05, bytearray(232), True)
            except OSError as error:
                if error.errno == errno.ENXIO:
                    return terminal()
                raise
            raise Blocked("owned image loop remains attached")
        finally:
            os.close(descriptor)
