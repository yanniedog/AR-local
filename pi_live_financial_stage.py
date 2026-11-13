"""Read-only production staging identity and isolated, filesystem-matched stages.

Environment files accept literal single-line systemd assignments. More complex
escaping/continuations fail closed; they are never evaluated as shell input.
Only the staging assignment and file metadata leave the reader.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess

KEY = "AR_LOCAL_RAM_ROOT"
PROFILES = ("production", "tmpfs-supplemental")
SERVICE = "ar-local-daily.service"
PROPERTIES = {"User", "Environment", "EnvironmentFiles", "PassEnvironment", "UnsetEnvironment"}


def canonical_name(value):
    path = PurePosixPath(value)
    if (not re.fullmatch(r"/[A-Za-z0-9._/-]+", value) or ".." in path.parts or str(path) != value):
        raise ValueError("staging path must be canonical, absolute and unambiguous")
    return value


def canonical(value):
    path = Path(canonical_name(value))
    if path.resolve() != path:
        raise ValueError("staging path must have no symlink ancestors")
    return path


def environment_file(text):
    """Conservative systemd literal grammar; reject unsupported syntax globally."""
    assignments = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or "\\" in value:
            raise ValueError("unsupported systemd environment-file syntax")
        if value[:1] in {"'", '"'}:
            quote = value[0]
            if len(value) < 2 or value[-1] != quote or quote in value[1:-1]:
                raise ValueError("unsupported quoted environment-file assignment")
            value = value[1:-1]
        if key == KEY:
            assignments.append(value)
    return assignments


def identity(st):
    return [st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_nlink,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def read_environment_file(name, optional):
    path = canonical(name)
    for parent in (path.parent, *path.parent.parents):
        try:
            st = parent.lstat()
        except FileNotFoundError:
            if optional:
                continue
            raise ValueError("required environment-file ancestor is missing") from None
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError("environment-file ancestor is not root protected")
    try:
        before = path.lstat()
    except FileNotFoundError:
        if optional:
            return [], {"path": name, "optional": True, "missing": True}
        raise ValueError("required production environment file is missing") from None
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_nlink != 1
            or before.st_mode & 0o022 or before.st_size > 1024**2):
        raise ValueError("unsafe production environment file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("environment-file identity changed")
        raw = stream.read(1024**2 + 1)
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("environment-file changed while read")
    if identity(path.lstat()) != identity(before) or len(raw) > 1024**2:
        raise ValueError("environment-file changed while read")
    return environment_file(raw.decode("utf-8")), {"path": name, "optional": optional, "identity": identity(before)}


def resolve_configuration(fields, reader=read_environment_file, uid_for_user=None):
    if set(fields) != PROPERTIES or any(not isinstance(value, str) for value in fields.values()):
        raise ValueError("complete exact production environment properties required")
    if uid_for_user is None:
        import pwd
        uid_for_user = lambda user: pwd.getpwnam(user).pw_uid
    user = fields.get("User", "")
    if not user or uid_for_user(user) < 1000:
        raise ValueError("production user must be an explicit unprivileged owner")
    if KEY in shlex.split(fields.get("PassEnvironment", "")):
        raise ValueError("manager-inherited staging environment is ambiguous")
    if "\\" in fields.get("Environment", ""):
        raise ValueError("escaped systemd Environment serialization requires explicit review")
    value = f"/dev/shm/ar-local-{uid_for_user(user)}"
    assignments = []
    for token in shlex.split(fields.get("Environment", "")):
        key, sep, item = token.partition("=")
        if key == KEY and sep:
            value = canonical_name(item)
            assignments.append({"source": "Environment", "value": item})
    files, text = [], fields.get("EnvironmentFiles", "").strip()
    while text:
        match = re.match(r"(/[^\s\\]+) \(ignore_errors=(yes|no)\)(?:\s+|$)", text)
        if not match:
            raise ValueError("unsupported systemd EnvironmentFiles representation")
        values, meta = reader(match[1], match[2] == "yes")
        files.append(meta)
        for item in values:
            value = canonical_name(item)
            assignments.append({"source": match[1], "value": item})
        text = text[match.end():]
    unset = shlex.split(fields.get("UnsetEnvironment", ""))
    if KEY in unset or f"{KEY}={value}" in unset:
        value = f"/dev/shm/ar-local-{uid_for_user(user)}"
    root = canonical_name(value)
    result = {"service": SERVICE, "user": user, "effective_root": root,
              "assignments": assignments, "environment_files": files,
              "unset_staging": [s for s in unset if s.split("=", 1)[0] == KEY]}
    result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def production_configuration():
    result = subprocess.run(["systemctl", "show", SERVICE,
        "--property=User,Environment,EnvironmentFiles,PassEnvironment,UnsetEnvironment"],
        capture_output=True, text=True, check=True, timeout=15)
    return resolve_configuration(property_fields(result.stdout))


def property_fields(text):
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key not in PROPERTIES or key in fields:
            raise ValueError("duplicate or unexpected production environment property")
        fields[key] = value
    if set(fields) != PROPERTIES:
        raise ValueError("incomplete production environment properties")
    return fields


def filesystem(path):
    path = canonical(str(path))
    ancestor = path
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not ancestor.is_dir() or ancestor.resolve() != ancestor:
        raise ValueError("staging ancestor must be a canonical directory")
    st = ancestor.stat()
    result = subprocess.run(["findmnt", "--json", "--target", str(ancestor),
        "--output", "TARGET,FSTYPE,MAJ:MIN,FSROOT"], capture_output=True, text=True,
        check=True, timeout=10)
    rows = json.loads(result.stdout)["filesystems"]
    if len(rows) != 1 or not rows[0].get("fstype"):
        raise ValueError("staging filesystem is ambiguous")
    return {"st_dev": st.st_dev, "fstype": rows[0]["fstype"],
            "mount": rows[0]["target"], "fsroot": rows[0]["fsroot"], "major_minor": rows[0]["maj:min"]}


def choose_stage(operation, profile, configuration, probe=filesystem):
    if profile not in PROFILES:
        raise ValueError("unknown staging qualification profile")
    production = probe(Path(configuration["effective_root"]))
    use_tmpfs = profile == "tmpfs-supplemental" or production["fstype"] == "tmpfs"
    root = (Path("/dev/shm") / ("ar-local-canary-" + operation.name)
            if use_tmpfs else operation / "capture-stage")
    selected = probe(root)
    if (profile == "production" and backing(selected) != backing(production)
            or use_tmpfs and selected["fstype"] != "tmpfs"):
        raise ValueError("isolated staging filesystem does not match qualification profile")
    if root.exists() or root.is_symlink():
        raise ValueError("isolated capture stage already exists")
    return {"profile": profile, "production_fidelity": profile == "production",
            "qualification": "PRODUCTION_STORAGE" if profile == "production" else "SUPPLEMENTAL",
            "root": str(root), "filesystem": selected, "production_filesystem": production,
            "production_configuration": configuration}


def backing(observation):
    """Bind backing storage; mount targets/fsroot legitimately differ in sandbox."""
    return {key: observation[key] for key in ("st_dev", "fstype", "major_minor")}


def directory_identity(path):
    path = canonical(str(path))
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise ValueError("capture stage must remain a private owned directory")
    return {"st_dev": st.st_dev, "st_ino": st.st_ino, "st_uid": st.st_uid, "mode": stat.S_IMODE(st.st_mode)}


def verify_directory(binding):
    if directory_identity(Path(binding["root"])) != binding["directory_identity"]:
        raise ValueError("capture stage directory identity changed")
    observed = filesystem(Path(binding["root"]))
    if backing(observed) != backing(binding["filesystem"]):
        raise ValueError("capture stage backing filesystem changed")
    return observed


def verify_stage(marker, binding, probe=filesystem):
    if marker.get("ram_staged") is not True or marker.get("ram_root") != binding["root"]:
        raise ValueError("capture selected a different staging root or mode")
    observed = probe(Path(binding["root"]))
    if backing(observed) != backing(binding["filesystem"]):
        raise ValueError("actual capture filesystem changed")
    return {"root": marker["ram_root"], "filesystem": observed,
            "profile": binding["profile"], "production_fidelity": binding["production_fidelity"],
            "qualification": binding["qualification"]}
