"""Bind reconciled partial admission to the exact finalized source bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app_payload_partial_accounting import CLASSIFIED_FAILURES
from cdr_compatibility import classify_fetch_failure
from cdr_export_contract import load_contract
from cdr_finalization import verify_completion_marker


def _within(root: Path, relative: str) -> Path:
    part = Path(relative)
    if not relative or part.is_absolute() or '..' in part.parts:
        raise ValueError('Invalid finalized source path')
    path = root / part
    if path.resolve() != path.absolute():
        raise ValueError('Finalized paths must not contain symlinks')
    path.relative_to(root)
    return path


def reconciled_failure_statuses(exports: Path, contract: dict) -> bool:
    """Older contracts can hide internal errors under upstream_rejection.

    Check the original contract-bound raw status histogram as well as provider
    categories; unknown internal status labels never receive a quota waiver.
    """
    try:
        descriptors = [a for a in contract['artifacts'] if a['path'] == 'ingest-status.json']
        if len(descriptors) != 1:
            return False
        descriptor = descriptors[0]
        if not 0 < descriptor['bytes'] <= 8 * 1024 * 1024:
            return False
        with _within(exports, 'ingest-status.json').open('rb') as stream:
            raw = stream.read(descriptor['bytes'] + 1)
        if len(raw) != descriptor['bytes'] or hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
            return False
        status = json.loads(raw)
        counts = status['by_status']
        return (isinstance(counts, dict) and bool(counts)
            and status['total'] == contract['coverage']['failure_records']
            and all(type(n) is int and n > 0 and classify_fetch_failure(s).category in CLASSIFIED_FAILURES
                    for s, n in counts.items())
            and sum(counts.values()) == status['total'])
    except (KeyError, OSError, ValueError, TypeError):
        return False


def verify_reconciled_source(state: Path, exports: Path, run_date: str, contract: dict) -> bool:
    """Caller retains the ingest lock through verification, build and upload."""
    try:
        state, exports = state.absolute(), exports.absolute()
        if (contract['observation_date'] != run_date
                or _within(state.parent, contract['source_path']) != exports):
            return False
        marker = json.loads(_within(state, contract['completion_marker_path']).read_bytes())
        stored = load_contract(_within(state, marker['export_contract_path']))
        if stored != contract or not verify_completion_marker(marker, state, run_date):
            return False
        return reconciled_failure_statuses(exports, contract)
    except (KeyError, OSError, ValueError, TypeError):
        return False
