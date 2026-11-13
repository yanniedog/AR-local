"""Explicit, hash-bound operator extensions; never changes scheduled policy."""
from __future__ import annotations

import hashlib
import json
import re
import stat
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Hobart")
SCHEMA = "ar-local-operation-window-v1"
STAGES = {"quality-canary", "quality-seal", "quality-activate", "live-financial-capture"}


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("operator window timestamps require an explicit timezone")
    return parsed


def next_quiet(now: datetime) -> datetime:
    local = now.astimezone(TZ)
    boundary = local.replace(hour=0, minute=30, second=0, microsecond=0)
    return boundary if local < boundary else boundary + timedelta(days=1)


def validate(value: dict, *, now: datetime, target: str, operation: Path, stage: str) -> datetime:
    if now.tzinfo is None or not re.fullmatch(r"[0-9a-f]{40}", target):
        raise ValueError("aware current time and exact candidate required")
    if value.get("schema") != SCHEMA or value.get("target_commit") != target:
        raise ValueError("operator authorization does not identify this candidate")
    if value.get("timezone") != "Australia/Hobart" or stage not in STAGES:
        raise ValueError("unknown operator timezone or operation stage")
    stages, roots = value.get("stages"), value.get("operation_roots")
    if (not isinstance(stages, list) or not stages or any(not isinstance(s, str) or s not in STAGES for s in stages)
            or not isinstance(roots, list) or not roots or any(not isinstance(p, str) for p in roots)):
        raise ValueError("authorization stages and operation roots must be explicit string lists")
    if any(not Path(p).is_absolute() or Path(p).resolve() != Path(p) for p in roots):
        raise ValueError("authorization roots must be canonical absolute paths")
    if stage not in stages or str(operation) not in roots:
        raise ValueError("operator authorization does not cover this operation")
    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise ValueError("explicit operator decision must be recorded")
    issued, start, end = (timestamp(value[k]) for k in ("issued_at", "not_before", "expires_at"))
    if not issued <= start <= now < end or end - issued > timedelta(hours=4):
        raise ValueError("operator window is expired, future or longer than four hours")
    if end > next_quiet(issued) or time(0, 30) <= now.astimezone(TZ).time() < time(3, 30):
        raise ValueError("operator window must preserve the natural-ingest quiet window")
    return end


def load(reference: dict | None, *, now: datetime, target: str, operation: Path, stage: str) -> datetime | None:
    if reference is None:
        return None
    path = Path(reference["path"])
    expected = reference["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("independently retained authorization SHA256 required")
    info = path.lstat()
    if (not path.is_absolute() or path.resolve() != path or any(p.is_symlink() for p in path.parents)
            or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536):
        raise ValueError("canonical regular bounded authorization file required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("operator authorization bytes changed")
    return validate(json.loads(raw), now=now, target=target, operation=operation, stage=stage)


def reference(args) -> dict | None:
    path, digest = getattr(args, "window_authorization", None), getattr(args, "window_authorization_sha256", None)
    if bool(path) != bool(digest):
        raise ValueError("operator authorization requires both path and reviewed SHA256")
    return {"path": str(path), "sha256": digest} if path else None


def deadline(now: datetime, extension: datetime | None) -> datetime:
    return extension if extension is not None else now.astimezone(TZ).replace(hour=22, minute=0, second=0, microsecond=0)


def add_arguments(parser) -> None:
    parser.add_argument("--window-authorization", type=Path)
    parser.add_argument("--window-authorization-sha256")
