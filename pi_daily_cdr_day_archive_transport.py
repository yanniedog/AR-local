"""Create-only rclone transport for daily CDR raw records on Google Drive."""
from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from pathlib import Path

FOLDER_NAME = "daily-cdr-raw-records"
LEGACY_FOLDER_NAME = "daily-cdr-day-archives"
PRODUCTION_DATA_ROOT = "/srv/ar-local/data"
PRODUCTION_DAY_ARCHIVE_SPOOL = "/var/lib/ar-local-day-archives"
CANARY_ROOT_PARENT = Path("/srv/ar-local/canary")
CANARY_GENERATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GEN = r"obs-\d{4}-\d{2}-\d{2}-[0-9a-f]{16}"
OBJECT_RE = re.compile(
    r"^(?:"
    rf"\d{{4}}-\d{{2}}-\d{{2}}(?:\.{_GEN})?\.(?:tar\.zst|sha256|manifest\.json|GAP\.json)"
    r"|CONTROL\.(?:tar\.zst|sha256|manifest\.json)"
    r")$"
)


def resolve_archive_remote(remote: str, *, preserve_absolute: bool = False) -> str:
    """Pin uploads to daily-cdr-raw-records. The older day-archives folder is immutable.

    When ``preserve_absolute`` is true (isolated canary local backend), keep a
    leading ``/`` so rclone local remotes stay absolute under the canary tree.
    """
    match = re.fullmatch(r"([a-zA-Z0-9_-]+):(.*)", remote.strip())
    if not match:
        raise ValueError("rclone remote must be name:path")
    remote_name, raw_path = match.group(1), match.group(2)
    absolute = bool(preserve_absolute and raw_path.startswith("/"))
    remote_path = raw_path.strip("/")
    segments = [segment for segment in remote_path.split("/") if segment]
    if any(segment in (".", "..") for segment in segments):
        raise ValueError("day-archive remote path must not contain . or ..")
    if LEGACY_FOLDER_NAME in segments:
        raise ValueError(
            "refusing immutable export-only folder daily-cdr-day-archives; "
            "raw records use daily-cdr-raw-records"
        )
    if FOLDER_NAME in segments and segments[-1] != FOLDER_NAME:
        raise ValueError("daily-cdr-raw-records must be the final remote path segment")
    if not segments or segments[-1] != FOLDER_NAME:
        segments = [*segments, FOLDER_NAME]
    joined = "/".join(segments)
    if absolute:
        return f"{remote_name}:/{joined}"
    return f"{remote_name}:{joined}"


def _canary_root_from_env() -> Path:
    """Derive ``<canary>`` from ``AR_LOCAL_DAY_ARCHIVE_ENV=<canary>/config/day-archive.env``.

    The canary root must be a generation directory directly under the canonical
    canary parent (default ``/srv/ar-local/canary/<generation>``).
    """
    override = os.environ.get("AR_LOCAL_DAY_ARCHIVE_ENV", "").strip()
    if not override:
        raise ValueError(
            "local rclone archive requires AR_LOCAL_DAY_ARCHIVE_ENV (canary isolation)"
        )
    env_path = Path(override).expanduser().resolve(strict=False)
    if env_path.name != "day-archive.env" or env_path.parent.name != "config":
        raise ValueError(
            "canary day-archive env must be <canary>/config/day-archive.env"
        )
    canary_root = env_path.parent.parent
    parent = CANARY_ROOT_PARENT.resolve(strict=False)
    if (
        canary_root.parent != parent
        or not CANARY_GENERATION_RE.fullmatch(canary_root.name)
        or not canary_root.is_dir()
    ):
        raise ValueError(
            f"canary root must be an existing generation directory under {parent}"
        )
    return canary_root


def _is_same_or_beneath(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_local_canary_destination(remote_path: str, canary_root: Path) -> Path:
    """Require absolute local destination under the isolated canary tree only."""
    if not remote_path.startswith("/"):
        raise ValueError("canary local archive remote must use an absolute path")
    destination = Path(remote_path).resolve(strict=False)
    if not _is_same_or_beneath(destination, canary_root.resolve(strict=False)):
        raise ValueError(
            f"canary local archive remote must stay under canary root {canary_root}"
        )
    for forbidden in (PRODUCTION_DAY_ARCHIVE_SPOOL, PRODUCTION_DATA_ROOT):
        if _is_same_or_beneath(destination, Path(forbidden).resolve(strict=False)):
            raise ValueError(
                f"canary local archive remote must not use production path {forbidden}"
            )
    return destination


def _require_private_rclone_config(config: Path) -> None:
    info = config.lstat()
    if (
        config != config.resolve()
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size > 1024**2
        or stat.S_IMODE(info.st_mode) not in (0o400, 0o440, 0o600, 0o640)
        # Root services may read a pi-owned conf under a root-only credentials dir.
        or info.st_uid not in (0, os.getuid(), 1000)
    ):
        raise ValueError("private canonical existing rclone config required")


def migrate_day_archive_env(text: str) -> str:
    """Point an installed env file at daily-cdr-raw-records.

    Rewrites only a remote whose final segment is the legacy immutable folder.
    A remote that already ends in the raw-records folder is unchanged. Any other
    destination is rejected. The transport still refuses the legacy folder.
    install-day-archive.sh inlines this decision under python3 -I -S and must
    not import this module. Keep the two copies aligned.
    """
    lines = text.splitlines(True)
    seen = False
    rewritten: list[str] = []
    for line in lines:
        if not line.startswith("AR_LOCAL_DAY_ARCHIVE_REMOTE="):
            rewritten.append(line)
            continue
        seen = True
        newline = "\n" if line.endswith("\n") else ""
        raw = line[:-1] if newline else line
        key, separator, value = raw.partition("=")
        if separator != "=":
            raise ValueError("AR_LOCAL_DAY_ARCHIVE_REMOTE must be name:path")
        quote = ""
        body = value.strip()
        if len(body) >= 2 and body[0] == body[-1] and body[0] in "\"'":
            quote = body[0]
            body = body[1:-1]
        match = re.fullmatch(r"([a-zA-Z0-9_-]+):(.*)", body.strip())
        if not match:
            raise ValueError("AR_LOCAL_DAY_ARCHIVE_REMOTE must be name:path")
        remote_name, remote_path = match.group(1), match.group(2).strip("/")
        segments = [segment for segment in remote_path.split("/") if segment]
        if not segments:
            raise ValueError("AR_LOCAL_DAY_ARCHIVE_REMOTE needs a folder path")
        if segments[-1] == LEGACY_FOLDER_NAME:
            segments[-1] = FOLDER_NAME
        elif segments[-1] != FOLDER_NAME:
            raise ValueError(
                "AR_LOCAL_DAY_ARCHIVE_REMOTE must end in daily-cdr-raw-records "
                "or daily-cdr-day-archives"
            )
        migrated = resolve_archive_remote(f"{remote_name}:{'/'.join(segments)}")
        rewritten.append(f"{key}={quote}{migrated}{quote}{newline}")
    if not seen:
        raise ValueError("AR_LOCAL_DAY_ARCHIVE_REMOTE missing")
    return "".join(rewritten)


class DayArchiveTransportError(RuntimeError):
    """Fatal transport failure; abort without deleting local archives."""


DEFAULT_DRIVE_BACKUP_SPOOL = Path("/var/lib/ar-local-drive-backup")


def require_day_archive_writes_allowed(
    spool: Path, *, local_backend: bool = False
) -> None:
    """Honor the global Drive write hold for direct CLI and service invocations.

    Isolated canary ``type=local`` archives never touch Drive, so the Drive write
    hold (D-028) must not block them when ``local_backend`` is true.
    """
    if local_backend:
        return
    from pi_drive_backup_hold import Blocked, require_writes_allowed

    try:
        require_writes_allowed(Path(spool))
        backup_spool = Path(
            os.environ.get(
                "AR_LOCAL_DRIVE_BACKUP_SPOOL", str(DEFAULT_DRIVE_BACKUP_SPOOL)
            )
        )
        if backup_spool.resolve() != Path(spool).resolve():
            require_writes_allowed(backup_spool)
    except Blocked as error:
        raise DayArchiveTransportError(str(error)) from error


class DayArchiveRclone:
    def __init__(self, config: Path, remote: str, root_folder_id: str, guard=lambda: None):
        self.config = Path(config)
        self.root_folder_id = root_folder_id
        self.guard = guard
        self.executable = "/usr/bin/rclone"
        self.local_backend = False
        match = re.fullmatch(r"([a-zA-Z0-9_-]+):(.*)", remote.strip())
        if not match:
            raise ValueError("rclone remote must be name:path")
        self.remote_name = match.group(1)
        if root_folder_id and not re.fullmatch(r"[a-zA-Z0-9_-]{10,200}", root_folder_id):
            raise ValueError("pinned Drive root folder ID invalid")
        _require_private_rclone_config(self.config)
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.config, encoding="utf-8")
        if self.remote_name not in parser:
            raise ValueError(f"rclone remote section missing: {self.remote_name}")
        section = parser[self.remote_name]
        backend = section.get("type", "").strip()
        canary_override = bool(os.environ.get("AR_LOCAL_DAY_ARCHIVE_ENV", "").strip())
        if backend == "local":
            self._init_local_canary(remote, section)
            return
        if canary_override:
            raise ValueError(
                "canary day-archive env requires type=local rclone remote (D-028)"
            )
        self.remote = resolve_archive_remote(remote)
        match = re.fullmatch(r"([a-zA-Z0-9_-]+):(.*)", self.remote)
        if not match:
            raise ValueError("rclone remote must be name:path")
        self.remote_name = match.group(1)
        allowed_roots = (None, "", root_folder_id) if root_folder_id else (None, "")
        if (
            backend != "drive"
            or section.get("scope") != "drive.file"
            or not json.loads(section.get("token", "{}")).get("refresh_token")
            or section.get("service_account_file")
            or section.get("service_account_credentials")
            or section.get("team_drive")
            or section.get("root_folder_id") not in allowed_roots
        ):
            raise ValueError("reuse existing drive.file application credentials only")

    def _init_local_canary(self, remote: str, section) -> None:
        """Allow rclone ``type=local`` only for isolated canary trees (D-028: no Drive)."""
        if self.root_folder_id:
            raise ValueError("canary local archive must not set a Drive root folder id")
        # Local backend must stay sparse: no Drive OAuth or shared-drive keys.
        forbidden = (
            "token",
            "client_id",
            "client_secret",
            "service_account_file",
            "service_account_credentials",
            "team_drive",
            "root_folder_id",
            "scope",
        )
        if any(section.get(key) for key in forbidden):
            raise ValueError("canary local rclone remote must not carry Drive credentials")
        canary_root = _canary_root_from_env()
        self.remote = resolve_archive_remote(remote, preserve_absolute=True)
        match = re.fullmatch(r"([a-zA-Z0-9_-]+):(.*)", self.remote)
        if not match:
            raise ValueError("rclone remote must be name:path")
        self.remote_name = match.group(1)
        _validate_local_canary_destination(match.group(2), canary_root)
        self.local_backend = True

    def path(self, relative: str) -> str:
        name = PureName(relative)
        if not OBJECT_RE.fullmatch(name):
            raise ValueError(f"unsupported day-archive object path: {relative}")
        return f"{self.remote}/{name}"

    def _drive_root_args(self) -> list[str]:
        if not self.root_folder_id:
            return []
        return ["--drive-root-folder-id", self.root_folder_id]

    def ensure_folder(self) -> None:
        """Create the dedicated subdirectory if missing (mkdir idempotent)."""
        self.guard()
        env = self._env()
        args = [
            self.executable,
            "--config",
            str(self.config),
            "mkdir",
            *self._drive_root_args(),
            "--",
            self.remote,
        ]
        completed = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
        if completed.returncode not in (0,):
            # rclone mkdir is idempotent; treat already-exists as success when stderr is empty-ish
            stderr = (completed.stderr or "").lower()
            if "already" not in stderr and completed.returncode != 0:
                raise DayArchiveTransportError(
                    f"failed to ensure Drive folder {self.remote}: exit {completed.returncode}"
                )

    def upload(self, relative: str, source: Path) -> None:
        self._copyto("upload", relative, source)

    def download(self, relative: str, destination: Path) -> bool:
        if destination.exists() or destination.is_symlink():
            raise ValueError("download requires new private destination")
        return self._copyto("download", relative, destination, missing=True)

    def remote_exists(self, relative: str) -> bool:
        self.guard()
        env = self._env()
        args = [
            self.executable,
            "--config",
            str(self.config),
            "lsf",
            *self._drive_root_args(),
            "--",
            self.path(relative),
        ]
        completed = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
        if completed.returncode in (3, 4):
            return False
        if completed.returncode != 0:
            raise DayArchiveTransportError(f"remote exists check failed: exit {completed.returncode}")
        return bool(completed.stdout.strip())

    def _env(self) -> dict:
        return {
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "GOMAXPROCS": "2",
            "GOMEMLIMIT": "192MiB",
            "GOGC": "50",
            "HOME": "/nonexistent",
        }

    def _copyto(self, direction: str, relative: str, local: Path, *, missing: bool = False) -> bool:
        if direction not in ("upload", "download"):
            raise ValueError("fixed transfer direction required")
        remote = self.path(relative)
        local = Path(local)
        if not local.is_absolute() or local != local.resolve() or local.is_symlink():
            raise ValueError("canonical absolute local object required")
        if direction == "upload" and not local.is_file():
            raise ValueError("regular local upload required")
        if direction == "download" and local.exists():
            raise ValueError("new local download required")
        source, destination = (str(local), remote) if direction == "upload" else (remote, str(local))
        self.guard()
        args = [
            self.executable,
            "--config",
            str(self.config),
            "copyto",
            *self._drive_root_args(),
            "--immutable",
            "--ignore-existing",
            "--checksum",
            "--transfers",
            "1",
            "--checkers",
            "1",
            "--bwlimit",
            "8M",
            "--retries",
            "1",
            "--low-level-retries",
            "2",
            "--contimeout",
            "30s",
            "--timeout",
            "600s",
            "--",
            source,
            destination,
        ]
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            child = subprocess.Popen(args, stdout=out, stderr=err, env=self._env())
            try:
                while child.poll() is None:
                    self.guard()
                    if out.tell() + err.tell() > 256 * 1024:
                        raise DayArchiveTransportError("transport diagnostic size limit exceeded")
                    time.sleep(0.1)
                self.guard()
                if missing and child.returncode in (3, 4):
                    return False
                if child.returncode:
                    raise DayArchiveTransportError(f"day-archive transport failed: exit {child.returncode}")
                return True
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=10)


def PureName(relative: str) -> str:
    """Accept only a single object filename. Do not strip directory prefixes."""
    text = relative.replace("\\", "/").strip()
    if not text or text != Path(text).name or text in (".", ".."):
        raise ValueError("day-archive objects are flat under the dedicated folder")
    if not OBJECT_RE.fullmatch(text):
        raise ValueError(f"unsupported day-archive object path: {relative}")
    return text


def sha256_file(path: Path, guard=lambda: None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            guard()
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_uploaded_archive(
    transport: DayArchiveRclone,
    relative: str,
    local_archive: Path,
    expected_sha256: str,
    scratch: Path,
    guard=lambda: None,
) -> None:
    """Re-download the cloud object and require exact sha256 match before local unlink."""
    scratch.mkdir(parents=True, exist_ok=True)
    download = scratch / f"verify-{PureName(relative)}"
    if download.exists():
        download.unlink()
    ok = transport.download(relative, download)
    if not ok:
        raise DayArchiveTransportError(f"remote object missing after upload: {relative}")
    if download.stat().st_size != local_archive.stat().st_size:
        raise DayArchiveTransportError("remote size differs from local archive")
    actual = sha256_file(download, guard)
    if actual != expected_sha256:
        raise DayArchiveTransportError("remote sha256 differs from local archive")
    if sha256_file(local_archive, guard) != expected_sha256:
        raise DayArchiveTransportError("local archive changed after upload")
    download.unlink()
