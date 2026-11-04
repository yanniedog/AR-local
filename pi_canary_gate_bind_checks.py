#!/usr/bin/env python3
"""Shared fail-closed checks for canary gate binders (receipt + v1 public bytes)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping

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
    manifest: Mapping[str, Any], domain_by_name: Mapping[str, bytes]
) -> list[str]:
    """Run ``validate_manifest(..., root=)`` so historical envelopes bind to core.

    Digest checks alone cannot catch a catalogue envelope whose ``core_sha256``
    disagrees with ``files.core``; publication rejects those via local-asset
    validation. Stage already-verified domain bytes for every descriptor from
    ``iter_payload_assets`` (legacy files, history namespaces, executables) —
    never re-read release wire/ciphertext from disk.
    """

    from app_payload_optional_assets import iter_payload_assets
    from app_payload_revisions_state import validate_manifest

    findings: list[str] = []
    try:
        inventory = list(iter_payload_assets(dict(manifest)))
    except Exception as exc:  # noqa: BLE001
        findings.append(f"v1 asset inventory: {type(exc).__name__}: {exc}")
        return findings
    required_names: list[str] = []
    for _key, entry in inventory:
        if not isinstance(entry, Mapping):
            findings.append("v1 asset descriptor not object")
            return findings
        name = Path(str(entry.get("name") or "")).name
        if not name:
            findings.append("v1 asset missing name")
            return findings
        required_names.append(name)
    try:
        with tempfile.TemporaryDirectory(prefix="canary-v1-payload-") as tmp:
            root = Path(tmp)
            for name in required_names:
                body = domain_by_name.get(name)
                if body is None:
                    findings.append(f"v1 payload missing staged domain bytes {name!r}")
                    return findings
                (root / name).write_bytes(body)
            validate_manifest(dict(manifest), root)
    except Exception as exc:  # noqa: BLE001 — surface publication rejection
        findings.append(f"v1 local/historical validation: {type(exc).__name__}: {exc}")
    return findings
