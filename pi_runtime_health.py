#!/usr/bin/env python3
"""Pi runtime health probes and self-heal (dashboard, nginx, tailscaled)."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ar_local_pi_runtime import (
    PI_DASHBOARD_PORT,
    PI_TAILSCALE_IP,
    data_state_root,
    ensure_runtime_data_writable,
    export_manifest_is_valid,
    is_raspberry_pi,
)
from ar_local_pi_service_heal import (
    restart_dashboard_and_nginx,
    restart_tailscaled,
    unit_is_active,
)

REPO_ROOT = Path(__file__).resolve().parent
STATE_NAME = "runtime_health.json"
PROBE_PATH = "/api/latest"
DEFAULT_PROBE_TIMEOUT_SEC = 15.0
DEFAULT_PROBE_RETRIES = 2
DEFAULT_FAIL_THRESHOLD = 3
DEFAULT_TAILSCALE_FAIL_THRESHOLD = 2
DEFAULT_HEAL_COOLDOWN_SEC = 300
DEFAULT_TAILSCALE_HEAL_COOLDOWN_SEC = 600
JOURNAL_LOOKBACK_SEC = 300
EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_CONFIG = 2


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat()


def state_path() -> Path:
    return data_state_root(REPO_ROOT) / STATE_NAME


def load_state() -> dict[str, Any]:
    path = state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    ensure_runtime_data_writable(REPO_ROOT)
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def probe_urls() -> tuple[str, ...]:
    return (
        f"http://127.0.0.1{PROBE_PATH}",
        f"http://127.0.0.1:{PI_DASHBOARD_PORT}{PROBE_PATH}",
    )


def http_probe(url: str, *, timeout: float, retries: int) -> tuple[bool, str]:
    last_err = "unknown"
    for attempt in range(max(1, retries + 1)):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if int(resp.status) != 200:
                    last_err = f"HTTP {resp.status}"
                    continue
                payload = json.loads(resp.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    last_err = "invalid JSON object"
                    continue
                if not export_manifest_is_valid(payload):
                    last_err = "manifest missing rates"
                    continue
                return True, f"OK run_date={payload.get('run_date')!r}"
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
        except Exception as exc:
            last_err = str(exc)
        if attempt < retries:
            time.sleep(0.5)
    return False, last_err


def run_http_probes(*, timeout: float, retries: int) -> tuple[bool, list[str]]:
    messages: list[str] = []
    all_ok = True
    for url in probe_urls():
        ok, detail = http_probe(url, timeout=timeout, retries=retries)
        messages.append(f"{url}: {detail}")
        if not ok:
            all_ok = False
    return all_ok, messages


def tailnet_ip() -> str:
    proc = subprocess.run(
        ["tailscale", "ip", "-4"],
        capture_output=True,
        text=True,
        shell=False,
        check=False,
        timeout=10,
    )
    if proc.returncode == 0:
        lines = (proc.stdout or "").strip().splitlines()
        if lines:
            return lines[0].strip()
    return PI_TAILSCALE_IP


def tcp_probe(host: str, port: int, *, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def tailscale_journal_unhealthy() -> tuple[bool, str]:
    proc = subprocess.run(
        ["journalctl", "-u", "tailscaled.service", "--since", f"{JOURNAL_LOOKBACK_SEC}s", "--no-pager", "-o", "cat"],
        capture_output=True,
        text=True,
        shell=False,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        return False, "journal unavailable"
    text = (proc.stdout or "").lower()
    patterns = ("derp-5", "magicsock", "receiveipv4", "derp send", "connection reset")
    hits = [p for p in patterns if p in text]
    if hits:
        return True, f"journal patterns: {', '.join(hits)}"
    return False, "journal clean"


def check_tailscale(*, http_timeout: float) -> tuple[bool, list[str]]:
    messages: list[str] = []
    if not unit_is_active("tailscaled.service"):
        messages.append("tailscaled.service not active")
        return False, messages
    ip = tailnet_ip()
    messages.append(f"tailnet ip={ip}")
    tailnet_http_ok = False
    if tcp_probe(ip, 80, timeout=min(http_timeout, 8.0)):
        ok, detail = http_probe(f"http://{ip}{PROBE_PATH}", timeout=http_timeout, retries=1)
        if ok:
            messages.append(f"tailnet HTTP: OK {detail}")
            tailnet_http_ok = True
        else:
            messages.append(f"tailnet HTTP failed: {detail}")
    else:
        messages.append(f"TCP :80 on {ip} failed")
    journal_bad, journal_detail = tailscale_journal_unhealthy()
    messages.append(f"journal: {journal_detail}")
    return tailnet_http_ok and not journal_bad, messages


def cooldown_elapsed(state: dict[str, Any], key: str, cooldown_sec: int) -> bool:
    raw = state.get(key)
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(str(raw))
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (_utc_now() - last).total_seconds() >= cooldown_sec


def cmd_check(args: argparse.Namespace) -> int:
    http_ok, http_msgs = run_http_probes(timeout=args.timeout, retries=args.retries)
    for line in http_msgs:
        print(f"pi_runtime_health: {line}")
    tail_ok: Optional[bool] = None
    if args.check_tailscale:
        tail_ok, tail_msgs = check_tailscale(http_timeout=args.timeout)
        for line in tail_msgs:
            print(f"pi_runtime_health: tailscale {line}")
    state = load_state()
    state["last_check_at"] = _utc_iso()
    state["http_fail_streak"] = 0 if http_ok else int(state.get("http_fail_streak") or 0) + 1
    if tail_ok is not None:
        state["tailscale_fail_streak"] = 0 if tail_ok else int(state.get("tailscale_fail_streak") or 0) + 1
    save_state(state)
    if http_ok and (tail_ok is None or tail_ok):
        print("pi_runtime_health: check OK")
        return EXIT_OK
    print(
        f"pi_runtime_health: check FAIL (http_streak={state.get('http_fail_streak')}, "
        f"tailscale_streak={state.get('tailscale_fail_streak')})",
        file=sys.stderr,
    )
    return EXIT_UNHEALTHY


def cmd_heal(args: argparse.Namespace) -> int:
    http_ok, http_msgs = run_http_probes(timeout=args.timeout, retries=args.retries)
    for line in http_msgs:
        print(f"pi_runtime_health: {line}")
    tail_ok, tail_msgs = check_tailscale(http_timeout=args.timeout)
    for line in tail_msgs:
        print(f"pi_runtime_health: tailscale {line}")
    state = load_state()
    state["last_check_at"] = _utc_iso()
    state["http_fail_streak"] = 0 if http_ok else int(state.get("http_fail_streak") or 0) + 1
    state["tailscale_fail_streak"] = 0 if tail_ok else int(state.get("tailscale_fail_streak") or 0) + 1
    healed = False
    http_streak = int(state.get("http_fail_streak") or 0)
    if not http_ok and http_streak >= args.fail_threshold:
        if cooldown_elapsed(state, "last_http_heal_at", args.heal_cooldown):
            print(f"pi_runtime_health: HTTP fail streak {http_streak}; restarting dashboard + nginx")
            if restart_dashboard_and_nginx(dry_run=args.dry_run) != 0:
                save_state(state)
                return EXIT_UNHEALTHY
            state["last_http_heal_at"] = _utc_iso()
            state["http_fail_streak"] = 0
            healed = True
            if not args.dry_run:
                time.sleep(3)
                http_ok, http_msgs = run_http_probes(timeout=args.timeout, retries=args.retries)
                for line in http_msgs:
                    print(f"pi_runtime_health: post-heal {line}")
        else:
            print("pi_runtime_health: HTTP heal skipped (cooldown)", file=sys.stderr)
    tail_streak = int(state.get("tailscale_fail_streak") or 0)
    if not tail_ok and tail_streak >= args.tailscale_fail_threshold:
        if cooldown_elapsed(state, "last_tailscale_heal_at", args.tailscale_heal_cooldown):
            print(f"pi_runtime_health: tailscale fail streak {tail_streak}; restarting tailscaled")
            if restart_tailscaled(dry_run=args.dry_run) != 0:
                save_state(state)
                return EXIT_UNHEALTHY
            state["last_tailscale_heal_at"] = _utc_iso()
            state["tailscale_fail_streak"] = 0
            healed = True
        else:
            print("pi_runtime_health: tailscale heal skipped (cooldown)", file=sys.stderr)
    save_state(state)
    if http_ok and tail_ok:
        print("pi_runtime_health: heal OK (healthy)")
        return EXIT_OK
    if healed:
        print("pi_runtime_health: heal applied; re-check on next timer tick")
        return EXIT_OK
    print("pi_runtime_health: still unhealthy (below heal threshold or cooldown)", file=sys.stderr)
    return EXIT_UNHEALTHY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pi runtime HTTP probes and self-heal.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=DEFAULT_PROBE_TIMEOUT_SEC)
    parser.add_argument("--retries", type=int, default=DEFAULT_PROBE_RETRIES)
    parser.add_argument("--fail-threshold", type=int, default=DEFAULT_FAIL_THRESHOLD)
    parser.add_argument("--tailscale-fail-threshold", type=int, default=DEFAULT_TAILSCALE_FAIL_THRESHOLD)
    parser.add_argument("--heal-cooldown", type=int, default=DEFAULT_HEAL_COOLDOWN_SEC)
    parser.add_argument("--tailscale-heal-cooldown", type=int, default=DEFAULT_TAILSCALE_HEAL_COOLDOWN_SEC)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--heal", action="store_true")
    parser.add_argument("--check-tailscale", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.heal:
        args.check_tailscale = True
    if args.check and not args.check_tailscale and not is_raspberry_pi():
        args.check_tailscale = False
    if args.check:
        return cmd_check(args)
    if args.heal:
        return cmd_heal(args)
    return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
