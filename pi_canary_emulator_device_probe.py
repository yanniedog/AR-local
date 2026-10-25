#!/usr/bin/env python3
"""Fail-closed emulator/device probe for canary gates (never invents PASS).

Inventories local Android SDK AVDs and adb devices. Emits UNKNOWN receipts
unless a caller supplies a real lab/CI receipt to canonicalize elsewhere.
Does not start emulators or install APKs by default (use --attempt-boot only
with an explicit APK path bound to target_commit).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

COMMIT_RE = __import__("re").compile(r"^[0-9a-f]{40}$")


class ProbeError(ValueError):
    """Probe cannot be written honestly."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    if path.exists() or path.is_symlink():
        raise ProbeError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(payload), sort_keys=True, indent=2) + "\n").encode("utf-8")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(raw)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return hashlib.sha256(raw).hexdigest()


def _run(cmd: Sequence[str], timeout: int = 30) -> dict[str, Any]:
    """Run an argv list (never shell=True). Callers pass SDK-local binaries only."""
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
        return {
            "cmd": list(cmd),
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-8000:],
            "stderr": (proc.stderr or "")[-4000:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"cmd": list(cmd), "error": f"{type(exc).__name__}:{exc}"}


def discover_sdk() -> Path:
    env = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if env:
        return Path(env)
    candidates = (
        Path.home() / "AppData" / "Local" / "Android" / "Sdk",  # Windows
        Path.home() / "Library" / "Android" / "sdk",  # macOS
        Path.home() / "Android" / "Sdk",  # Linux
        Path("/usr/lib/android-sdk"),
        Path("/opt/android-sdk"),
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise ProbeError("Android SDK not found (set ANDROID_HOME)")


def list_avds(sdk: Path) -> list[str]:
    emu = sdk / "emulator" / "emulator.exe"
    if not emu.is_file():
        emu = sdk / "emulator" / "emulator"
    if not emu.is_file():
        return []
    out = _run([str(emu), "-list-avds"])
    text = out.get("stdout") or ""
    return [line.strip() for line in text.splitlines() if line.strip()]


def list_adb_devices(sdk: Path) -> list[dict[str, str]]:
    adb = sdk / "platform-tools" / "adb.exe"
    if not adb.is_file():
        adb = sdk / "platform-tools" / "adb"
    if not adb.is_file():
        return []
    out = _run([str(adb), "devices", "-l"])
    devices: list[dict[str, str]] = []
    for line in (out.get("stdout") or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append({"serial": parts[0], "state": parts[1], "raw": line})
    return devices


def inventory_apks(
    roots: Sequence[Path],
    *,
    max_files: int = 20,
    max_depth: int = 4,
) -> list[dict[str, Any]]:
    """Shallow APK inventory for fail-closed classification (never implies PASS)."""
    found: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        root = root.resolve()
        for dirpath, dirnames, filenames in os.walk(root):
            rel = Path(dirpath).resolve().relative_to(root)
            depth = len(rel.parts)
            if depth > max_depth:
                dirnames.clear()
                continue
            # Skip heavy trees
            skip = {
                "node_modules",
                ".git",
                ".expo",
                "android",
                "ios",
                "__pycache__",
                ".tox",
            }
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            for name in filenames:
                if not name.lower().endswith(".apk"):
                    continue
                path = Path(dirpath) / name
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    size = path.stat().st_size
                    # Hash only first 1 MiB + size for cheap identity (not claim of integrity).
                    with path.open("rb") as fh:
                        prefix = fh.read(1024 * 1024)
                    digest = hashlib.sha256(prefix + str(size).encode()).hexdigest()
                except OSError:
                    continue
                found.append(
                    {
                        "path": str(path),
                        "bytes": size,
                        "prefix_sha256": digest,
                        "bound_to_target": False,
                        "reason": "inventory only; not stamped as TARGET_SHA candidate APK",
                    }
                )
                if len(found) >= max_files:
                    return found
    return found


def probe(
    *,
    target_commit: str,
    output: Path,
    apk_path: Optional[Path] = None,
    apk_inventory_roots: Optional[Sequence[Path]] = None,
    replace_output: bool = False,
) -> dict[str, Any]:
    if not COMMIT_RE.fullmatch(target_commit):
        raise ProbeError("target_commit must be 40 lowercase hex")
    findings: list[str] = []
    try:
        sdk = discover_sdk()
    except ProbeError as exc:
        sdk = None
        findings.append(str(exc))
    avds = list_avds(sdk) if sdk else []
    devices = list_adb_devices(sdk) if sdk else []
    physical = [d for d in devices if d.get("state") == "device" and "emulator" not in d.get("serial", "")]
    emulators_up = [d for d in devices if "emulator" in d.get("serial", "")]

    apk_ok = False
    apk_meta: dict[str, Any] = {}
    if apk_path is not None:
        if not apk_path.is_file() or apk_path.is_symlink():
            findings.append(f"apk missing: {apk_path}")
        else:
            digest = hashlib.sha256(apk_path.read_bytes()).hexdigest()
            apk_meta = {
                "path": str(apk_path),
                "bytes": apk_path.stat().st_size,
                "sha256": digest,
                "bound_claim": "operator-supplied; still requires P-007 matrix for PASS",
            }
            # Presence alone is not PASS — still need install/run matrix evidence.
            apk_ok = True
            findings.append(
                "APK present but matrix run not executed by this probe "
                "(use lab receipt after install/upgrade/acquisition checks)"
            )
    else:
        findings.append("no --apk supplied for TARGET_SHA-bound build")

    inventory: list[dict[str, Any]] = []
    if apk_inventory_roots:
        inventory = inventory_apks(apk_inventory_roots)
        if inventory:
            findings.append(
                f"apk_inventory_count={len(inventory)} (all unbound; do not treat as candidate)"
            )
        else:
            findings.append("apk_inventory empty under supplied roots")

    if not avds:
        findings.append("no AVDs discovered")
    if not physical:
        findings.append("no physical adb devices attached (device matrix lab-only)")

    payload = {
        "schema_version": 1,
        "binder": "emulator_device_probe",
        "target_commit": target_commit,
        "result": "UNKNOWN",
        "completed_at": utc_now_iso(),
        "sdk": str(sdk) if sdk else None,
        "avds": avds,
        "adb_devices": devices,
        "physical_device_count": len(physical),
        "emulator_runtime_count": len(emulators_up),
        "apk": apk_meta or None,
        "apk_bytes_present": apk_ok,
        "apk_inventory": inventory,
        "findings": findings,
        "gates": {
            "candidate_emulator_matrix": {
                "result": "UNKNOWN",
                "reason": (
                    "AVDs inventory only; need TARGET_SHA APK lab run (P-007) "
                    "with devices[] PASS receipt"
                    if avds
                    else "no AVDs; external lab required"
                ),
            },
            "candidate_device_matrix": {
                "result": "UNKNOWN",
                "reason": "no physical devices attached; external lab required",
            },
        },
        "forbidden": [
            "fabricating PASS",
            "inferring device PASS from emulator",
            "treating AVD inventory alone as matrix PASS",
            "binding inventory APKs as TARGET_SHA candidate",
        ],
    }
    if replace_output and output.exists() and not output.is_symlink():
        output.unlink()
    digest = write_json_atomic(output, payload)
    return {
        "path": str(output),
        "sha256": digest,
        "result": "UNKNOWN",
        "avds": avds,
        "apk_inventory_count": len(inventory),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target-commit", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apk", type=Path, default=None, help="Optional APK path (still UNKNOWN without lab matrix)")
    p.add_argument(
        "--apk-inventory-root",
        action="append",
        default=[],
        type=Path,
        help="Shallow scan root for unbound APK inventory (repeatable; never implies PASS)",
    )
    p.add_argument(
        "--replace-output",
        action="store_true",
        help="Delete existing output path before write (refresh probe; never upgrades to PASS)",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    info = probe(
        target_commit=args.target_commit,
        output=args.output,
        apk_path=args.apk,
        apk_inventory_roots=args.apk_inventory_root or None,
        replace_output=bool(args.replace_output),
    )
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeError as exc:
        print(f"pi_canary_emulator_device_probe: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
