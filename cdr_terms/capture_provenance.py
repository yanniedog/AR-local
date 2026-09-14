"""Source calendar/instant evidence, separate from derived archive write time."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from cdr_export_contract import load_contract

from .identity import byte_digest, canonical_json, timestamp
from .store import EvidenceStore


def source_time(finalized: Mapping[str, Any], *, state_dir: Path | None,
                observed_at: str | None) -> tuple[str, dict[str, Any], bytes | None]:
    """A generation timestamp describes its snapshot, never legal effective time.

    Contract construction during a later historical backfill is not evidence of
    that older day's observation. Refuse it; neither midnight nor import time is
    an acceptable substitute. A Hobart day can start on the preceding UTC date.
    """
    contract_bytes = None
    if observed_at is not None:
        provenance = {"basis": "explicit_source_observation", "timezone": "Australia/Hobart"}
    else:
        relative = Path(str(finalized.get("export_contract_path") or ""))
        if state_dir is None or relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("source_observation_requires_bound_export_contract")
        base = state_dir.resolve()
        path = (base / relative).resolve()
        if base not in path.parents or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("source_observation_contract_unavailable_or_unsafe")
        contract = load_contract(path)
        for key, expected in (("generation_id", finalized["generation_id"]),
                              ("contract_digest", finalized["export_contract_digest"]),
                              ("observation_date", finalized.get("run_date"))):
            if contract[key] != expected:
                raise ValueError("source_observation_contract_identity_mismatch")
        # Retain the exact verified contract representation, avoiding a second
        # filesystem read that could race replacement after validation.
        contract_bytes = (canonical_json(contract) + "\n").encode("utf-8")
        observed_at = contract["observed_at"]
        provenance = {"basis": "finalized_source_generation", "timezone": contract["timezone"],
                      "contract_sha256": byte_digest(contract_bytes), "contract_digest": contract["contract_digest"]}
    instant = timestamp(observed_at)
    local_day = datetime.fromisoformat(instant.replace("Z", "+00:00")).astimezone(ZoneInfo(provenance["timezone"])).date().isoformat()
    if local_day != finalized.get("run_date"):
        raise ValueError("source_observation_calendar_mismatch_requires_retained_time_evidence")
    return instant, provenance, contract_bytes


def begin_capture(store: EvidenceStore, generation: str, observed_at: str,
                  captured_at: str, provenance: Mapping[str, Any]) -> str:
    """Record intent before any observations; an unfinished capture has no authority."""
    context = canonical_json(provenance)
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO ingest_capture_attempts VALUES (?,?,?,?)",
                         (generation, observed_at, timestamp(captured_at), context))
        row = store.db.execute("SELECT * FROM ingest_capture_attempts WHERE ingest_id=?", (generation,)).fetchone()
        if row["source_observed_at"] != observed_at or row["provenance_json"] != context:
            raise ValueError("source_observation_capture_identity_changed")
    return row["captured_at"]
