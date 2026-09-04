"""Shared Pi service restart helpers (status API, nginx, tailscaled)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SUBPROCESS_TIMEOUT_SEC = 120

STATUS_UNIT = "ar-local-status.service"
NGINX_UNIT = "nginx.service"
TAILSCALED_UNIT = "tailscaled.service"


def _run(cmd: list[str], *, dry_run: bool = False) -> tuple[int, str, str]:
    if dry_run:
        print(f"ar_local_pi_service_heal: dry-run {cmd!r}")
        return 0, "", ""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SEC,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def nginx_config_present() -> bool:
    return Path("/etc/nginx/sites-enabled/ar-local-status").is_file()


def restart_status(*, dry_run: bool = False) -> int:
    code, _, err = _run(["sudo", "systemctl", "restart", STATUS_UNIT], dry_run=dry_run)
    if code != 0:
        print(f"ar_local_pi_service_heal: restart {STATUS_UNIT} failed: {err}", file=sys.stderr)
    else:
        print(f"ar_local_pi_service_heal: restarted {STATUS_UNIT}")
    return code


def reload_or_restart_nginx(*, dry_run: bool = False) -> int:
    if not nginx_config_present():
        install_proxy = REPO_ROOT / "deploy" / "pi" / "install-pi-status-proxy.sh"
        if install_proxy.is_file():
            code, _, err = _run(["sudo", "sh", str(install_proxy), str(REPO_ROOT)], dry_run=dry_run)
            if code != 0:
                print(f"ar_local_pi_service_heal: install nginx proxy failed: {err}", file=sys.stderr)
            return code
        print("ar_local_pi_service_heal: nginx proxy not installed", file=sys.stderr)
        return 1
    code, _, err = _run(["sudo", "nginx", "-t"], dry_run=dry_run)
    if code != 0:
        print(f"ar_local_pi_service_heal: nginx -t failed: {err}", file=sys.stderr)
        return code
    code, _, err = _run(["sudo", "systemctl", "reload-or-restart", NGINX_UNIT], dry_run=dry_run)
    if code != 0:
        print(f"ar_local_pi_service_heal: reload-or-restart {NGINX_UNIT} failed: {err}", file=sys.stderr)
    else:
        print(f"ar_local_pi_service_heal: reloaded {NGINX_UNIT}")
    return code


def restart_status_and_nginx(*, dry_run: bool = False) -> int:
    """Restart the status API and reload or restart its nginx proxy."""
    rc = restart_status(dry_run=dry_run)
    if rc != 0:
        return rc
    return reload_or_restart_nginx(dry_run=dry_run)


def restart_tailscaled(*, dry_run: bool = False) -> int:
    code, _, err = _run(["sudo", "systemctl", "restart", TAILSCALED_UNIT], dry_run=dry_run)
    if code != 0:
        print(f"ar_local_pi_service_heal: restart {TAILSCALED_UNIT} failed: {err}", file=sys.stderr)
    else:
        print(f"ar_local_pi_service_heal: restarted {TAILSCALED_UNIT}")
    return code


def unit_is_active(unit: str) -> bool:
    code, out, _ = _run(["systemctl", "is-active", unit])
    return code == 0 and out in ("active", "activating")
