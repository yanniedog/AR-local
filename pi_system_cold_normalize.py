"""Retire captured runtime custody ONLY in the new offline recovery image.

The full unmodified OS+raw tree must be verified first. Original bytes and
metadata move into a private in-image audit; an explicit transformed manifest
is verified afterwards. This starts no work and changes no persistent schedule.
"""
import base64
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from pi_system_capture import relative, sha, utc, write

IMAGE_ROOT = Path("/scratch/joined-root")
BOOT_ROOT = Path("/scratch/joined-boot")
BOOT_POLICY = "etc/sysctl.d/zzzz-ar-local-recovery-swappiness.conf"
OWNER_UID = OWNER_GID = 0
QUEUE = "var/lib/shared-pi-queue/state.json"
LEASE = "srv/ar-local/data/state/daily-ingest.lock"
FAMILIES = (("var/lib/ar-local-system-recovery-control", "var/lib/ar-local-system-recovery-handoff"),
            ("var/lib/ar-local-plain-backup-control", "var/lib/ar-local-plain-backup-handoff"))


def safe(root, name):
    path = root / relative(name)
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("offline normalization path crosses a symlink")
    return path


def record(path, name):
    info = path.lstat()
    row = {"path": name, "type": stat.S_IFMT(info.st_mode), "mode": stat.S_IMODE(info.st_mode),
           "uid": info.st_uid, "gid": info.st_gid, "mtime_ns": info.st_mtime_ns,
           "xattrs": {key: base64.b64encode(os.getxattr(path, key, follow_symlinks=False)).decode("ascii")
                      for key in sorted(os.listxattr(path, follow_symlinks=False))}}
    if stat.S_ISREG(info.st_mode):
        row.update(size=info.st_size, sha256=sha(path))
    return row


def active_custody(root):
    prefixes = []
    active = {}
    for private, public in FAMILIES:
        base = safe(root, private)
        if not base.exists():
            continue
        for entry in os.scandir(base):
            if not re.fullmatch("[a-f0-9]{32}", entry.name):
                continue
            path = Path(entry.path)
            if not entry.is_dir(follow_symlinks=False) or path.is_symlink():
                raise ValueError("captured custody directory is unsafe")
            intent = path / "intent.json"
            if not intent.exists():
                continue  # Unsubmitted preparation has no runtime ownership.
            if intent.is_symlink() or not intent.is_file() or intent.stat().st_size > 65536:
                raise ValueError("invalid bounded captured custody intent")
            value = json.loads(intent.read_bytes())
            if value.get("phase") == "RESTORED":
                continue
            if value.get("phase") not in {"PREPARED", "ACTIVE", "RESTORING"} or value.get("nonce") != entry.name:
                raise ValueError("unknown captured runtime intent; preserve and refuse")
            prefixes.append(private + "/" + entry.name)
            handoff = safe(root, public + "/" + entry.name)
            if handoff.exists():
                if handoff.is_symlink() or not handoff.is_dir():
                    raise ValueError("captured handoff is unsafe")
                prefixes.append(public + "/" + entry.name)
            active[entry.name] = value
    if len(prefixes) > 128:
        raise ValueError("captured custody exceeds bounded normalization scope")
    return prefixes, active


def bounded_json(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 ** 2:
        raise ValueError("bounded regular captured control document required")
    return json.loads(path.read_bytes())


def control_binding(root, nonce, intent):
    private, public = FAMILIES[0]
    packet = bounded_json(safe(root, private + "/" + nonce + "/packet.json"))
    authority = bounded_json(safe(root, public + "/" + nonce + "/approval.json"))
    closure = bounded_json(safe(root, "usr/local/lib/ar-local-system-recovery/root-control-manifest.json"))
    if not isinstance(closure, dict) or not 1 <= len(closure) <= 128:
        raise ValueError("bounded captured image source closure required")
    for name, expected in closure.items():
        if (not name.startswith(("/usr/local/lib/ar-local-system-recovery/", "/usr/local/lib/ar-local-plain-backup/"))
                or not re.fullmatch("[a-f0-9]{64}", expected)
                or sha(safe(root, name.removeprefix("/"))) != expected):
            raise ValueError("captured approved image source closure differs")
    checksum = hashlib.sha256(json.dumps(closure, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (packet.get("schema") != "ar-local-system-recovery-packet-v1" or packet.get("phase") != "finalize"
            or packet.get("manual_system_recovery") is not True
            or authority.get("schema") != "ar-local-system-recovery-authority-v1"
            or authority.get("manual_system_recovery") is not True
            or any(value.get("source_closure_sha256") != checksum or value.get("nonce") != nonce
                   or value.get("unit") != intent["unit"] for value in (packet, authority, intent))
            or authority.get("phase") != packet["phase"] or authority.get("mode") != "RUN_ARCHIVE"
            or packet.get("mode") != "RUN_ARCHIVE"):
        raise ValueError("captured active image owner and approved control closure are not bound")
    return checksum


def image_target(root, path):
    """Resolve sysctl links inside the image, including absolute links, never host /etc."""
    parts, remaining = [], list(Path(path).parts)
    links = 0
    while remaining:
        name = remaining.pop(0)
        if name in {"", "/", "."}:
            continue
        if name == "..":
            if not parts:
                raise ValueError("persistent sysctl link escapes image")
            parts.pop()
            continue
        current = root.joinpath(*parts, name)
        if current.is_symlink():
            links += 1
            if links > 16:
                raise ValueError("persistent sysctl link cycle")
            target = os.readlink(current)
            if target.startswith("/"):
                parts = []
            remaining = list(Path(target).parts) + remaining
        else:
            parts.append(name)
    return root.joinpath(*parts)


def boot_swappiness(root, boot):
    # systemd-sysctl/procps precedence: highest-priority basename, then lexical
    # basename order; procps also reads /etc/sysctl.conf last. /run is omitted
    # runtime state. No captured /proc value is treated as a boot configuration.
    selected = {}
    directories = ("etc/sysctl.d", "usr/local/lib/sysctl.d", "usr/lib/sysctl.d", "lib/sysctl.d")
    for name in directories:
        directory = image_target(root, name)
        if directory.exists():
            for entry in os.scandir(directory):
                if entry.name.endswith(".conf"):
                    selected.setdefault(entry.name, str(Path(name) / entry.name))
                    if len(selected) > 512:
                        raise ValueError("persistent sysctl inventory exceeds bound")
    settings, files = [], []
    paths = [selected[name] for name in sorted(selected)] + ["etc/sysctl.conf"]
    for name in paths:
        path = image_target(root, name)
        if path == root / "dev/null":
            files.append({"path": name, "masked": True})
            continue
        if not path.exists():
            if name != "etc/sysctl.conf":
                raise ValueError("dangling persistent sysctl configuration")
            continue
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 ** 2:
            raise ValueError("bounded persistent sysctl configuration required")
        files.append({"path": name, "sha256": sha(path)})
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            key, separator, value = line.partition("=")
            key = key.strip().lstrip("-").replace("/", ".")
            if fnmatch.fnmatchcase("vm.swappiness", key):
                if key != "vm.swappiness" or not separator or value.strip() != "60":
                    raise ValueError("persistent boot swappiness is conflicting or ambiguous")
                settings.append({"path": name, "line": number, "value": 60})
    if boot != BOOT_ROOT or boot.resolve() != boot or boot.is_symlink():
        raise ValueError("fixed new offline boot filesystem required")
    cmdline = boot / "cmdline.txt"
    if not cmdline.is_file() or cmdline.is_symlink() or cmdline.stat().st_size > 65536:
        raise ValueError("bounded verified boot command line required")
    for token in cmdline.read_text().split():
        if ("sysctl.extra" in token
                or token.startswith("sysctl.") and "swappiness" in token and token != "sysctl.vm.swappiness=60"):
            raise ValueError("boot command line overrides persistent swappiness60")
    for name in ("etc/credstore/sysctl.extra", "etc/credstore.encrypted/sysctl.extra"):
        if safe(root, name).exists():
            raise ValueError("unqualified persistent sysctl credential override")
    for base in ("etc/systemd/system/systemd-sysctl.service.d", "usr/lib/systemd/system/systemd-sysctl.service.d"):
        path = image_target(root, base)
        if path.exists() and any(entry.name.endswith(".conf") for entry in os.scandir(path)):
            raise ValueError("unqualified persistent sysctl service drop-in")
    service = image_target(root, "usr/lib/systemd/system/systemd-sysctl.service")
    override = root / "etc/systemd/system/systemd-sysctl.service"
    if override.exists() or override.is_symlink():
        raise ValueError("unqualified persistent sysctl service replacement")
    if not service.is_file() or service.stat().st_size > 65536:
        raise ValueError("bounded captured systemd sysctl service required")
    starts = []
    for line in service.read_text().splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key == "ExecStart":
            starts.append(value)
        if separator and (key in {"ExecStartPre", "ExecStartPost", "LoadCredential", "LoadCredentialEncrypted", "SetCredential", "SetCredentialEncrypted"}):
            raise ValueError("unqualified persistent sysctl service command or credential")
    if starts != ["/usr/lib/systemd/systemd-sysctl"]:
        raise ValueError("fixed captured systemd sysctl service command required")
    target = safe(root, BOOT_POLICY)
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        raise ValueError("new offline explicit sysctl policy requires an absent target and existing directory")
    if any(name > target.name for name in selected):
        raise ValueError("new offline sysctl policy is not the last basename")
    return {"result": "NEW_OFFLINE_EXPLICIT_SYSCTL60_PLANNED", "settings": settings, "files": files,
            "new_path": BOOT_POLICY, "original_path_state": "ABSENT", "cmdline_sha256": sha(cmdline), "sysctl_service_sha256": sha(service),
            "runtime_proc_value_used": False, "scope": "systemd-sysctl_and_procps_configuration", "boot_test": "NOT_TESTED"}


def new_directories(root, path):
    created = []
    missing = []
    current = path
    while current != root and not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        os.chown(directory, OWNER_UID, OWNER_GID)
        os.chmod(directory, 0o700)
        created.append(directory)
    return created


def normalize(root, manifest, output, recovery_sha, *, boot=None):
    root, manifest, output = Path(root), Path(manifest), Path(output)
    if (root != IMAGE_ROOT or root.resolve() != root or root.is_symlink()
            or not re.fullmatch("[a-f0-9]{64}", recovery_sha)):
        raise ValueError("fixed new offline image root and recovery identity required")
    queue_path, lease_path = safe(root, QUEUE), safe(root, LEASE)
    for path in (queue_path, lease_path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 ** 2:
            raise ValueError("bounded single-link captured queue/native custody required")
    queue = json.loads(queue_path.read_bytes())
    if (set(queue) != {"version", "next_sequence", "jobs"} or queue["version"] != 1
            or type(queue["next_sequence"]) is not int or not 0 <= queue["next_sequence"] < 2 ** 63
            or not isinstance(queue["jobs"], list) or not 1 <= len(queue["jobs"]) <= 1024):
        raise ValueError("captured active v1 queue is not recognized")
    prefixes, active = active_custody(root)
    if any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
           or row.get("state") not in {"waiting", "running", "quarantined"} for row in queue["jobs"]):
        raise ValueError("unknown captured queue runtime record")
    jobs = {row["id"]: row for row in queue["jobs"]}
    lines = lease_path.read_text().splitlines()
    lease = dict(line.split("=", 1) for line in lines)
    if len(jobs) != len(queue["jobs"]) or len(lines) != 4 or len(lease) != 4:
        raise ValueError("ambiguous captured ownership metadata")
    owner = jobs.get(lease.get("role", "").removeprefix("shared-pi-host-task:"), {})
    nonce = owner.get("unit", "").removeprefix("ar-local-plain-backup-").removesuffix(".service")
    binding = {"owner_pid": owner.get("pid"), "owner_ticks": owner.get("start_ticks"), "boot_id": owner.get("boot_id"),
               "job_id": owner.get("id"), "unit": owner.get("unit"), "invocation": owner.get("invocation_id")}
    if (nonce not in active or active[nonce].get("unit") != owner.get("unit")
            or any(active[nonce].get("identity", {}).get(key) != value or value is None for key, value in binding.items())
            or lease != {"pid": str(owner.get("pid")), "boot_id": owner.get("boot_id"),
                         "role": "shared-pi-host-task:" + owner.get("id", ""), "recovery": "manual"}):
        raise ValueError("captured native lease and active image custody are not bound")
    if any(row.get("boot_id") != owner["boot_id"] for row in queue["jobs"]):
        raise ValueError("captured queue contains missing or foreign boot custody")
    control_sha = control_binding(root, nonce, active[nonce])
    boot_policy = boot_swappiness(root, Path(boot) if boot is not None else BOOT_ROOT)
    audit_name = "var/lib/ar-local-recovery-normalization/" + recovery_sha
    audit = safe(root, audit_name)
    base = audit.parent
    if base.exists() and (base.stat().st_uid != OWNER_UID or stat.S_IMODE(base.stat().st_mode) != 0o700):
        raise ValueError("existing offline audit parent is not private")
    if audit.exists():
        raise ValueError("existing offline normalization is preserved; never retry")
    moved = [QUEUE, LEASE, *prefixes]
    legacy = "var/lib/ar-local-drive-reclaim/current.json"
    if safe(root, legacy).exists() or safe(root, legacy).is_symlink():
        raise ValueError("unbound legacy reclaim custody must be preserved and reviewed")
    def retired(name):
        return any(name == prefix or name.startswith(prefix + "/") for prefix in moved)
    # Hash-match every selected original before the first transformation.
    found = set()
    with manifest.open(encoding="ascii") as source:
        for line in source:
            row = json.loads(line)
            if retired(row["path"]):
                path = safe(root, row["path"])
                if row["type"] not in {stat.S_IFREG, stat.S_IFDIR} or "hardlink_to" in row:
                    raise ValueError("unsupported captured custody node")
                if row["type"] == stat.S_IFREG and (path.stat().st_nlink != 1 or sha(path) != row["sha256"]):
                    raise ValueError("captured custody bytes differ before normalization")
                found.add(row["path"])
    if not set(moved) <= found:
        raise ValueError("captured custody is missing from verified source manifest")
    created = new_directories(root, audit)
    before = {name: sha(safe(root, name)) for name in moved if safe(root, name).is_file()}
    for name in moved:
        destination = audit / "original" / name
        created += new_directories(root, destination.parent)
        os.rename(safe(root, name), destination)  # Same image filesystem, metadata retained.
    normalized = {**queue, "jobs": []}
    with queue_path.open("x", encoding="ascii") as destination:
        json.dump(normalized, destination, sort_keys=True, separators=(",", ":"))
        destination.write("\n")
        destination.flush()
        os.fsync(destination.fileno())
    policy_path = safe(root, BOOT_POLICY)
    with policy_path.open("x", encoding="ascii") as destination:
        destination.write("# Offline recovery: retain the observed normal host policy.\nvm.swappiness = 60\n")
        destination.flush()
        os.fsync(destination.fileno())
    os.chown(policy_path, OWNER_UID, OWNER_GID)
    os.chmod(policy_path, 0o644)
    boot_policy.update(result="NEW_OFFLINE_EXPLICIT_SYSCTL60", new_sha256=sha(policy_path))
    receipt = {"schema": "ar-local-offline-custody-normalization-v1", "scope": "NEW_OFFLINE_IMAGE_ONLY",
               "captured_manifest_sha256": sha(manifest), "recovery_set_sha256": recovery_sha,
               "retired_paths": moved, "original_file_sha256": before, "original_queue_jobs": len(queue["jobs"]),
               "captured_boot_id": owner["boot_id"], "retired_queue_jobs":
                   [{"id": row["id"], "boot_id": row["boot_id"], "state": row["state"]} for row in queue["jobs"]],
               "queue_after_sha256": sha(queue_path), "retired_active_nonces": sorted(active),
               "captured_control_closure_sha256": control_sha, "persistent_boot_policy": boot_policy,
               "automatic_work_started": False, "persistent_schedules": "UNCHANGED", "boot_test": "NOT_TESTED", "recorded_at": utc()}
    receipt_path = audit / "receipt.json"
    write(receipt_path, receipt)
    os.chown(receipt_path, OWNER_UID, OWNER_GID)
    os.chmod(receipt_path, 0o600)
    new_rows = {path.relative_to(root).as_posix(): record(path, path.relative_to(root).as_posix()) for path in created}
    new_rows[receipt_path.relative_to(root).as_posix()] = record(receipt_path, receipt_path.relative_to(root).as_posix())
    new_rows[BOOT_POLICY] = record(policy_path, BOOT_POLICY)
    # Existing parent-directory metadata remains the captured expectation and is
    # restored by the caller after all moves/new children have been created.
    with output.open("x", encoding="ascii") as destination, manifest.open(encoding="ascii") as source:
        for line in source:
            row = json.loads(line)
            name = row["path"]
            if retired(name):
                original = {**row, "path": audit_name + "/original/" + name}
                destination.write(json.dumps(original, sort_keys=True) + "\n")
                if name == QUEUE:
                    row.update(size=queue_path.stat().st_size, sha256=sha(queue_path))
                else:
                    continue
            destination.write(json.dumps(row, sort_keys=True) + "\n")
        for row in new_rows.values():
            destination.write(json.dumps(row, sort_keys=True) + "\n")
        destination.flush()
        os.fsync(destination.fileno())
    return {"result": "OFFLINE_RUNTIME_CUSTODY_RETIRED", "receipt_sha256": sha(receipt_path),
            "receipt_path": receipt_path.relative_to(root).as_posix(), "manifest_sha256": sha(output),
            "original_manifest_sha256": sha(manifest), "queue_admission": "EMPTY_VALID_V1_QUEUE",
            "persistent_boot_policy": "NEW_OFFLINE_EXPLICIT_SYSCTL60", "boot_test": "NOT_TESTED"}
