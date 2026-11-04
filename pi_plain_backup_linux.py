"""Root-owned stdlib effects for fixed plaintext-backup reclaim/credential scope."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
try:
    import pwd
except ImportError:
    pwd=None
import select
import stat
import subprocess

from pi_plain_backup_core import (Blocked, packet_runtime_seconds, parse_runtime_microseconds,
                                 validate_commissioning_packet)
from pi_shared_queue_post_hooks import ROOT, HANDOFF, approval, root_json, pairs, verify_plain_service

STATE = Path("/var/lib/ar-local-plain-backup-control")
NATIVE = Path("/srv/ar-local/data/state/daily-ingest.lock")
CREDENTIAL = "/var/lib/ar-local-drive-backup/credentials/dedicated-20260913-ready3/rclone-verified-ready3.conf"
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", "HOME": "/root"}


def digest(path):
    path = Path(path)
    for item in (path, *path.parents):
        info = item.lstat()
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o022:
            raise Blocked("untrusted fixed root source")
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 64*1024*1024:
        raise Blocked("untrusted bounded root source")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(pid):
    if type(pid) is not int or not 0 < pid <= 4194304:
        raise Blocked("invalid kernel PID identity")
    handle = os.pidfd_open(pid)
    try:
        poll = select.poll(); poll.register(handle, select.POLLIN)
        if poll.poll(0): raise Blocked("process identity has exited")
        root = Path("/proc") / str(pid)
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        status = pairs(line.split(":", 1) for line in (root / "status").read_text().splitlines())
        group = (root / "cgroup").read_text().strip()
        if not group.startswith("0::/") or "\n" in group: raise Blocked("unified cgroup required")
        value = {"pid": pid, "ticks": int(fields[19]), "ppid": int(fields[1]),
                 "uid": int(status["Uid"].split()[0]),
                 "uids": [int(item) for item in status["Uid"].split()],
                 "gids": [int(item) for item in status["Gid"].split()], "nnp": int(status["NoNewPrivs"].strip()),
                 "exe": str((root / "exe").resolve()), "cgroup": group[3:],
                 "argv": [x.decode() for x in (root / "cmdline").read_bytes().split(b"\0") if x]}
        if poll.poll(0) or int((root/"stat").read_text().rsplit(")",1)[1].split()[19]) != value["ticks"]:
            raise Blocked("process changed during identity read")
        return value
    finally:
        os.close(handle)


def atomic(path, value, *, replace=False, mode=0o600):
    path = Path(path)
    temporary = path.with_name("." + path.name + ".pending")
    created = False
    try:
        with temporary.open("xb") as stream:
            created = True; os.chmod(temporary, mode)
            stream.write((json.dumps(value, sort_keys=True, indent=2)+"\n").encode())
            stream.flush(); os.fsync(stream.fileno())
        if replace: os.replace(temporary, path)
        else: os.link(temporary, path); temporary.unlink()
        directory = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if created: temporary.unlink(missing_ok=True)


class Host:
    def __init__(self, nonce):
        self.nonce = nonce
        self.private = STATE / nonce
        self.public = HANDOFF / nonce
        self.resource_baseline = None
        self.stop_post_verified = False
        self.stage = "host_ready"

    def now(self): return datetime.now(timezone.utc)
    def boot(self): return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    def value(self): return int(Path("/proc/sys/vm/swappiness").read_text())
    def set_value(self, value):
        self.stage="apply_zero" if value==0 else "restore_sixty"
        if value not in (0,60): raise Blocked("only measured60/temporary0 exists")
        Path("/proc/sys/vm/swappiness").write_text(str(value)+"\n")
    def packet(self, nonce):
        if nonce != self.nonce: raise Blocked("nonce scope differs")
        return root_json(self.private / "packet.json")
    def intent(self, nonce):
        path = self.private / "intent.json"
        return root_json(path) if path.exists() else None
    def save_intent(self, nonce, value, create=False):
        self.stage="intent_write"
        if nonce != self.nonce: raise Blocked("intent nonce differs")
        atomic(self.private / "intent.json", value, replace=not create)

    def _show(self, unit):
        fields = "Id,LoadState,ActiveState,SubState,MainPID,ControlPID,InvocationID,ControlGroup,User,NoNewPrivileges,Type,KillMode,NeedDaemonReload,CPUQuotaPerSecUSec,TasksMax,IOWeight,RuntimeMaxUSec"
        result = subprocess.run(["/usr/bin/systemctl", "show", unit, "--no-pager", "--property="+fields],
            capture_output=True, text=True, timeout=10, env=ENV)
        value = pairs(line.split("=",1) for line in result.stdout.splitlines() if line)
        if set(value) != set(fields.split(",")) or value["Id"] != unit:
            raise Blocked("incomplete native service identity")
        if result.returncode and not (result.returncode == 1 and value["LoadState"] == "not-found"):
            raise Blocked("service identity unavailable")
        return value

    def _members(self, group):
        if not group.startswith("/system.slice/ar-local-plain-backup-") or ".." in Path(group).parts:
            raise Blocked("foreign cgroup")
        root = Path("/sys/fs/cgroup") / group.lstrip("/")
        if not root.exists(): return []
        paths = list(root.glob("**/cgroup.procs"))
        if len(paths) > 8: raise Blocked("nested/unbounded backup cgroups")
        values = {int(pid) for path in paths for pid in path.read_text().split()}
        if len(values)>128: raise Blocked("unbounded backup membership")
        return sorted(values)

    def _closure(self, packet):
        rows = packet.get("closure")
        if not isinstance(rows, dict) or not 1 <= len(rows) <= 128:
            raise Blocked("reviewed immutable source closure absent")
        if hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":")).encode()).hexdigest() != packet["source_closure_sha256"]:
            raise Blocked("source closure binding differs")
        for relative, expected in rows.items():
            if (Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative
                    or digest(ROOT/relative) != expected):
                raise Blocked("source closure member differs")

    def _controller(self, packet):
        current, intermediates = os.getppid(), []
        expected = ["/usr/bin/python3","-I","-B",str(ROOT/"parent.py"),self.nonce]
        own=identity(os.getpid())
        if (own.get("uids")!=[0]*4 or own.get("gids")!=[0]*4 or own["nnp"]!=0
                or own["exe"]!=str(Path("/usr/bin/python3").resolve())
                or own["argv"] not in [["/usr/bin/python3","-I","-B",str(ROOT/"broker.py"),action,self.nonce]
                    for action in ("acquire","finish")]):
            raise Blocked("fixed root broker credentials/command differ")
        # sudo's setuid monitor retains the invoking Pi real UID. Its effective,
        # saved and filesystem IDs are root; requiring realUID0 rejects native
        # sudo even though the root Python child has all four UID/GID fields0.
        sudo=["/usr/bin/sudo","-n",*own["argv"]]
        digest(Path("/usr/bin/sudo").resolve())  # root-protected executable only
        for _ in range(4):
            item = identity(current)
            if item["cgroup"]!=own["cgroup"]:
                raise Blocked("privileged caller left the admitted cgroup")
            if item["argv"] == expected:
                if (item.get("uids")!=[packet["uid"]]*4 or item.get("gids")!=[packet["gid"]]*4
                        or item["nnp"]!=0 or item["exe"]!=str(Path("/usr/bin/python3").resolve())
                        or digest(ROOT/"parent.py")!=packet["parent_sha256"]):
                    raise Blocked("trusted parent identity differs")
                return item, intermediates
            if (item.get("uids")!=[packet["uid"],0,0,0] or item.get("gids")!=[0]*4 or item["nnp"]!=0
                    or item["exe"]!=str(Path("/usr/bin/sudo").resolve()) or item["argv"]!=sudo):
                raise Blocked("unexpected privileged caller ancestry")
            intermediates.append(item); current=item["ppid"]
        raise Blocked("trusted parent not found in bounded ancestry")

    def _job(self, packet, *, allow_terminal=False):
        fd=os.open("/var/lib/shared-pi-queue/state.json",os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=packet["uid"] or info.st_nlink!=1
                    or not 0<info.st_size<=1048576):
                raise Blocked("bounded Pi-owned queue state required")
            body=os.read(fd,1048577)
            if len(body)!=info.st_size: raise Blocked("queue state changed during read")
            data=json.loads(body,object_pairs_hook=pairs)
        finally: os.close(fd)
        jobs = [job for job in data.get("jobs",[]) if job.get("unit")==packet["unit"]]
        if len(jobs)!=1: raise Blocked("unique retained queue claim missing")
        job=jobs[0]; info=self._show(packet["unit"])
        if (job.get("state") not in (("waiting","running") if allow_terminal else ("running",))
                or type(job.get("max_duration_seconds")) is not int
                or job["max_duration_seconds"]!=packet_runtime_seconds(packet,allow_legacy=allow_terminal)
                or job.get("project")!="ar-local" or job.get("mode")!="exclusive"
                or not {"ar-local","host"} <= set(job.get("resources",[]))
                or not (info["InvocationID"]==job.get("invocation_id") or allow_terminal and info["LoadState"]=="not-found"
                    and info["MainPID"]=="0" and info["ControlPID"]=="0" and info["InvocationID"]=="")
                or job.get("cgroup") != "/system.slice/"+packet["unit"]):
            raise Blocked("retained host queue invocation differs")
        if not allow_terminal and (info["MainPID"] != str(job["pid"]) or info["ActiveState"]!="active"):
            raise Blocked("live admitted queue wrapper absent")
        return job,info

    def _lease(self, job):
        fd=os.open(NATIVE,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd); values=pairs(line.split("=",1) for line in os.read(fd,16385).decode("ascii").splitlines())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.packet(self.nonce)["uid"] or info.st_nlink!=1
                    or values!={"pid":str(job["pid"]),"boot_id":job["boot_id"],
                        "role":"shared-pi-host-task:"+job["id"],"recovery":"manual"}):
                raise Blocked("exact inherited manual native lease differs")
            return info
        finally: os.close(fd)

    def _controls(self, packet):
        self.stage="controls_authority"
        if packet.get("root_control_manifest_sha256")!=digest(ROOT/"root-control-manifest.json"):
            raise Blocked("packet does not bind the installed root control manifest")
        authority=approval(packet["unit"],current=True)
        if authority["source_closure_sha256"] != packet["source_closure_sha256"]:
            raise Blocked("root approval/packet source binding differs")
        self.stage="controls_native"
        verify_plain_service(packet["unit"])
        self.stage="controls_closure"
        self._closure(packet)
        self.stage="controls_queue"
        modules={"pi_shared_queue.py","pi_shared_queue_store.py","pi_shared_queue_policy.py",
            "pi_shared_queue_native.py","pi_shared_queue_post_hooks.py"}
        queue_closure=packet.get("queue_closure",{})
        if (set(queue_closure)!=modules or hashlib.sha256(json.dumps(queue_closure,sort_keys=True,
                separators=(",",":")).encode()).hexdigest()!=packet["queue_closure_sha256"]
                or any(digest(Path("/usr/local/lib/shared-pi-queue")/name)!=expected
                    for name,expected in queue_closure.items())):
            raise Blocked("exact reviewed installed queue bridge differs")
        self.stage="controls_sources"
        for name,key in (("broker.py","broker_sha256"),("parent.py","parent_sha256"),
                         ("pi_plain_drive_resources.py","resources_sha256")):
            if digest(ROOT/name)!=packet[key] or authority[key]!=packet[key]:
                raise Blocked("approved root control source differs")
        self.stage="controls_uid"
        pi=pwd.getpwnam("pi")
        if (packet["uid"],packet["gid"])!=(pi.pw_uid,pi.pw_gid) or pi.pw_uid==0:
            raise Blocked("approved Pi account UID/GID changed")
        self.stage="controls_runtime"
        for path,key in (("/usr/bin/bwrap","bwrap_sha256"),("/usr/bin/setpriv","setpriv_sha256")):
            if digest(Path(path).resolve())!=packet[key]:
                raise Blocked("fixed sandbox runtime differs")
        # Do not expose an alternate host-proc mount through the recursive root
        # bind. Private /proc alone is insufficient when another alias exists.
        self.stage="controls_proc"
        for row in Path("/proc/self/mountinfo").read_text().splitlines():
            left,right=row.split(" - ",1)
            if right.split()[0]=="proc" and left.split()[4]!="/proc":
                raise Blocked("host proc alias would escape the private PID view")
        self.stage="controls_hold"
        if digest(Path("/etc/ar-local/drive-write-hold.json"))!=packet["global_hold_sha256"]:
            raise Blocked("global legacy hold changed; no bypass permitted")
        if Path("/var/lib/ar-local-drive-reclaim/current.json").exists():
            raise Blocked("another root reclaim owner exists")
        self.stage="controls_reconciler"
        timer=subprocess.run(["/usr/bin/systemctl","show","ar-local-drive-reclaim-reconcile.timer",
            "--property=LoadState,ActiveState,UnitFileState","--no-pager"],capture_output=True,text=True,timeout=10,check=True,env=ENV)
        values=pairs(line.split("=",1) for line in timer.stdout.splitlines())
        if values!={"LoadState":"loaded","ActiveState":"active","UnitFileState":"enabled"}:
            raise Blocked("existing independent reconciler is not active/enabled")
        entry=Path("/usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py")
        original=entry.with_name("pi_drive_reclaim.original.py")
        bindings=root_json(ROOT/"reconcile-wrapper-manifest.json")
        expected_bindings={"wrapper_sha256":packet["reconcile_wrapper_sha256"],
            "original_sha256":packet["reconcile_original_sha256"],
            "callback_sha256":packet["reconcile_callback_sha256"],
            "root_control_manifest_sha256":digest(ROOT/"root-control-manifest.json")}
        if bindings!=expected_bindings or any(digest(path)!=expected_bindings[key] for key,path in
                (("wrapper_sha256",entry),("original_sha256",original),("callback_sha256",ROOT/"reconcile.py"))):
            raise Blocked("same-loaded-path wrapper/original/callback closure differs")
        from pi_shared_queue_post_hooks import _native
        native=_native("ar-local-drive-reclaim-reconcile.service","ExecStartEx",subprocess.run)
        fixed=["/usr/bin/python3","-I","-B",str(entry),"reconcile"]
        if len(native)!=1 or len(native[0])!=10 or native[0][:3]!=[fixed[0],fixed,[]]:
            raise Blocked("existing loaded root reconciliation entry differs")
        rootservice=subprocess.run(["/usr/bin/systemctl","show","ar-local-drive-reclaim-reconcile.service",
            "--property=User,NoNewPrivileges","--no-pager"],capture_output=True,text=True,timeout=10,check=True,env=ENV)
        if pairs(line.split("=",1) for line in rootservice.stdout.splitlines())!={"User":"root","NoNewPrivileges":"yes"}:
            raise Blocked("existing root reconciliation privilege boundary differs")
        self.stage="controls_workspace"
        work=Path("/var/lib/ar-local-plain-backup-work")/self.nonce
        for directory in (work,work.parent):
            info=directory.lstat()
            if info.st_uid!=0 or not stat.S_ISDIR(info.st_mode) or info.st_mode&0o022 or directory.resolve()!=directory:
                raise Blocked("root-controlled workspace parent differs")
        sandbox=work/"sandbox"; info=sandbox.lstat()
        if (not stat.S_ISDIR(info.st_mode) or sandbox.resolve()!=sandbox or info.st_uid!=packet["uid"]
                or stat.S_IMODE(info.st_mode)!=0o700 or list(sandbox.iterdir())):
            raise Blocked("new private writable sandbox must be empty and Pi-owned0700")
        self.stage="controls_probe"
        probe=root_json(self.private/"sandbox-probe.json")
        if (probe.get("schema")!="ar-local-plain-backup-sandbox-probe-v1" or probe.get("result")!="PASS"
                or probe.get("boot_id")!=self.boot() or probe.get("bwrap_sha256")!=packet["bwrap_sha256"]
                or probe.get("setpriv_sha256")!=packet["setpriv_sha256"]
                or probe.get("private_pid_mount") is not True or probe.get("host_uid_mapping") is not True
                or probe.get("source_readonly") is not True or probe.get("no_host_proc_alias") is not True
                or probe.get("nnp_all_caps_dropped") is not True or probe.get("sealed_context_verified") is not True):
            raise Blocked("actual fixed-namespace kernel probe absent")
        self.stage="controls_coupled"
        if packet["mode"]=="RUN_ARCHIVE":
            previous=packet.get("coupled_probe_nonce","")
            if not re.fullmatch("[0-9a-f]{32}",previous) or previous==self.nonce:
                raise Blocked("distinct actual commissioning nonce required")
            validate_commissioning_packet(root_json(STATE/previous/"packet.json"),previous,packet)
            prior_completion=root_json(HANDOFF/previous/"completion.json")
            if (prior_completion.get("operation_mode")!="PROBE" or prior_completion.get("resource_acceptance")!="PASS"
                    or prior_completion.get("readback")!=60 or prior_completion.get("result")!="RESTORED"
                    or prior_completion.get("untrusted_processes_gone") is not True
                    or prior_completion.get("stop_post_verified") is not True):
                raise Blocked("commissioning root completion proof differs")
            coupled=root_json(HANDOFF/previous/"coupled-probe.json")
            if (coupled.get("result")!="PROBE_PASS" or coupled.get("scope")!="NO_BACKUP_NO_DRIVE_WRITES"
                    or coupled.get("boot_id")!=self.boot() or coupled.get("root_completion_verified") is not True
                    or coupled.get("source_closure_sha256")!=packet["source_closure_sha256"]
                    or any(coupled.get(key)!=packet[key] for key in
                        ("bwrap_sha256","setpriv_sha256","parent_sha256","resources_sha256","broker_sha256","queue_closure_sha256","root_control_manifest_sha256"))):
                raise Blocked("actual successful coupled probe of this closure required")
        self.stage="controls_credential"
        conf=self.public/"credentials-copy.conf"
        info=conf.lstat()
        if (info.st_uid!=0 or info.st_gid!=packet["gid"] or info.st_nlink!=1
                or not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=65536 or stat.S_IMODE(info.st_mode)!=0o440
                or hashlib.sha256(conf.read_bytes()).hexdigest()!=packet["credential_sha256"]):
            raise Blocked("root-prestaged read-only scoped OAuth copy differs")

    def admission(self, packet):
        self._controls(packet)
        self.stage="admission_job"
        job,service=self._job(packet)
        self.stage="admission_controller"
        parent,_=self._controller(packet)
        self.stage="admission_owner"
        owner=identity(job["pid"])
        self.stage="admission_profile"
        if (parent["ppid"]!=job["pid"] or owner["ticks"]!=job["start_ticks"] or owner.get("uids")!=[packet["uid"]]*4 or owner.get("gids")!=[packet["gid"]]*4
                or parent["cgroup"]!=job["cgroup"] or owner["cgroup"]!=job["cgroup"]
                or service["User"]!="pi" or service["NoNewPrivileges"]!="no" or service["Type"]!="notify"
                or service["KillMode"]!="control-group"
                or parse_runtime_microseconds(service["RuntimeMaxUSec"])!=packet_runtime_seconds(packet)*1000000
                or service["CPUQuotaPerSecUSec"]!="1s" or service["TasksMax"]!="64" or service["IOWeight"]!="10"
                or job["boot_id"]!=self.boot()):
            raise Blocked("trusted controller/queue relationship differs")
        self.stage="admission_native_fd"
        info=self._lease(job); inherited=os.stat(f"/proc/{parent['pid']}/fd/3")
        if (info.st_dev,info.st_ino)!=(inherited.st_dev,inherited.st_ino):
            raise Blocked("trusted parent FD3 is not the inherited native lease")
        self.stage="admission_resources"
        from pi_plain_drive_resources import sample_host,host_violation
        current=sample_host()
        if self.resource_baseline is None: self.resource_baseline=current
        reason=host_violation(current,self.resource_baseline,self.resource_baseline,admission=True)
        if reason: raise Blocked(reason)
        return {"resource_baseline":self.resource_baseline,"fd":3,"owner_pid":job["pid"],"owner_ticks":job["start_ticks"],"boot_id":job["boot_id"],
            "job_id":job["id"],"unit":job["unit"],"invocation":job["invocation_id"],"cgroup":job["cgroup"],
            "device":info.st_dev,"inode":info.st_ino,"controller_pid":parent["pid"],"controller_ticks":parent["ticks"],
            "controller_sha256":packet["parent_sha256"],"resources_sha256":packet["resources_sha256"],"bwrap_sha256":packet["bwrap_sha256"]}

    def recheck(self, packet, expected):
        if self.admission(packet)!=expected: raise Blocked("admission changed before zero")

    def write_handoff(self, packet, value):
        self.stage="handoff_write"
        atomic(self.public/"lease.json",value,mode=0o640)
        os.chown(self.public/"lease.json",0,packet["gid"])

    def process_identity(self,pid):
        return identity(pid)

    def trusted_namespace_process(self,item,child,packet):
        """Only the recorded fork and its fixed bwrap/setpriv descendants."""
        fixed_bwrap="/usr/bin/bwrap"
        fixed_setpriv="/usr/bin/setpriv"
        from pi_plain_drive_resources import sandbox_argv
        full=sandbox_argv(packet)
        if item.get("uids")!=[0]*4 or item["cgroup"]!="/system.slice/"+packet["unit"]:
            return False
        current=item
        for _ in range(4):
            if current["pid"]==child:
                break
            current=identity(current["ppid"])
            if current.get("uids")!=[0]*4 or current.get("gids")!=[0]*4 or current["cgroup"]!=item["cgroup"]:
                return False
        else: return False
        if item["exe"]==str(Path(fixed_bwrap).resolve()):
            # bwrap's private PID init retains the original fixed command line.
            return item.get("gids")==[0]*4 and item["argv"]==full
        if item["exe"]==str(Path(fixed_setpriv).resolve()):
            offset=full.index(fixed_setpriv)
            return item.get("gids") in ([0]*4,[packet["gid"]]*4) and item["argv"]==full[offset:]
        # The direct fork can be observed before its first exec. It must still
        # be our exact root broker image/argv; arbitrary root Python is rejected.
        return (item.get("gids")==[0]*4 and item["pid"]==child and item["exe"]==str(Path("/usr/bin/python3").resolve())
            and item["argv"]==identity(os.getpid())["argv"])

    def run_worker(self,packet,expected):
        # This module is hash-bound in root's bootstrap manifest and contains
        # only stdlib resource/namespace control, never producer imports.
        from pi_plain_drive_resources import supervise
        result=supervise(self,packet,expected)
        atomic(self.private/"resources.json",result)
        if result["result"]!="PASS" or result["group_clean"] is not True:
            raise Blocked("private archive worker failed its unchanged resource guards")

    def no_acquire_identity(self, packet):
        job,_=self._job(packet,allow_terminal=True)
        return {"owner_pid":job["pid"],"owner_ticks":job["start_ticks"],"boot_id":job["boot_id"],
            "job_id":job["id"],"unit":job["unit"],"invocation":job["invocation_id"],"cgroup":job["cgroup"]}

    def prove_terminal(self, packet, expected, *, recovery):
        self.stage="finish_terminal"
        info=self._show(packet["unit"]); members=self._members(expected["cgroup"])
        if info["LoadState"]!="not-found" and info["InvocationID"]!=expected["invocation"]:
            raise Blocked("unit reused; no cleanup authorized")
        allowed={os.getpid()}
        if recovery:
            if members:
                # A privileged native ExecStopPost is the unit's ControlPID;
                # an outside orphan reconciler may proceed only on empty scope.
                if members!=[os.getpid()] or info["ControlPID"]!=str(os.getpid()) or info["MainPID"]!="0":
                    raise Blocked("untrusted processes survive; no restore/quarantine")
                self.stop_post_verified=True
        else:
            parent,intermediates=self._controller(packet)
            if (parent["pid"],parent["ticks"])!=(expected["controller_pid"],expected["controller_ticks"]):
                raise Blocked("parent identity changed")
            owner=identity(expected["owner_pid"])
            if owner["ticks"]!=expected["owner_ticks"] or info["MainPID"]!=str(owner["pid"]):
                raise Blocked("wrapper identity changed before finish")
            allowed.update([owner["pid"],parent["pid"],*[item["pid"] for item in intermediates]])
            if set(members)!=allowed:
                raise Blocked("untrusted/unknown worker PIDs remain")
        if "device" in expected and expected.get("boot_id")==self.boot():
            job,_=self._job(packet,allow_terminal=recovery)
            aliases={"id":"job_id","pid":"owner_pid","start_ticks":"owner_ticks","boot_id":"boot_id","invocation_id":"invocation"}
            if any(job.get(key)!=expected[value] for key,value in aliases.items()):
                raise Blocked("retained job changed before native custody proof")
            lease=self._lease(job)
            if "device" in expected and (lease.st_dev,lease.st_ino)!=(expected["device"],expected["inode"]):
                raise Blocked("native lease changed during worker lifetime")

    def observe_terminal(self,packet,expected,stage):
        self.stage="finish_resources"
        from pi_plain_drive_resources import sample_host,host_violation
        sample=sample_host(); baseline=expected.get("resource_baseline")
        reason=host_violation(sample,baseline,baseline) if baseline is not None else "no_owned_workload_baseline"
        target=self.private/"terminal-resources.json"
        previous=root_json(target) if target.exists() else {"observations":[]}
        if len(previous["observations"])>=4: raise Blocked("terminal resource record unexpectedly repeated")
        previous["observations"].append({"stage":stage,"host":sample,"violation":reason,
            "recorded_at":self.now().isoformat(),"readback":self.value()})
        atomic(target,previous,replace=target.exists())

    def quarantine_credential(self, packet):
        self.stage="credential_quarantine"
        source=self.public/"credentials-copy.conf"; target=self.private/"credentials-quarantine.conf"
        if not source.exists():
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==packet["credential_sha256"]:
                return
            raise Blocked("credential-copy custody ambiguous")
        info=source.lstat()
        if info.st_uid!=0 or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or target.exists():
            raise Blocked("credential quarantine target/owner ambiguous")
        if hashlib.sha256(source.read_bytes()).hexdigest()!=packet["credential_sha256"]:
            raise Blocked("credential copy changed; preserve it for investigation")
        if source.parent.stat().st_dev!=target.parent.stat().st_dev:
            raise Blocked("credential quarantine must be an atomic same-filesystem rename")
        os.chmod(source,0o600)
        after=source.lstat()
        if (after.st_dev,after.st_ino)!=(info.st_dev,info.st_ino):
            raise Blocked("credential identity changed before quarantine")
        os.rename(source,target)  # Exact private paths; never recursive cleanup.
        for path in (source.parent,target.parent):
            descriptor=os.open(path,os.O_DIRECTORY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)

    def complete(self, packet, expected, *, result, readback):
        self.stage="finish_completion"
        if readback!=60 or self.value()!=60: raise Blocked("terminal60 readback missing")
        resources=root_json(self.private/"resources.json") if (self.private/"resources.json").exists() else {}
        terminal=root_json(self.private/"terminal-resources.json") if (self.private/"terminal-resources.json").exists() else {}
        observations=terminal.get("observations",[])
        accepted=(resources.get("result")=="PASS" and resources.get("group_clean") is True
            and len(observations)==2 and [item["stage"] for item in observations]==["before_restore","after_restore"]
            and all(item.get("violation") is None for item in observations)
            and observations[-1].get("readback")==60)
        value={"schema":"ar-local-plain-backup-root-completion-v1","nonce":self.nonce,
            **{key:expected[key] for key in ("owner_pid","owner_ticks","boot_id","job_id","unit","invocation")},
            "result":result,"readback":60,"untrusted_processes_gone":True,"credential_quarantined":True,
            "stop_post_verified":self.stop_post_verified,"operation_mode":packet["mode"],"resource_acceptance":"PASS" if accepted else "FAIL_OR_NOT_RUN",
            "recorded_at":self.now().isoformat(),"recorded_boot_id":self.boot()}
        target=self.public/"completion.json"
        if target.exists():
            old=root_json(target)
            value["stop_post_verified"]=value["stop_post_verified"] or old.get("stop_post_verified") is True
            if any(old.get(key)!=value[key] for key in value if key not in ("recorded_at","recorded_boot_id","stop_post_verified")):
                raise Blocked("existing completion differs")
            if old.get("stop_post_verified") is not True and value["stop_post_verified"]:
                atomic(target,value,replace=True,mode=0o640);os.chown(target,0,packet["gid"])
        else:
            atomic(target,value,mode=0o640); os.chown(target,0,packet["gid"])
        if packet["mode"]=="PROBE" and accepted and self.stop_post_verified:
            if "runtime_seconds" not in packet or "root_control_manifest_sha256" not in packet:
                return  # Recovery preserves legacy proofs; it never upgrades commissioning authority.
            proof={"schema":"ar-local-plain-backup-coupled-probe-v1","result":"PROBE_PASS",
                "scope":"NO_BACKUP_NO_DRIVE_WRITES","nonce":self.nonce,"boot_id":self.boot(),
                "root_completion_verified":True,**{key:packet[key] for key in
                    ("source_closure_sha256","bwrap_sha256","setpriv_sha256","parent_sha256","resources_sha256","broker_sha256","queue_closure_sha256","root_control_manifest_sha256")}}
            probe_target=self.public/"coupled-probe.json"
            if probe_target.exists():
                if root_json(probe_target)!=proof: raise Blocked("existing coupled commissioning proof differs")
            else:
                atomic(probe_target,proof,mode=0o640)
                os.chown(probe_target,0,packet["gid"])
