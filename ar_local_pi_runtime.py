"""Raspberry Pi runtime defaults and low-write helpers for AR-local."""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from ar_local_platform import HostKind, host_kind

PI_PORTABLE_ROOT = Path("/srv/ar-local")
PI_REPO_ROOT = PI_PORTABLE_ROOT / "AR-local"
PI_SITE_REPO = PI_PORTABLE_ROOT / "australianrates"
PI_SITE_ROOT = PI_SITE_REPO / "site"
PI_DATA_ROOT = PI_PORTABLE_ROOT / "data"
_UID_SUFFIX = os.getuid() if hasattr(os, "getuid") else "shared"
PI_RAM_ROOT = Path(os.environ.get("AR_LOCAL_RAM_ROOT", f"/dev/shm/ar-local-{_UID_SUFFIX}"))
PI_DASHBOARD_HOST = "0.0.0.0"
PI_DASHBOARD_PORT = 8808
PI_DASHBOARD_PROXY_PORT = 80
# Operational Tailscale IP from docs/UNIVERSAL_ROADMAP.md (override via AR_PI_TAILSCALE_IP / AR_PI_BASE_URL).
PI_TAILSCALE_IP = (os.environ.get("AR_PI_TAILSCALE_IP", "100.78.28.10") or "100.78.28.10").strip()
_pi_base_url = (os.environ.get("AR_PI_BASE_URL", "") or "").strip().rstrip("/")
PI_PUBLIC_BASE_URL = f"{_pi_base_url}/" if _pi_base_url else f"http://{PI_TAILSCALE_IP}/"
ENV_PORTABLE_ROOT = "AR_LOCAL_PORTABLE_ROOT"
ENV_DATA_ROOT = "AR_LOCAL_DATA_ROOT"


def is_raspberry_pi() -> bool:
    return host_kind() == HostKind.RASPBERRY_PI


def default_ram_root() -> Path:
    return Path(os.environ.get("AR_LOCAL_RAM_ROOT", str(PI_RAM_ROOT))).expanduser().resolve()


def data_root(repo_root: Path) -> Path:
    configured = os.environ.get(ENV_DATA_ROOT, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    configured_portable = os.environ.get(ENV_PORTABLE_ROOT, "").strip()
    if configured_portable:
        return (Path(configured_portable).expanduser().resolve() / "data").resolve()
    if is_raspberry_pi():
        return PI_DATA_ROOT
    return repo_root.expanduser().resolve()


def data_runs_root(repo_root: Path) -> Path:
    return data_root(repo_root) / "runs"


def data_state_root(repo_root: Path) -> Path:
    return data_root(repo_root) / "state"


def ensure_runtime_data_writable(repo_root: Path) -> None:
    """Fail early when the configured runtime data tree cannot be written by this user."""
    root = data_root(repo_root)
    for path in (root, data_runs_root(repo_root), data_state_root(repo_root)):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"runtime data path is not creatable: {path}: {exc}") from exc
        probe = path / f".write-probe-{os.getpid()}"
        try:
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise RuntimeError(
                f"runtime data path is not writable by uid {os.getuid() if hasattr(os, 'getuid') else 'unknown'}: {path}: {exc}",
            ) from exc


def prepare_empty_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copytree_atomic(src: Path, dst: Path) -> None:
    """Copy a completed tree into place with a same-parent final rename."""
    src = src.resolve()
    dst = dst.resolve()
    if dst.exists() and tree_contents_equal(src, dst):
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.tmp-{os.getpid()}-{int(time.time())}"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp)
    if dst.exists():
        backup = dst.parent / f".{dst.name}.previous-{int(time.time())}"
        if backup.exists():
            shutil.rmtree(backup)
        dst.replace(backup)
        tmp.replace(dst)
        shutil.rmtree(backup)
        return
    tmp.replace(dst)


def tree_contents_equal(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir():
        return False
    left_files = sorted(p.relative_to(left) for p in left.rglob("*") if p.is_file())
    right_files = sorted(p.relative_to(right) for p in right.rglob("*") if p.is_file())
    if left_files != right_files:
        return False
    for rel in left_files:
        if not filecmp.cmp(left / rel, right / rel, shallow=False):
            return False
    return True


def manifest_banks_rate_count(manifest: Mapping[str, Any]) -> int:
    counts = manifest.get("banks_counts")
    if not isinstance(counts, Mapping):
        banks = manifest.get("banks")
        counts = banks if isinstance(banks, Mapping) else {}
    try:
        return int(counts.get("rates") or 0)
    except (TypeError, ValueError):
        return 0


def export_manifest_is_valid(manifest: Mapping[str, Any]) -> bool:
    """A dashboard export is usable when banking rates were exported."""
    return manifest_banks_rate_count(manifest) > 0


def load_exports_manifest(exports_root: Path) -> Optional[dict[str, Any]]:
    exports_root = exports_root.expanduser().resolve()
    manifest_path = exports_root / "dashboard-cache" / "latest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def latest_exports_root(runs_root: Path) -> Optional[Path]:
    runs_root = runs_root.expanduser().resolve()
    if not runs_root.is_dir():
        return None
    candidates: list[tuple[str, Path]] = []
    for child in runs_root.iterdir():
        if not child.is_dir():
            continue
        exports = child / "_exports"
        manifest = load_exports_manifest(exports)
        if manifest is not None and export_manifest_is_valid(manifest):
            candidates.append((child.name, exports))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[-1][1].resolve()
