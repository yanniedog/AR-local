"""Durable daytime gap recovery owned by the Pi's existing daily watchdog.

Reservations precede network/process work and survive crashes. A successful
small GET permits one seeded, append-only same-day capture; it never clears a
failure or publishes a probe response as banking data.
"""

from __future__ import annotations

import errno
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, time as daytime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ar_local_pi_runtime import data_state_root
from cdr_atomic import atomic_write_json, canonical_json_bytes
from cdr_observation_selection import captured_identities, provider_directories, selected_observation
from cdr_recovery_legacy import legacy_recovery_requests, terminal_index_failure
from cdr_reuse_identity import captured_provider_directories
from pi_cdr_recovery_probe import current_target_url, probe_register, probe_request
from pi_cdr_selection_recovery import reconsider_saved_selection

HOBART = ZoneInfo("Australia/Hobart")
MAX_PROBES_PER_TICK = 4
MAX_PROBES_PER_DAY = 384
MAX_CAPTURES_PER_DAY = 4
PROBE_BUDGET_SECONDS = 60
CAPTURE_BUDGET_SECONDS = 30 * 60
CAPTURE_COOLDOWN_SECONDS = 60 * 60
UNCHANGED_PROOF_COOLDOWN_SECONDS = 2 * 60 * 60
MIN_FREE_BYTES = 8 * 1024 ** 3
CLEANUP_SECONDS = 45
EXPECTED_GENERATION_ENV = "AR_LOCAL_CDR_RECOVERY_GENERATION"


def recovery_window(now: datetime) -> bool:
    local = now.astimezone(HOBART)
    return daytime(3, 30) <= local.time() < daytime(22)


def capture_timeout(now: datetime) -> float:
    local = now.astimezone(HOBART)
    closing = local.replace(hour=22, minute=0, second=0, microsecond=0)
    return max(0.0, min(CAPTURE_BUDGET_SECONDS, (closing - local).total_seconds() - CLEANUP_SECONDS))


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("recovery timestamp lacks timezone")
    return result.astimezone(timezone.utc)


def _backup_source_active(proc_root: Path = Path("/proc")) -> bool:
    """Honor legacy read-only source processes that predate the shared lease.

    Once the ingest lock is held, a newly started legacy source rejects its own
    preflight. An already streaming source must finish before recovery starts.
    """
    if os.name != "posix" or not proc_root.is_dir():
        raise RuntimeError("Recovery requires the Pi process inventory")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RuntimeError("Recovery cannot verify backup source activity") from error
        names = {Path(arg.decode("utf-8", errors="replace")).name for arg in args if arg}
        if "pi_backup_foundation.py" in names:
            return True
        if {"pi_laptop_backup_source.py", "source.py"} & names and b"stream" in args:
            return True
    return False


def recovery_block_reason(repo_root: Path, *, include_ingest_lock: bool = True) -> str:
    state = data_state_root(repo_root)
    if include_ingest_lock and _lock_owner_may_be_active(state / "daily-ingest.lock"):
        return "production_ingest_or_backup_lock_active"
    try:
        status = subprocess.run(
            ["systemctl", "is-active", "ar-local-daily.service", "ar-local-ingest-now.service"],
            capture_output=True, text=True, check=False, shell=False, timeout=5,
        )
        values = [value.strip() for value in status.stdout.splitlines()]
        if any(value in {"active", "activating", "deactivating", "reloading"} for value in values):
            return "scheduled_or_manual_ingest_active"
        if len(values) != 2 or any(value not in {"inactive", "failed"} for value in values):
            return "ingest_service_activity_unavailable"
        if _backup_source_active():
            return "backup_source_active"
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return "production_activity_unavailable"
    return ""


def _lock_owner_may_be_active(path: Path) -> bool:
    """Read only: the production lock owner performs any stale reclamation."""
    if not path.exists():
        return False
    try:
        if path.is_symlink() or path.stat().st_size > 4096:
            return True
        values = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
        pid = int(values.get("pid", "0"))
        if pid <= 0:
            return True
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, ValueError):
        return True
    return True


def assert_recovery_start_safe(repo_root: Path) -> None:
    """Called inside the existing DailyIngestLock, before pausing the dashboard."""
    now = datetime.now(timezone.utc)
    if not recovery_window(now) or capture_timeout(now) < 60:
        raise RuntimeError("Same-day recovery is allowed only from 03:30 until the 22:00 Hobart cutoff")
    reason = recovery_block_reason(repo_root, include_ingest_lock=False)
    if reason:
        raise RuntimeError(f"Same-day recovery deferred: {reason}; the watchdog will recheck")
    if shutil.disk_usage(data_state_root(repo_root).parent).free < MIN_FREE_BYTES:
        raise RuntimeError("Same-day recovery deferred: less than 8 GiB free for an isolated revision")
    expected = os.environ.get(EXPECTED_GENERATION_ENV)
    if expected:
        selected = selected_observation(data_state_root(repo_root), now.astimezone(HOBART).date().isoformat())
        if not selected or selected["contract"]["generation_id"] != expected:
            raise RuntimeError("Same-day recovery source changed after its probe; the watchdog will replan")


def restore_dashboard_if_idle(repo_root: Path) -> dict:
    """Restore after termination without restarting serving during another ingest."""
    local = datetime.now(timezone.utc).astimezone(HOBART)
    if daytime(0, 30) <= local.time() < daytime(3, 30):
        return {"status": "deferred", "reason": "protected_natural_ingest_window"}
    reason = recovery_block_reason(repo_root)
    if reason:
        return {"status": "deferred", "reason": reason}
    # Lazy import avoids a cycle: the wrapper imports only our preflight helper.
    from pi_daily_sync import DailyIngestLock

    try:
        with DailyIngestLock(data_state_root(repo_root) / "daily-ingest.lock"):
            reason = recovery_block_reason(repo_root, include_ingest_lock=False)
            if reason:
                return {"status": "deferred", "reason": reason}
            subprocess.run(
                ["sudo", "-n", "systemctl", "start", "ar-local-dashboard.service"],
                check=True, shell=False, timeout=10,
            )
        return {"status": "restored"}
    except RuntimeError:
        return {"status": "deferred", "reason": "production_lock_changed"}
    except (OSError, subprocess.SubprocessError) as error:
        return {"status": "restoration_failed", "failure_category": type(error).__name__}


@contextmanager
def _recovery_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            yield False
            return
        yield True  # Descriptor close releases ownership; never unlink a lock.


def _history(root: Path, run_date: str) -> list[dict]:
    result = []
    for path in sorted(root.glob("*.reserved.json")):
        if len(result) >= MAX_PROBES_PER_DAY + MAX_CAPTURES_PER_DAY + 128 or path.stat().st_size > 64 * 1024:
            raise ValueError("recovery reservation inventory exceeds its budget")
        row = json.loads(path.read_bytes())
        if row.get("schema_version") != 1 or row.get("run_date") != run_date:
            raise ValueError("invalid durable recovery reservation")
        _timestamp(row["reserved_at"])
        result.append(row)
    return result


def _reserve(root: Path, run_date: str, generation: str, kind: str, now: datetime, **fields) -> dict:
    reservation = {
        "schema_version": 1, "reservation_id": uuid.uuid4().hex, "kind": kind,
        "run_date": run_date, "generation_id": generation, "reserved_at": now.isoformat(),
        **fields,
    }
    atomic_write_json(root / f"{reservation['reservation_id']}.reserved.json", reservation, create_once=True)
    return reservation


def _finish(root: Path, reservation: dict, report: dict) -> None:
    atomic_write_json(root / f"{reservation['reservation_id']}.result.json", {
        "schema_version": 1, "reservation_id": reservation["reservation_id"],
        "finished_at": datetime.now(timezone.utc).isoformat(), **report,
    }, create_once=True)


def _request_key(request: dict) -> str:
    return hashlib.sha256(canonical_json_bytes({key: request.get(key) for key in
        ("provider_dir", "phase", "product_id", "url")})).hexdigest()


def _legacy_requests(observation: dict, providers: dict) -> list[dict]:
    """A one-generation bridge for the prior bounded-recovery status format."""
    status = observation["status"]
    initial = (status.get("recovery") or {}).get("initial_failure_journal")
    expected = (status.get("recovery") or {}).get("initial_failure_sha256")
    if not isinstance(initial, str) or len(initial.encode("utf-8")) > 256 * 1024:
        return []
    if hashlib.sha256(initial.encode("utf-8")).hexdigest() != expected:
        raise ValueError("legacy recovery failure journal is not bound")
    present = captured_identities(observation)
    if present is None:
        return []
    result = []
    affected = status.get("by_provider") or {}
    for line in initial.splitlines():
        row = json.loads(line)
        provider, pid = str(row.get("bank") or ""), str(row.get("product_id") or "")
        phase = str(row.get("phase") or "")
        if provider not in providers or not affected.get(provider):
            continue
        if phase not in {"products_index", "product_detail", "classification_detail"}:
            continue
        if phase != "products_index" and (not pid or (provider, pid) in present):
            continue
        if (phase == "products_index"
                and (status.get("index_diagnostics") or {}).get(provider, {}).get("pagination_complete") is True
                and not terminal_index_failure(status, provider)):
            continue
        result.append({"provider_dir": provider, "phase": phase, "product_id": pid,
                       "url": row.get("url") or providers[provider]["endpoint_url"],
                       "status": row.get("status"), "failure_category": row.get("failure_category")})
    return result


def _requests(observation: dict, providers: dict, cache_root: Path) -> list[dict]:
    raw = observation["status"].get("unresolved_requests")
    if raw is None:
        if observation["status"].get("raw_attempt_journal"):
            raw = legacy_recovery_requests(observation, providers, cache_root)
        else:
            raw = _legacy_requests(observation, providers)
    if not isinstance(raw, list) or len(raw) > 8192:
        raise ValueError("unresolved recovery queue is invalid")
    requests = {}
    for row in raw:
        if (not isinstance(row, dict) or row.get("provider_dir") not in providers
                or row.get("phase") not in {"products_index", "product_detail", "classification_detail"}
                or (row.get("phase") != "products_index" and not row.get("product_id"))):
            raise ValueError("unresolved recovery request is invalid")
        requests[_request_key(row)] = dict(row, request_key=_request_key(row))
    return list(requests.values())


def _due_requests(requests: list[dict], history: list[dict], now: datetime) -> list[dict]:
    probes = [row for row in history if row["kind"] == "probe"]
    counts = Counter(row.get("request_key") for row in probes)
    by_provider: dict[str, list[dict]] = {}
    for request in requests:
        by_provider.setdefault(request["provider_dir"], []).append(request)
    candidates = []
    for provider, rows in by_provider.items():
        attempts = [row for row in probes if row.get("provider_dir") == provider]
        last = max((_timestamp(row["reserved_at"]) for row in attempts), default=None)
        wait_seconds = min(7200, 900 * 2 ** min(max(0, len(attempts) - 1), 3))
        if last is not None and (now - last).total_seconds() < wait_seconds:
            continue
        selected = min(rows, key=lambda row: (counts[row["request_key"]], row["request_key"]))
        candidates.append((last or datetime.min.replace(tzinfo=timezone.utc), provider,
                           dict(selected, version_offset=2 * len(attempts))))
    return [row for _, _, row in sorted(candidates)[:MAX_PROBES_PER_TICK]]


def _coverage_health(observation: dict) -> dict:
    status = observation["status"]
    return {
        "selected_generation_id": observation["contract"]["generation_id"],
        "selected_event_digest": observation["event"]["event_digest"],
        "observation_state": observation["contract"]["observation_state"],
        "failure_records": int(status.get("total") or 0),
        "failure_provenance_complete": status.get("failure_provenance_complete") is True,
        "provider_failures": dict(status.get("by_provider") or {}),
        "request_sample_complete": status.get("unresolved_requests_complete") is True,
        "products_captured": (observation["contract"].get("coverage") or {}).get("products_discovered"),
        "eligible_rate_rows": (observation["contract"].get("coverage") or {}).get("eligible_rate_rows"),
    }


def _schedule_health(requests: list[dict], history: list[dict], now: datetime) -> dict:
    probes = [row for row in history if row["kind"] == "probe"]
    captures = [row for row in history if row["kind"] == "capture"]
    next_times = []
    for provider in {row["provider_dir"] for row in requests}:
        attempts = [row for row in probes if row.get("provider_dir") == provider]
        last = max((_timestamp(row["reserved_at"]) for row in attempts), default=None)
        wait_seconds = min(7200, 900 * 2 ** min(max(0, len(attempts) - 1), 3))
        next_times.append(max(now, last + timedelta(seconds=wait_seconds)) if last else now)
    return {
        "queued_request_sample_count": len(requests),
        "probe_reservations_today": len(probes),
        "capture_reservations_today": len(captures),
        "capture_reservations_remaining": max(0, MAX_CAPTURES_PER_DAY - len(captures)),
        "next_provider_probe_at_utc": min(next_times).isoformat() if next_times else None,
    }


def _probe_due(root: Path, observation: dict, providers: dict, due: list[dict],
               history: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    local = datetime.now(timezone.utc).astimezone(HOBART)
    closing = local.replace(hour=22, minute=0, second=0, microsecond=0)
    remaining = max(0.0, (closing - local).total_seconds())
    if not recovery_window(local) or remaining <= 0:
        return [], []
    deadline = time.monotonic() + min(PROBE_BUDGET_SECONDS, remaining)
    run_date, generation = observation["contract"]["observation_date"], observation["contract"]["generation_id"]
    register_reservation = _reserve(root, run_date, generation, "register", now)
    registry, brands = probe_register(deadline=deadline)
    _finish(root, register_reservation, registry)
    if not registry["ok"]:
        return [], [{"phase": "register_discovery", **registry}]
    positive, reports = [], []
    for request in due:
        if time.monotonic() >= deadline:
            break
        reservation = _reserve(root, run_date, generation, "probe", now,
                               provider_dir=request["provider_dir"], request_key=request["request_key"])
        history.append(reservation)
        try:
            url = current_target_url(request, providers[request["provider_dir"]], brands)
            report = probe_request(url, phase=request["phase"],
                                   product_id=str(request.get("product_id") or ""), deadline=deadline,
                                   version_offset=request.get("version_offset", 0))
            report.pop("data", None)
        except (KeyError, ValueError, RuntimeError) as error:
            report = {"ok": False, "failure_category": type(error).__name__, "complete_capture": False}
        report.update(provider_dir=request["provider_dir"], request_key=request["request_key"],
                      phase=request["phase"], product_id=request.get("product_id"),
                      registry_body_sha256=registry.get("body_sha256"))
        _finish(root, reservation, report)
        reports.append(report)
        if report["ok"]:
            positive.append(dict(report, probe_reservation_id=reservation["reservation_id"]))
    return positive, reports


def _capture_allowed(history: list[dict], proofs: list[dict], now: datetime) -> tuple[bool, str]:
    captures = [row for row in history if row["kind"] == "capture"]
    if len(captures) >= MAX_CAPTURES_PER_DAY:
        return False, "daily_capture_budget_exhausted"
    if any((now - _timestamp(row["reserved_at"])).total_seconds() < CAPTURE_COOLDOWN_SECONDS for row in captures):
        return False, "capture_cooldown"
    signatures = {(proof["request_key"], proof["body_sha256"]) for proof in proofs}
    if signatures and all(any(
        pair in {(item["request_key"], item["body_sha256"]) for item in row.get("proofs", [])}
        and (now - _timestamp(row["reserved_at"])).total_seconds() < UNCHANGED_PROOF_COOLDOWN_SECONDS
        for row in captures) for pair in signatures):
        return False, "unchanged_successful_probe_cooldown"
    return True, ""


def _recover_locked(repo_root: Path, state: Path, now: datetime, launch: Callable) -> dict:
    run_date = now.astimezone(HOBART).date().isoformat()
    observation = selected_observation(state, run_date)
    if observation is None:
        return {"status": "no_verified_same_day_observation"}
    reconsidered = reconsider_saved_selection(repo_root, state, run_date, observation)
    if reconsidered:
        return reconsidered
    # Re-entry above can finish an interrupted selection. Once it has no more
    # work, settle any selected or older-date upload before spending probes or
    # a capture that could suppress the watchdog's publication retry.
    from pi_daily_sync import payload_publication_pending

    if payload_publication_pending(repo_root):
        return {"status": "pending_publication_must_settle", "publication_required": True,
                "capture_attempted": False}
    health = _coverage_health(observation)
    if observation["contract"]["observation_state"] == "complete":
        return {"status": "complete", **health}
    providers = captured_provider_directories(observation["status"], provider_directories(observation["status"]))
    root = state / "cdr-recovery-v1" / run_date
    requests = _requests(observation, providers, root)
    if not requests:
        return {"status": "unresolved_request_evidence_unavailable", **health}
    history = _history(root, run_date)
    health.update(_schedule_health(requests, history, now))
    registers = [row for row in history if row["kind"] == "register"]
    if any((now - _timestamp(row["reserved_at"])).total_seconds() < 900 for row in registers):
        return {"status": "register_probe_cooldown", **health}
    probe_count = sum(row["kind"] == "probe" for row in history)
    if probe_count >= MAX_PROBES_PER_DAY:
        return {"status": "daily_probe_budget_exhausted", **health}
    due = _due_requests(requests, history, now)[:MAX_PROBES_PER_DAY - probe_count]
    if not due:
        return {"status": "provider_cooldown", **health}
    positive, reports = _probe_due(root, observation, providers, due, history, now)
    health.update(_schedule_health(requests, history, datetime.now(timezone.utc)))
    if not positive:
        return {"status": "upstream_gaps_remain", "probes": reports, **health}
    allowed, reason = _capture_allowed(history, positive, now)
    if not allowed:
        return {"status": reason, "probes": reports, **health}
    # Recheck after networking. The wrapper repeats this inside the shared lease.
    latest = selected_observation(state, run_date)
    if not latest or latest["event"]["event_digest"] != observation["event"]["event_digest"]:
        return {"status": "selected_observation_changed", **health}
    current = datetime.now(timezone.utc)
    reason = recovery_block_reason(repo_root)
    if reason or not recovery_window(current) or capture_timeout(current) < 60:
        return {"status": reason or "recovery_window_closed", **health}
    timeout = capture_timeout(current)
    reservation = _reserve(root, run_date, observation["contract"]["generation_id"],
                           "capture", current, timeout_seconds=timeout, proofs=positive)
    history.append(reservation)
    report = {"status": "capture_finished", "capture_attempted": True, "probes": reports}
    try:
        launch(run_date, timeout, observation["contract"]["generation_id"])
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status="capture_failed", failure_category=type(error).__name__)
    _finish(root, reservation, report)
    selected = selected_observation(state, run_date)
    report.update(_coverage_health(selected or observation))
    current_requests = (selected or observation)["status"].get("unresolved_requests")
    report.update(_schedule_health(current_requests if isinstance(current_requests, list) else requests,
                                   history, datetime.now(timezone.utc)))
    report["selection_advanced"] = bool(selected and selected["event"]["event_digest"] != observation["event"]["event_digest"])
    return report


def run_same_day_recovery(repo_root: Path, *, now_utc: datetime, dry_run: bool,
                          launch: Callable[[str, float, str], None]) -> dict:
    """One watchdog tick. Dry runs perform no probes, reservations, or captures."""
    if not recovery_window(now_utc):
        return {"status": "outside_recovery_window", "window": "03:30-22:00 Australia/Hobart"}
    if dry_run:
        return {"status": "dry_run", "capture_attempted": False}
    reason = recovery_block_reason(repo_root)
    if reason:
        return {"status": reason}
    state = data_state_root(repo_root)
    try:
        with _recovery_lock(state / ".cdr-recovery.lock") as acquired:
            if not acquired:
                return {"status": "recovery_already_active"}
            try:
                report = _recover_locked(repo_root, state, now_utc, launch)
            except (KeyError, TypeError, ValueError, OSError, RuntimeError) as error:
                report = {"status": "recovery_evidence_unavailable",
                          "failure_category": type(error).__name__, "capture_attempted": False}
            report.update(schema_version=1, checked_at=datetime.now(timezone.utc).isoformat(),
                          run_date=now_utc.astimezone(HOBART).date().isoformat())
            atomic_write_json(state / "cdr-recovery-status.json", report)
            return report
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as error:
        return {"status": "recovery_evidence_unavailable", "failure_category": type(error).__name__,
                "capture_attempted": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-dashboard", action="store_true", required=True)
    parser.parse_args(argv)
    report = restore_dashboard_if_idle(Path(__file__).resolve().parent)
    print(json.dumps(report, sort_keys=True))
    return 1 if report["status"] == "restoration_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
