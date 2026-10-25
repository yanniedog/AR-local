#!/usr/bin/env python3
"""Shared fail-closed checks for canary gate binders (receipt + v1 public bytes)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import pi_canary_acceptance as canary


def append_gate_specific_receipt_findings(
    gate: str, raw: Mapping[str, Any], findings: list[str]
) -> None:
    """Mirror canonicalize evidence checks so raw bind cannot authorize incomplete PASS."""

    if gate == "shadow_ingest":
        if type(raw.get("exit_code")) is not int or raw.get("exit_code") != 0:
            findings.append(
                f"shadow_ingest PASS requires exit_code=0, got {raw.get('exit_code')!r}"
            )
        exports_raw = raw.get("exports_dirs", raw.get("exports", []))
        if exports_raw is None:
            exports: list[object] = []
        elif isinstance(exports_raw, list):
            exports = exports_raw
        else:
            findings.append(
                f"exports_dirs/exports must be a list, got {type(exports_raw).__name__}"
            )
            exports = []
        if not exports or any(
            not isinstance(path, str) or not path.strip() for path in exports
        ):
            findings.append(
                "shadow_ingest PASS requires non-empty exports_dirs/exports path evidence"
            )
        return

    if gate == "stable_app_compatibility":
        ci = raw.get("ci")
        if not isinstance(ci, dict) or ci.get("command") != "npm run ci":
            findings.append("stable-app PASS requires ci.command='npm run ci'")
        elif type(ci.get("exit_code")) is not int or ci.get("exit_code") != 0:
            findings.append("stable-app PASS requires ci.exit_code=0")
        elif not (
            isinstance(ci.get("log_sha256"), str)
            and canary.SHA256_RE.fullmatch(ci["log_sha256"]) is not None
        ):
            findings.append("stable-app PASS requires ci.log_sha256 (64 hex)")
        elif any(
            type(ci.get(field)) is not int or ci[field] <= 0
            for field in ("suites", "tests")
        ):
            findings.append(
                "stable-app PASS requires positive integer ci.suites and ci.tests"
            )
        return

    if gate.endswith("_matrix"):
        from pi_canary_app_matrix_receipts import _validate_matrix_device

        devices = raw.get("devices")
        if not isinstance(devices, list) or not devices:
            findings.append("matrix PASS requires non-empty devices[]")
            return
        for index, device in enumerate(devices):
            if not isinstance(device, dict):
                findings.append(f"devices[{index}] must be an object")
                continue
            findings.extend(_validate_matrix_device(gate, index, device))


def validate_v1_payload_root(
    manifest: Mapping[str, Any], asset_paths: Sequence[Path]
) -> list[str]:
    """Run ``validate_manifest(..., root=)`` so historical envelopes bind to core.

    Digest checks alone cannot catch a catalogue envelope whose ``core_sha256``
    disagrees with ``files.core``; publication rejects those via local-asset
    validation. Stage declared file names (including history namespaces) into a
    temporary payload dir and apply the same root checks.
    """

    from app_payload_revisions_state import NAMESPACE, validate_manifest

    findings: list[str] = []
    by_name = {
        path.name: path
        for path in asset_paths
        if path.is_file() and not path.is_symlink()
    }
    required_names: set[str] = set()
    files = manifest.get("files")
    if isinstance(files, Mapping):
        for entry in files.values():
            if isinstance(entry, Mapping):
                name = Path(str(entry.get("name") or "")).name
                if name:
                    required_names.add(name)
    for ns_key in (
        NAMESPACE,
        "bank_rate_history_catalogue_packed",
        "bank_rate_history_ready",
    ):
        ns = manifest.get(ns_key)
        if not isinstance(ns, Mapping):
            continue
        file_entry = ns.get("file")
        if isinstance(file_entry, Mapping):
            name = Path(str(file_entry.get("name") or "")).name
            if name:
                required_names.add(name)
    try:
        with tempfile.TemporaryDirectory(prefix="canary-v1-payload-") as tmp:
            root = Path(tmp)
            for name in sorted(required_names):
                src = by_name.get(name)
                if src is None:
                    findings.append(f"v1 payload missing staged asset {name!r}")
                    return findings
                (root / name).write_bytes(src.read_bytes())
            validate_manifest(dict(manifest), root)
    except Exception as exc:  # noqa: BLE001 — surface publication rejection
        findings.append(f"v1 local/historical validation: {type(exc).__name__}: {exc}")
    return findings
