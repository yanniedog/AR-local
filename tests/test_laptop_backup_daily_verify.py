"""Evidence-specific tests for canonical daily backup verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import laptop_backup_daily_verify as daily_verify
from tests.support_observation import write_verified_observation


def _accounting(exports: Path) -> dict:
    return json.loads(
        (exports / "product-accounting-v1.json").read_text(encoding="utf-8")
    )


def test_rejects_unresolved_product_evidence(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    write_verified_observation(exports, observation_date="2026-09-03")
    accounting = _accounting(exports)
    accounting["products"][0]["evidence_ids"] = ["f" * 64]

    with pytest.raises(ValueError, match="does not resolve"):
        daily_verify._validate_promoted_product_evidence(exports, accounting)


def test_rejects_evidence_from_another_product(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    write_verified_observation(exports, observation_date="2026-09-03")
    accounting = _accounting(exports)
    status = json.loads((exports / "ingest-status.json").read_text(encoding="utf-8"))
    journal_root = exports / status["raw_attempt_journal"]["path"]
    events = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((journal_root / "events").glob("*.json"))
    ]
    unrelated = next(
        event for event in events if event["context"].get("product_id") == "unrelated"
    )
    accounting["products"][0]["evidence_ids"] = [
        unrelated["response"]["body_sha256"]
    ]

    with pytest.raises(ValueError, match="verified journal attempts"):
        daily_verify._validate_promoted_product_evidence(exports, accounting)


def test_rebuilds_promoted_manifest(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    write_verified_observation(exports, observation_date="2026-09-03")
    accounting = _accounting(exports)
    status_path = exports / "ingest-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    pointer = status["raw_attempt_journal"]
    manifest_path = exports / pointer["promotion_manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_file_count"] += 1
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    pointer["promotion_manifest_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest conflicts"):
        daily_verify._validate_promoted_product_evidence(exports, accounting)


def test_binds_provider_state_to_journal_context(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    write_verified_observation(exports, observation_date="2026-09-03")
    accounting = _accounting(exports)
    status_path = exports / "ingest-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["provider_states"][0].update(
        provider_dir="Invented Bank", brand_name="Invented Bank"
    )
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown provider|lacks journal-bound evidence"):
        daily_verify._validate_promoted_product_evidence(exports, accounting)
