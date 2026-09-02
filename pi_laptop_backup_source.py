"""Read-only Pi source for compressed laptop preservation streams.

This helper is copied to a unique temporary path by the laptop receiver.  It
never writes the production checkout or data tree.  Observation streams read a
completed run plus its bound state.  Control streams first create a private
snapshot in /dev/shm so SQLite, Git, and mutable state are internally
consistent, then remove that exact temporary directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from contextlib import closing
from datetime import date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


PROTOCOL = "ar-local-laptop-backup-stream-v1"
QUIET_START = time(0, 30)
QUIET_END = time(3, 30)
WINDOW_TZ = ZoneInfo("Australia/Hobart")
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
CHUNK = 1024 * 1024
TIMER_NEXT_RE = re.compile(
    r"^(?P<weekday>[A-Z][a-z]{2}) (?P<date>\d{4}-\d{2}-\d{2}) "
    r"01:00:00 (?P<zone>AEST|AEDT)$"
)


def validate_next_daily_timer(value: str, now: datetime) -> None:
    match = TIMER_NEXT_RE.fullmatch(value)
    local_now = now.astimezone(WINDOW_TZ)
    expected_date = local_now.date()
    if local_now.timetz().replace(tzinfo=None) >= time(1, 0):
        expected_date += timedelta(days=1)
    expected = datetime.combine(expected_date, time(1, 0), WINDOW_TZ)
    if (
        match is None
        or date.fromisoformat(match["date"]) != expected_date
        or match["weekday"] != expected.strftime("%a")
        or match["zone"] != expected.tzname()
    ):
        raise ValueError("daily ingest timer is not scheduled for the exact next 01:00 in Australia/Hobart")


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=120)


def canonical_root(value: str, label: str) -> Path:
    configured = Path(value).expanduser()
    if not configured.is_absolute() or configured.is_symlink():
        raise ValueError(f"{label} must be an absolute non-symlink path")
    resolved = configured.resolve(strict=True)
    if configured != resolved or not resolved.is_dir():
        raise ValueError(f"{label} must be a canonical real directory")
    return resolved


def in_quiet_window(now: datetime | None = None) -> bool:
    current = (now or datetime.now(WINDOW_TZ)).astimezone(WINDOW_TZ).timetz().replace(tzinfo=None)
    return QUIET_START <= current < QUIET_END


def repo_state(repo: Path) -> dict[str, object]:
    commit = command("git", "-C", str(repo), "rev-parse", "HEAD").stdout.strip()
    dirty = command("git", "-C", str(repo), "status", "--porcelain").stdout.splitlines()
    return {"path": str(repo), "commit": commit, "clean": not dirty, "dirty_paths": dirty}


def http_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - fixed operator URL
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
            return bool(
                response.status == 200
                and isinstance(payload, dict)
                and payload.get("schema_version") == 1
                and payload.get("service") == "ar-local"
                and payload.get("status") in {"ok", "degraded"}
            )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def valid_terminal_failure(state: Path, protected_sha: str) -> dict[str, object] | None:
    root = state / "ingest-executions"
    if not root.is_dir() or root.is_symlink():
        return None
    for record_path in sorted(root.glob("????-??-??/*.FAIL.json"), reverse=True):
        try:
            date = record_path.parent.name
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if (
                record_path.is_symlink()
                or not isinstance(record, dict)
                or record.get("result") != "FAIL"
                or record.get("run_date") != date
                or record.get("repository_clean") is not True
                or record.get("candidate_code_sha") != protected_sha
                or record.get("deviations") != []
                or record.get("deviation_authorization") is not None
                or not record.get("exact_commands")
                or (state / f"{date}.done.json").exists()
            ):
                continue
            evidence = record.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                continue
            failure_root = record_path.parent.resolve()
            for item in evidence:
                path = Path(str(item.get("path") or "")) if isinstance(item, dict) else Path()
                resolved = path.resolve(strict=True)
                if (
                    not path.is_absolute()
                    or path.is_symlink()
                    or not path.is_file()
                    or resolved != path
                    or not resolved.is_relative_to(failure_root)
                    or sha256_file(path) != str(item.get("sha256") or "")
                ):
                    break
            else:
                return {"run_date": date, "record_path": str(record_path), "result": "FAIL"}
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return None


def production_preflight(args: argparse.Namespace) -> dict[str, object]:
    if in_quiet_window():
        raise ValueError("backup is forbidden during the 00:30-03:30 Australia/Hobart quiet window")
    repo = canonical_root(args.production_repo, "production repo")
    runs = canonical_root(args.runs_root, "runs root")
    state = canonical_root(args.state_root, "state root")
    current = repo_state(repo)
    if not current["clean"]:
        raise ValueError("production checkout is dirty")
    if current["commit"] != args.expected_production_sha:
        raise ValueError("production checkout does not match the expected protected SHA")
    if (state / "daily-ingest.lock").exists():
        raise ValueError("daily ingest lock exists")
    service = command("systemctl", "is-active", "ar-local-daily.service", check=False).stdout.strip()
    terminal_failure = None
    if service == "failed":
        terminal_failure = valid_terminal_failure(state, args.expected_production_sha)
        if terminal_failure is None:
            raise ValueError("daily ingest service failed without verified terminal-failure evidence")
    elif service != "inactive":
        raise ValueError(f"daily ingest service is active: {service}")
    timer = command("systemctl", "is-enabled", "ar-local-daily.timer", check=False).stdout.strip()
    if timer != "enabled":
        raise ValueError(f"daily ingest timer is not enabled: {timer}")
    timer_active = command(
        "systemctl", "is-active", "ar-local-daily.timer", check=False
    ).stdout.strip()
    if timer_active != "active":
        raise ValueError(f"daily ingest timer is not active: {timer_active}")
    timer_next = command(
        "systemctl",
        "show",
        "ar-local-daily.timer",
        "--property=NextElapseUSecRealtime",
        "--value",
    ).stdout.strip()
    checked_at = datetime.now(WINDOW_TZ)
    validate_next_daily_timer(timer_next, checked_at)
    if not http_healthy(args.status_url):
        raise ValueError("status health endpoint is not HTTP 200")
    return {
        "checked_at": checked_at.isoformat(),
        "production": current,
        "runs_root": str(runs),
        "state_root": str(state),
        "daily_service": service,
        "terminal_failure_authorization": terminal_failure,
        "daily_timer": timer,
        "daily_timer_active": timer_active,
        "daily_timer_next": timer_next,
        "ingest_lock_absent": True,
        "status_url": args.status_url,
        "status_healthy": True,
    }


def validate_archive_path(relative: str, seen: dict[str, str]) -> None:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe archive path: {relative}")
    for part in path.parts:
        if "\x00" in part or "\n" in part or "\r" in part or ":" in part:
            raise ValueError(f"path is invalid on Windows: {relative}")
        if part.endswith((" ", ".")) or part.split(".", 1)[0].upper() in WINDOWS_RESERVED:
            raise ValueError(f"path is invalid on Windows: {relative}")
    folded = relative.casefold()
    prior = seen.setdefault(folded, relative)
    if prior != relative:
        raise ValueError(f"case-insensitive path collision: {prior} / {relative}")


def file_entry(path: Path, relative: str, seen: dict[str, str]) -> dict[str, object]:
    validate_archive_path(relative, seen)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError(f"source is not a regular non-symlink file: {path}")
    if info.st_nlink != 1:
        raise ValueError(f"source has multiple hard links: {path}")
    return {
        "path": relative,
        "type": "file",
        "size": info.st_size,
        "sha256": sha256_file(path),
        "mode": oct(stat.S_IMODE(info.st_mode)),
        "mtime_ns": (info.st_mtime_ns // 1_000_000_000) * 1_000_000_000,
        "uid": info.st_uid,
        "gid": info.st_gid,
    }


def regular_tree(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().encode("utf-8")):
        if path.is_symlink():
            raise ValueError(f"source tree contains symlink: {path}")
        if path.is_file():
            files.append(path)
        elif not path.is_dir():
            raise ValueError(f"source tree contains special file: {path}")
    return files


def json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def observation_sources(args: argparse.Namespace) -> tuple[list[tuple[Path, str]], dict[str, object]]:
    runs = Path(args.runs_root)
    state = Path(args.state_root)
    date = args.date
    run = (runs / date).resolve(strict=True)
    if run.parent != runs.resolve() or not run.is_dir() or run.is_symlink():
        raise ValueError("observation run path is not a direct real child of runs root")
    done = state / f"{date}.done.json"
    if not done.is_file() or done.is_symlink():
        raise ValueError("completed observation marker is missing")
    if json_object(done).get("date", date) not in {date, None}:
        raise ValueError("legacy completion marker date mismatch")
    selected: dict[str, Path] = {
        f"data/runs/{date}/{path.relative_to(run).as_posix()}": path
        for path in regular_tree(run)
    }
    for path in (done, state / f"{date}.integrity.json"):
        if path.is_file() and not path.is_symlink():
            selected[f"data/state/{path.name}"] = path
    for relative_root in (
        Path("completion-markers-v2") / date,
        Path("export-contracts-v2") / date,
        Path("ledger-v2/events") / date,
    ):
        source_root = state / relative_root
        if source_root.is_dir() and not source_root.is_symlink():
            for path in regular_tree(source_root):
                selected[f"data/state/{path.relative_to(state).as_posix()}"] = path
    pointer = state / "observation-pointers-v2/latest-observation.json"
    latest = None
    if pointer.is_file() and not pointer.is_symlink():
        candidate = json_object(pointer)
        if candidate.get("observation_date") == date:
            latest = candidate
            selected["data/state/observation-pointers-v2/latest-observation.json"] = pointer
            head = state / "ledger-v2/head.json"
            if head.is_file() and not head.is_symlink():
                selected["data/state/ledger-v2/head.json"] = head
    if not any(path.startswith(f"data/runs/{date}/_exports/local-cdr.sqlite") for path in selected):
        raise ValueError("daily SQLite export is missing")
    return sorted(((path, relative) for relative, path in selected.items()), key=lambda item: item[1].encode("utf-8")), {
        "kind": "observation",
        "observation_date": date,
        "is_latest_observation": latest is not None,
        "latest_pointer": latest,
    }


def diagnostic_sources(args: argparse.Namespace) -> tuple[list[tuple[Path, str]], dict[str, object]]:
    runs = Path(args.runs_root)
    state = Path(args.state_root)
    date = args.date
    run = (runs / date).resolve(strict=True)
    if run.parent != runs.resolve() or not run.is_dir() or run.is_symlink():
        raise ValueError("diagnostic run path is not a direct real child of runs root")
    if (state / f"{date}.done.json").exists():
        raise ValueError("completed run must use the observation archive path")
    selected = {
        f"data/runs/{date}/{path.relative_to(run).as_posix()}": path
        for path in regular_tree(run)
    }
    failure_root = state / "ingest-executions" / date
    if failure_root.is_dir() and not failure_root.is_symlink():
        for path in regular_tree(failure_root):
            selected[f"data/state/{path.relative_to(state).as_posix()}"] = path
    if not selected:
        raise ValueError("diagnostic run contains no retained evidence")
    return sorted(
        ((path, relative) for relative, path in selected.items()),
        key=lambda item: item[1].encode("utf-8"),
    ), {
        "kind": "diagnostic",
        "run_date": date,
        "publishable": False,
    }


def copy_regular_tree(source: Path, destination: Path, *, exclude_locks: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for path in regular_tree(source):
        relative = path.relative_to(source)
        if exclude_locks and (path.name.endswith((".lock", ".tmp", ".partial")) or ".partial-" in path.name):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = path.stat()
        shutil.copy2(path, target)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise RuntimeError(f"source changed during control snapshot: {path}")
        if sha256_file(path) != sha256_file(target):
            raise RuntimeError(f"control snapshot hash mismatch: {path}")


def sqlite_backup(source: Path, destination: Path) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
    with closing(sqlite3.connect(f"file:{destination.as_posix()}?mode=ro&immutable=1", uri=True)) as check:
        quick = check.execute("PRAGMA quick_check").fetchone()[0]
        tables = sorted(row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    if quick != "ok":
        raise ValueError("macro SQLite backup failed quick_check")
    return {"source": str(source), "path": "macro/local-macro.sqlite", "quick_check": quick, "tables": tables}


def write_command(path: Path, args: Sequence[str]) -> None:
    result = command(*args, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed while preparing control snapshot: {' '.join(args)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.stdout, encoding="utf-8", newline="\n")


def secret_metadata(paths: Iterable[Path]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted(set(paths)):
        record: dict[str, object] = {"path": str(path), "bytes_copied": False}
        try:
            info = path.lstat()
            record.update({"exists": True, "mode": oct(stat.S_IMODE(info.st_mode)), "uid": info.st_uid, "gid": info.st_gid})
            if stat.S_ISREG(info.st_mode) and not path.is_symlink():
                try:
                    record["sha256"] = sha256_file(path)
                except PermissionError:
                    record["sha256"] = None
                    record["digest_status"] = "INACCESSIBLE"
        except FileNotFoundError:
            record["exists"] = False
        except PermissionError:
            record.update({"exists": None, "metadata_status": "INACCESSIBLE"})
        result.append(record)
    return result


def prepare_control(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    root = Path(tempfile.mkdtemp(prefix="ar-local-laptop-backup-", dir="/dev/shm"))
    os.chmod(root, 0o700)
    try:
        state = Path(args.state_root)
        copy_regular_tree(state, root / "data/state", exclude_locks=True)
        repositories = []
        for label, configured in (("AR-local", args.production_repo), ("australianrates", args.site_repo)):
            repo = canonical_root(configured, f"{label} repo")
            current = repo_state(repo)
            if not current["clean"]:
                raise ValueError(f"{label} checkout is dirty")
            bundle = root / f"git/{label}.bundle"
            bundle.parent.mkdir(parents=True, exist_ok=True)
            command("git", "-C", str(repo), "bundle", "create", str(bundle), "--all")
            current["bundle_path"] = f"git/{label}.bundle"
            current["bundle_sha256"] = sha256_file(bundle)
            repositories.append(current)
        for unit in ("ar-local-daily.service", "ar-local-daily.timer", "ar-local-status.service"):
            write_command(root / f"system/systemd/{unit}.txt", ("systemctl", "cat", unit))
            write_command(root / f"system/systemd/{unit}.show.txt", ("systemctl", "show", unit))
        write_command(root / "system/packages.tsv", ("dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n"))
        secret_paths = list(Path("/etc/ar-local").glob("*.env"))
        secret_paths.extend((Path.home() / ".ssh", Path(args.state_root).parent / "netdata/lib/bearer_tokens"))
        metadata = {
            "schema_version": 1,
            "repositories": repositories,
            "secret_locations": secret_metadata(secret_paths),
            "hostname": command("hostname").stdout.strip(),
            "uname": command("uname", "-a").stdout.strip(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip(),
        }
        (root / "system/control-metadata.json").write_bytes(canonical_json_bytes(metadata))
        return root, {"kind": "control", "control": metadata}
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def prepare_macro(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    root = Path(tempfile.mkdtemp(prefix="ar-local-laptop-macro-", dir="/dev/shm"))
    os.chmod(root, 0o700)
    try:
        macro = Path(args.macro_db).resolve(strict=True)
        report = sqlite_backup(macro, root / "macro/local-macro.sqlite")
        return root, {"kind": "macro", "macro": report}
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def immutable_control_sources(args: argparse.Namespace) -> list[tuple[Path, str]]:
    selected: list[tuple[Path, str]] = []
    data_root = Path(args.state_root).parent
    for name in ("runs-archive", "predeploy"):
        optional = data_root / name
        if optional.is_dir() and not optional.is_symlink():
            selected.extend(
                (path, f"data/{name}/{path.relative_to(optional).as_posix()}")
                for path in regular_tree(optional)
            )
    return selected


def manifest_for(sources: Sequence[tuple[Path, str]], identity: Mapping[str, object], args: argparse.Namespace) -> dict[str, object]:
    seen: dict[str, str] = {}
    entries = [file_entry(path, relative, seen) for path, relative in sources]
    return {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "plan_document_id": args.plan_document_id,
        "plan_version": args.plan_version,
        "plan_git_commit": args.plan_git_commit,
        "plan_sha256": args.plan_sha256,
        "candidate_code_sha": args.candidate_code_sha,
        "protected_code_sha": args.expected_production_sha,
        **identity,
        "files": entries,
        "file_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
    }


def recheck_entries(sources: Sequence[tuple[Path, str]], entries: Sequence[Mapping[str, object]]) -> None:
    for (path, relative), entry in zip(sources, entries, strict=True):
        if relative != entry["path"]:
            raise RuntimeError("source and manifest order diverged")
        info = path.stat()
        expected = (entry["size"], entry["mtime_ns"], entry["sha256"])
        normalized_mtime = (info.st_mtime_ns // 1_000_000_000) * 1_000_000_000
        actual = (info.st_size, normalized_mtime, sha256_file(path))
        if actual != expected:
            raise RuntimeError(f"source changed while streaming: {path}")


def stream_tar(sources: Sequence[tuple[Path, str]]) -> None:
    zstd_args = ("ionice", "-c2", "-n7", "nice", "-n", "10", "zstd", "-3", "-T2", "--stdout", "--quiet")
    compressor = subprocess.Popen(zstd_args, stdin=subprocess.PIPE, stdout=sys.stdout.buffer, stderr=subprocess.PIPE)
    assert compressor.stdin is not None
    try:
        with tarfile.open(fileobj=compressor.stdin, mode="w|", format=tarfile.GNU_FORMAT) as archive:
            for path, relative in sources:
                info = archive.gettarinfo(str(path), arcname=relative)
                if not info.isfile():
                    raise ValueError(f"source is not a regular file: {path}")
                info.mtime = int(info.mtime)
                with path.open("rb") as payload:
                    archive.addfile(info, payload)
        compressor.stdin.close()
        compressor_error = (compressor.stderr.read() if compressor.stderr else b"").decode("utf-8", "replace")
        compressor_code = compressor.wait()
    except BaseException:
        compressor.kill()
        raise
    if compressor_code:
        raise RuntimeError(f"archive pipeline failed: zstd={compressor_code} {compressor_error}")


def retained_runs(args: argparse.Namespace) -> list[dict[str, object]]:
    runs = Path(args.runs_root)
    state = Path(args.state_root)
    values = []
    for run in sorted(runs.iterdir()):
        if not run.is_dir() or run.is_symlink() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", run.name):
            continue
        completed = (state / f"{run.name}.done.json").is_file()
        values.append({"date": run.name, "status": "completed" if completed else "diagnostic"})
    return values


def latest_observation_identity(args: argparse.Namespace, inventory: Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    completed = [str(item["date"]) for item in inventory if item.get("status") == "completed"]
    if not completed:
        return None
    date = completed[-1]
    state = Path(args.state_root)
    done = state / f"{date}.done.json"
    if not done.is_file() or done.is_symlink():
        raise ValueError("latest completion marker is missing or unsafe")
    pointer = state / "observation-pointers-v2/latest-observation.json"
    result: dict[str, object] = {
        "observation_date": date,
        "completion_marker_sha256": sha256_file(done),
        "pointer_sha256": None,
    }
    if pointer.is_file() and not pointer.is_symlink():
        value = json_object(pointer)
        if value.get("observation_date") == date:
            result["pointer_sha256"] = sha256_file(pointer)
    return result


def prepared_sources(args: argparse.Namespace, kind: str) -> tuple[list[tuple[Path, str]], dict[str, object], Path | None]:
    temporary: Path | None = None
    if kind == "observation":
        sources, identity = observation_sources(args)
    elif kind == "diagnostic":
        sources, identity = diagnostic_sources(args)
    elif kind == "control":
        temporary, identity = prepare_control(args)
        sources = [(path, path.relative_to(temporary).as_posix()) for path in regular_tree(temporary)]
        sources.extend(immutable_control_sources(args))
        sources.sort(key=lambda item: item[1].encode("utf-8"))
    else:
        temporary, identity = prepare_macro(args)
        sources = [(path, path.relative_to(temporary).as_posix()) for path in regular_tree(temporary)]
    return sources, identity, temporary


def content_revision(manifest: Mapping[str, object]) -> str:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("component manifest lacks files")
    volatile_control_paths = {
        f"system/systemd/{unit}.show.txt"
        for unit in (
            "ar-local-daily.service",
            "ar-local-daily.timer",
            "ar-local-status.service",
        )
    }
    volatile_control_paths.update({
        "data/state/runtime_health.json",
        "git/AR-local.bundle",
        "git/australianrates.bundle",
        "system/control-metadata.json",
    })
    identity = [
        {"path": item["path"], "size": item["size"], "sha256": item["sha256"]}
        for item in files
        if isinstance(item, Mapping)
        and not (manifest.get("kind") == "control" and item.get("path") in volatile_control_paths)
    ]
    valid_files = [item for item in files if isinstance(item, Mapping)]
    if len(valid_files) != len(files):
        raise ValueError("component manifest contains an invalid file")
    material: object = identity
    if manifest.get("kind") == "control":
        control = manifest.get("control")
        if not isinstance(control, Mapping) or not isinstance(control.get("repositories"), list):
            raise ValueError("control manifest lacks semantic metadata")
        repositories = []
        for repository in control["repositories"]:
            if not isinstance(repository, Mapping):
                raise ValueError("control repository metadata is invalid")
            repositories.append({key: value for key, value in repository.items() if key != "bundle_sha256"})
        normalized_control = dict(control)
        normalized_control["repositories"] = repositories
        material = {"files": identity, "control": normalized_control}
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def component_identities(args: argparse.Namespace, inventory: Sequence[Mapping[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {"diagnostics": {}}
    prior_date = args.date
    try:
        for kind in ("control", "macro"):
            temporary: Path | None = None
            try:
                sources, identity, temporary = prepared_sources(args, kind)
                manifest = manifest_for(sources, identity, args)
                recheck_entries(sources, manifest["files"])
                result[kind] = {"content_revision": content_revision(manifest), "source_bytes": manifest["total_bytes"]}
            finally:
                if temporary is not None:
                    shutil.rmtree(temporary)
        diagnostics = result["diagnostics"]
        assert isinstance(diagnostics, dict)
        for item in inventory:
            if item.get("status") != "diagnostic":
                continue
            args.date = str(item["date"])
            sources, identity, _temporary = prepared_sources(args, "diagnostic")
            manifest = manifest_for(sources, identity, args)
            recheck_entries(sources, manifest["files"])
            diagnostics[args.date] = {"content_revision": content_revision(manifest), "source_bytes": manifest["total_bytes"]}
        return result
    finally:
        args.date = prior_date


def emit_stream(args: argparse.Namespace) -> int:
    preflight = production_preflight(args)
    temporary: Path | None = None
    try:
        sources, identity, temporary = prepared_sources(args, args.kind)
        manifest = manifest_for(sources, identity, args)
        manifest_bytes = canonical_json_bytes(manifest)
        header = {
            "protocol": PROTOCOL,
            "generated_at": datetime.now(WINDOW_TZ).isoformat(),
            "preflight": preflight,
            "manifest": manifest,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        }
        sys.stdout.buffer.write(canonical_json_bytes(header))
        sys.stdout.buffer.flush()
        stream_tar(sources)
        recheck_entries(sources, manifest["files"])
        return 0
    finally:
        if temporary is not None:
            resolved = temporary.resolve()
            if resolved.parent == Path("/dev/shm") and resolved.name.startswith(("ar-local-laptop-backup-", "ar-local-laptop-macro-")):
                shutil.rmtree(resolved)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("command", choices=("list", "stream"))
    value.add_argument("--kind", choices=("observation", "diagnostic", "control", "macro"), default="observation")
    value.add_argument("--date")
    value.add_argument("--runs-root", default="/srv/ar-local/data/runs")
    value.add_argument("--state-root", default="/srv/ar-local/data/state")
    value.add_argument("--production-repo", default="/srv/ar-local/AR-local")
    value.add_argument("--site-repo", default="/srv/ar-local/australianrates")
    value.add_argument("--macro-db", default="/srv/ar-local/AR-local/state/local-macro.sqlite")
    value.add_argument("--status-url", default="http://127.0.0.1:8808/api/status")
    value.add_argument("--expected-production-sha", required=True)
    value.add_argument("--candidate-code-sha", required=True)
    value.add_argument("--plan-document-id", required=True)
    value.add_argument("--plan-version", required=True)
    value.add_argument("--plan-git-commit", required=True)
    value.add_argument("--plan-sha256", required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        preflight = production_preflight(args)
        if args.command == "list":
            inventory = retained_runs(args)
            print(json.dumps({"ok": True, "preflight": preflight, "retained_runs": inventory, "completed_dates": [item["date"] for item in inventory if item["status"] == "completed"], "latest_observation": latest_observation_identity(args, inventory), "component_identities": component_identities(args, inventory)}, indent=2, sort_keys=True))
            return 0
        if args.kind in {"observation", "diagnostic"} and not args.date:
            raise ValueError("--date is required for run streams")
        return emit_stream(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "result": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
