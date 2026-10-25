"""Ingest archive identity: one verified object per observation generation.

Timer and backfill callers keep the date-level object. A same-day ingest
upload names a revision separately and can continue after the Hobart quiet
window without uploading during it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from ar_local_ingest_schedule import DAILY_INGEST_TZ
from pi_daily_cdr_day_archive_scope import require_day

SCHEMA = "ar-local-daily-cdr-raw-record-v1"
GENERATION_RE = re.compile(r"^obs-\d{4}-\d{2}-\d{2}-[0-9a-f]{16}$")


PRODUCTION_DAY_ARCHIVE_ENV = Path("/etc/ar-local/day-archive.env")
PRODUCTION_DAY_ARCHIVE_SPOOL = "/var/lib/ar-local-day-archives"
PRODUCTION_DAY_ARCHIVE_RCLONE = (
    "/var/lib/ar-local-drive-backup/credentials/"
    "dedicated-20260913-ready3/rclone-verified-ready3.conf"
)
PRODUCTION_DAY_ARCHIVE_REMOTE_PREFIX = "ar_local_drive_dedicated_20260913:"


def _clear_inherited_day_archive_env() -> None:
    """Drop inherited archive settings so a canary env cannot partially override production."""
    for key in list(os.environ):
        if key.startswith("AR_LOCAL_DAY_ARCHIVE") or key == "RCLONE_CONFIG":
            os.environ.pop(key, None)


def _parse_day_archive_env_file(env_path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("AR_LOCAL_") or key == "RCLONE_CONFIG":
            parsed[key] = value.strip().strip("\"'")
    return parsed


def _validate_canary_day_archive_env(parsed: dict[str, str]) -> None:
    """Fail closed before mutating os.environ so isolation settings survive rejection."""
    spool = parsed.get("AR_LOCAL_DAY_ARCHIVE_SPOOL", "").strip()
    if not spool:
        raise ValueError("canary day-archive env must set AR_LOCAL_DAY_ARCHIVE_SPOOL")
    if spool.rstrip("/") == PRODUCTION_DAY_ARCHIVE_SPOOL.rstrip("/"):
        raise ValueError(
            "canary day-archive env must not use production archive spool "
            f"{PRODUCTION_DAY_ARCHIVE_SPOOL}"
        )
    remote = parsed.get("AR_LOCAL_DAY_ARCHIVE_REMOTE", "").strip()
    if not remote:
        raise ValueError(
            "canary day-archive env must set isolated AR_LOCAL_DAY_ARCHIVE_REMOTE"
        )
    if remote.startswith(PRODUCTION_DAY_ARCHIVE_REMOTE_PREFIX):
        raise ValueError(
            "canary day-archive env must not use production archive remote"
        )
    rclone = parsed.get("RCLONE_CONFIG", "").strip()
    if not rclone:
        raise ValueError("canary day-archive env must set isolated RCLONE_CONFIG")
    if rclone.replace("\\", "/").rstrip("/") == PRODUCTION_DAY_ARCHIVE_RCLONE.rstrip(
        "/"
    ):
        raise ValueError(
            "canary day-archive env must not use production RCLONE_CONFIG"
        )


def load_day_archive_env(path: Path | None = None) -> None:
    """Apply the archive env file so ingest uses the dedicated remote and config.

    Prefer ``AR_LOCAL_DAY_ARCHIVE_ENV`` when set so isolated canary/shadow runs
    cannot silently load production ``/etc/ar-local/day-archive.env``.

    When the override is set, fail closed on missing/symlink/incomplete env files
    and refuse production spool/remote/rclone inheritance. Validation runs before
    any ``os.environ`` mutation so a rejected canary env leaves isolation intact.
    """
    override = os.environ.get("AR_LOCAL_DAY_ARCHIVE_ENV", "").strip()
    if path is None:
        env_path = Path(override) if override else PRODUCTION_DAY_ARCHIVE_ENV
    else:
        env_path = path
    # Fail closed only when an isolated canary override is selected.
    canary_mode = bool(override)
    if not env_path.is_file() or env_path.is_symlink():
        if canary_mode:
            raise ValueError(
                f"canary day-archive env missing or symlink (fail-closed): {env_path}"
            )
        return
    parsed = _parse_day_archive_env_file(env_path)
    if canary_mode:
        _validate_canary_day_archive_env(parsed)
        _clear_inherited_day_archive_env()
        # Keep AR_LOCAL_DAY_ARCHIVE_ENV pointing at the canary file after clear.
        os.environ["AR_LOCAL_DAY_ARCHIVE_ENV"] = str(env_path)
    for key, value in parsed.items():
        os.environ[key] = value


def require_generation(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or GENERATION_RE.fullmatch(value) is None:
        raise ValueError("observation generation id is not obs-YYYY-MM-DD-<16 hex>")
    return value


def generation_progress(progress_file: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not progress_file.is_file():
        return found
    for line in progress_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        day = row.get("date")
        generation = row.get("generation_id")
        if isinstance(day, str) and isinstance(generation, str) and generation:
            found[f"{day}#{generation}"] = row
    return found


class StageMissing(ValueError):
    """The recorded capture stage is gone and this generation has no PASS."""


def root_has_files(path: Path) -> bool:
    if not path.is_dir() or path.is_symlink():
        return False
    return any(item.is_file() for item in path.rglob("*"))


def cached_generation_upload(
    progress_file: Path,
    day: str,
    generation_id: str,
    stage_roots: list[Path] | None,
    fingerprint: str,
) -> dict | None:
    """Return a reusable PASS, or None when a new upload is required."""
    prior = generation_progress(progress_file).get(f"{day}#{generation_id}")
    roots = list(stage_roots or [])
    has_files = any(root_has_files(path) for path in roots)
    passed = bool(prior and prior.get("result") == "PASS")
    any_missing = any((not path.is_dir()) or path.is_symlink() for path in roots)
    if any_missing and not passed:
        raise StageMissing("capture stage missing before a verified archive")
    if passed and roots and not has_files:
        return prior
    if passed and prior.get("source_fingerprint") == fingerprint:
        return prior
    if roots and not has_files and any((not path.is_dir()) or path.is_symlink() for path in roots):
        raise StageMissing("capture stage missing before a verified archive")
    return None


def generation_has_pass(progress_file: Path, day: str, generation_id: str | None) -> bool:
    if not generation_id:
        return False
    row = generation_progress(progress_file).get(f"{day}#{generation_id}")
    return bool(row and row.get("result") == "PASS")


def _sidecar_stem(remote_name: str) -> str:
    if remote_name.endswith(".tar.zst"):
        return remote_name[: -len(".tar.zst")]
    if remote_name.endswith(".GAP.json"):
        return remote_name[: -len(".GAP.json")]
    return remote_name


def _retarget_sidecar(path: Path, remote_name: str, suffix: str, body: str | None = None) -> Path:
    """Upload a generation-named copy and leave the date-named workspace file."""
    target = path.with_name(_sidecar_stem(remote_name) + suffix)
    if target == path:
        if body is not None:
            path.write_text(body, encoding="utf-8")
        return path
    if body is not None:
        target.write_text(body, encoding="utf-8")
    else:
        shutil.copyfile(path, target)
    return target


def bind_generation_remote(day: str, built: dict, generation_id: str, prior_day: dict | None, transport) -> None:
    canonical = f"{day}.GAP.json" if built.get("kind") == "gap" else f"{day}.tar.zst"
    taken = bool(transport is not None and transport.remote_exists(canonical))
    remote_name = remote_name_for_generation(
        day, kind=str(built.get("kind") or "day"), generation_id=generation_id,
        prior_day=prior_day, canonical_taken=taken,
    )
    built["remote_name"] = remote_name
    if remote_name == canonical:
        return
    if built.get("sha_path"):
        sha = Path(built["sha_path"])
        built["sha_path"] = str(_retarget_sidecar(
            sha, remote_name, ".sha256", f"{built.get('sha256', '')}  {remote_name}\n",
        ))
    if built.get("manifest_path"):
        built["manifest_path"] = str(_retarget_sidecar(Path(built["manifest_path"]), remote_name, ".manifest.json"))


def remote_name_for_generation(
    day: str,
    *,
    kind: str,
    generation_id: str | None,
    prior_day: dict | None,
    canonical_taken: bool,
) -> str:
    suffix = ".GAP.json" if kind == "gap" else ".tar.zst"
    canonical = f"{day}{suffix}"
    if not generation_id:
        return canonical
    suffixed = f"{day}.{generation_id}{suffix}"
    if prior_day and prior_day.get("result") == "PASS":
        owner = prior_day.get("generation_id")
        if owner not in (None, generation_id):
            return suffixed
        if owner == generation_id and isinstance(prior_day.get("remote_name"), str):
            return str(prior_day["remote_name"])
    if canonical_taken:
        return suffixed
    return canonical


def continuation_path(spool: Path, day: str, generation_id: str) -> Path:
    return Path(spool) / "requests" / f"{day}.{generation_id}.ingest-continuation.json"


def quarantine_unrecoverable(spool: Path, day: str, generation_id: str | None) -> None:
    """Move a continuation that can never upload so later requests can drain."""
    if not generation_id:
        return
    source = continuation_path(spool, day, generation_id)
    if not source.exists():
        return
    blocked = Path(spool) / "blocked"
    blocked.mkdir(parents=True, exist_ok=True)
    source.replace(blocked / source.name)


def clear_archive_requests(spool: Path, day: str, generation_id: str | None) -> None:
    (Path(spool) / "requests" / f"{day}.json").unlink(missing_ok=True)
    if generation_id:
        continuation_path(spool, day, generation_id).unlink(missing_ok=True)


def enqueue_ingest_continuation(
    day: str,
    *,
    spool: Path,
    generation_id: str,
    stage_roots: list[Path],
    data_root: Path,
    state_dir: Path | None = None,
    runs_root: Path | None = None,
    clean_ram_stage: bool | None = None,
) -> Path:
    day = require_day(day)
    generation = require_generation(generation_id)
    if generation is None:
        raise ValueError("quiet-window continuation requires a generation id")
    path = continuation_path(spool, day, generation)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    payload = {
        "schema": SCHEMA,
        "date": day,
        "continue_same_day": True,
        "generation_id": generation,
        "stage_roots": [str(Path(root).resolve()) for root in stage_roots],
        "data_root": str(Path(data_root).resolve()),
        "state_dir": None if state_dir is None else str(Path(state_dir).resolve()),
        "runs_root": None if runs_root is None else str(Path(runs_root).resolve()),
        "clean_ram_stage": True if clean_ram_stage is None else bool(clean_ram_stage),
        "reason": "archive-retry",
        "requested_at": datetime.now(tz=DAILY_INGEST_TZ).isoformat(),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _absolute_path(value: object) -> Path | None:
    if not isinstance(value, str) or ".." in Path(value).parts:
        return None
    path = Path(value)
    if not path.is_absolute():
        return None
    return path


def _continuation_job(body: dict, day: str) -> dict | None:
    generation = body.get("generation_id")
    if not isinstance(generation, str):
        return None
    try:
        require_generation(generation)
    except ValueError:
        return None
    roots: list[Path] = []
    for item in body.get("stage_roots") or []:
        stage = _absolute_path(item)
        if stage is None:
            return None
        roots.append(stage)
    data_root = _absolute_path(body.get("data_root"))
    if data_root is None or not roots:
        return None
    job = {
        "day": day,
        "allow_same_day": True,
        "generation_id": generation,
        "stage_roots": roots,
        "data_root": data_root,
    }
    for key in ("state_dir", "runs_root"):
        found = _absolute_path(body.get(key))
        if found is not None:
            job[key] = found
    if "clean_ram_stage" in body:
        job["clean_ram_stage"] = bool(body.get("clean_ram_stage"))
    return job


def pending_archive_jobs(spool: Path, *, today: str, quiet: bool) -> list[dict]:
    """Return one job. Ingest continuations run only outside the quiet window."""
    requests_dir = Path(spool) / "requests"
    if not requests_dir.is_dir():
        return []
    continuation = None
    historical = None
    for marker in sorted(requests_dir.glob("*.json")):
        try:
            body = json.loads(marker.read_text(encoding="utf-8"))
            day = require_day(body["date"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError, TypeError):
            continue
        if body.get("continue_same_day") is True:
            if quiet or continuation is not None:
                continue
            continuation = _continuation_job(body, day)
            continue
        if day == today or historical is not None:
            continue
        historical = {"day": day, "allow_same_day": False}
    if continuation is not None:
        return [continuation]
    if historical is not None:
        return [historical]
    return []
