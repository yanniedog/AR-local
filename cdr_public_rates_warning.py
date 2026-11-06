"""Publish committed source-status warnings without collecting or pricing.

A warning snapshot copies the immutable candidate header, retains every price
and chunk descriptor, and marks discovery/reference freshness pending. It never
acknowledges source work. The original approval still owns programme scope;
all approved programmes are suspended until deterministic processing completes.
"""
from __future__ import annotations

import copy
import hashlib
import sqlite3
import time
from pathlib import Path

from cdr_atomic import atomic_write_json, canonical_json_bytes
from cdr_public_rates_candidate import Candidate, MAX_ROOT_BYTES, candidate_digest, read_candidate, selected_evidence
from cdr_terms.identity import digest

MAX_SOURCE_REGISTERS = 128
PENDING_REASON = 'public_pricing_source_update_pending'


class SupersededCandidate(ValueError):
    """Accepted source state or a newer complete snapshot supersedes a retry."""


class PublicPricingSourcePending(ValueError):
    """Committed source status cannot be safely inspected for publication."""


def read_source_state(root: Path, generation: str, *, include_clean: bool = False) -> dict | None:
    """Bounded read-only status query, independent of collector admission."""
    path = Path(root).resolve() / 'evidence.sqlite3'
    if not path.is_file() or path.is_symlink():
        raise PublicPricingSourcePending('public_pricing_source_state_unavailable')
    started, connection = time.monotonic(), None
    try:
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.set_progress_handler(lambda: int(time.monotonic() - started > 1), 1000)
        if connection.execute('PRAGMA application_id').fetchone()[0] != 0x4152544D:
            raise PublicPricingSourcePending('public_pricing_source_state_unavailable')
        rows = connection.execute('SELECT register_id,sequence,event_id,status,observed_at '
            'FROM public_rate_candidate_events e WHERE e.ingest_id=? AND e.sequence='
            '(SELECT MAX(sequence) FROM public_rate_candidate_events newest '
            'WHERE newest.ingest_id=e.ingest_id AND newest.register_id=e.register_id) '
            'ORDER BY register_id LIMIT ?', (generation, MAX_SOURCE_REGISTERS + 1)).fetchall()
        if len(rows) > MAX_SOURCE_REGISTERS:
            raise PublicPricingSourcePending('public_pricing_source_state_budget_exceeded')
        if not include_clean and not any(row['status'] == 'dirty' for row in rows):
            return None
        events = [{'registerId': row['register_id'], 'sequence': row['sequence'], 'eventId': row['event_id'],
                   'status': row['status'], 'observedAt': row['observed_at']} for row in rows]
        return {'schemaVersion': 1, 'generationId': generation, 'events': events}
    except sqlite3.Error as error:
        raise PublicPricingSourcePending('public_pricing_source_state_unavailable') from error
    finally:
        if connection is not None:
            connection.close()


def _root(candidate: Candidate) -> Path:
    if not isinstance(candidate, Candidate):
        raise ValueError('public_warning_requires_verified_immutable_candidate')
    path = candidate.path.resolve()
    root = path.parents[2]
    expected = root / 'public-rate-candidates' / digest(candidate['generationId']) / (candidate_digest(candidate) + '.json')
    if path != expected or candidate.get('enabledProgrammeIds') != []:
        raise ValueError('public_warning_requires_verified_immutable_candidate')
    return root


def _source(root: Path, snapshot: dict, candidate: Candidate) -> Candidate:
    name, identity = snapshot.get('sourceCandidateFile'), snapshot.get('sourceCandidateSha256')
    if not isinstance(name, str) or not isinstance(identity, str):
        raise ValueError('invalid_public_warning_source_binding')
    relative = Path(name)
    path = root / relative
    if relative.is_absolute() or '..' in relative.parts or path.is_symlink() or root not in path.resolve().parents:
        raise ValueError('invalid_public_warning_source_binding')
    source = read_candidate(path)
    if (candidate_digest(source) != identity or _root(source) != root
            or source['generationId'] != snapshot.get('sourceGenerationId') or source['runDate'] != snapshot.get('sourceRunDate')
            or candidate['generationId'] != snapshot.get('targetGenerationId') or candidate['runDate'] != snapshot.get('targetRunDate')
            or 'warningSnapshot' in source):
        raise ValueError('invalid_public_warning_source_binding')
    return source


def project_warning(source: Candidate, state: dict, *, generation: str | None = None, run_date: str | None = None) -> dict:
    """Metadata projection: original monetary values and evidence stay exact."""
    root = _root(source)
    generation, run_date = generation or source['generationId'], run_date or source['runDate']
    if ('warningSnapshot' in source or state.get('generationId') != generation or source['runDate'] > run_date
            or source['generationId'] == generation and source['runDate'] != run_date):
        raise ValueError('invalid_public_warning_source_state')
    value = copy.deepcopy(dict(source))
    historical = source['generationId'] != generation
    reasons = {PENDING_REASON} | ({'public_pricing_previous_generation_history'} if historical else set())
    value.update(generationId=generation, runDate=run_date)
    if historical:
        # Old offer/evidence chunks remain available only through their original
        # edition. No executable programme can acquire a new generation here.
        value.update(programmes=[], programmeChunks=[], evidenceChunks=[])
        needed = {identity for item in source.get('referenceRates', []) for identity in item['evidenceIds']}
        value['evidence'] = selected_evidence(source, needed) if needed else []
    for item in value.get('products', []) + value.get('referenceRates', []):
        freshness = item.setdefault('freshness', {})
        freshness['state'] = 'deferred'
        freshness['reasonCodes'] = sorted(set(freshness.get('reasonCodes', [])) | reasons)
        if 'productId' in item:
            item['reasonCodes'] = sorted(set(item.get('reasonCodes', [])) | reasons)
            if historical:
                item['suppressedProgrammeCount'] = item.get('suppressedProgrammeCount', 0) + len(item['programmeIds'])
                item['programmeIds'] = []
                if item['status'] == 'current':
                    item['status'] = 'unknown'
    for entry in value.get('coverage', []):
        entry.update(sourceStatus='refresh_pending', referenceSourceStatus='deferred', sourceAcquisition='deferred',
                     extraction='pending', pricingInterpretation='pending', costCompleteness='unknown',
                     resolutionStatus='unresolved', publicationStatus='warning_candidate')
        if 'programmesWithFormula' in entry:
            entry['programmesWithFormula'] = 0
        entry['reasonCodes'] = sorted(set(entry.get('reasonCodes', [])) | reasons)
    value['warningSnapshot'] = {'schemaVersion': 1,
        'sourceCandidateFile': source.path.resolve().relative_to(root).as_posix(),
        'sourceCandidateSha256': candidate_digest(source), 'sourceGenerationId': source['generationId'],
        'sourceRunDate': source['runDate'], 'targetGenerationId': generation, 'targetRunDate': run_date,
        'sourceState': copy.deepcopy(state),
        'sourceStateSha256': hashlib.sha256(canonical_json_bytes(state)).hexdigest()}
    return value


def write_warning(root: Path, source: Candidate, state: dict, *, generation: str | None = None, run_date: str | None = None) -> Candidate:
    if Path(root).resolve() != _root(source):
        raise ValueError('invalid_public_warning_evidence_root')
    value = project_warning(source, state, generation=generation, run_date=run_date)
    body = canonical_json_bytes(value)
    if len(body) > MAX_ROOT_BYTES:
        raise PublicPricingSourcePending('public_warning_candidate_budget_exceeded')
    identity = hashlib.sha256(body).hexdigest()
    path = Path(root) / 'public-rate-candidates' / digest(value['generationId']) / (identity + '.json')
    atomic_write_json(path, value, create_once=True)
    return read_candidate(path)


def validate_warning_candidate(candidate: dict, *, check_current: bool = True) -> None:
    """Reproduce status-only bytes and bind them to committed source events."""
    if 'warningSnapshot' not in candidate:
        return
    root = _root(candidate)
    snapshot = candidate['warningSnapshot']
    if (not isinstance(snapshot, dict) or set(snapshot) != {'schemaVersion', 'sourceCandidateFile',
            'sourceCandidateSha256', 'sourceGenerationId', 'sourceRunDate', 'targetGenerationId', 'targetRunDate',
            'sourceState', 'sourceStateSha256'} or snapshot.get('schemaVersion') != 1):
        raise ValueError('invalid_public_warning_snapshot')
    state = snapshot['sourceState']
    if not isinstance(state, dict) or snapshot['sourceStateSha256'] != hashlib.sha256(canonical_json_bytes(state)).hexdigest():
        raise ValueError('invalid_public_warning_source_state')
    source = _source(root, snapshot, candidate)
    if dict(candidate) != project_warning(source, state, generation=candidate['generationId'], run_date=candidate['runDate']):
        raise ValueError('public_warning_cannot_override_observed_pricing')
    if not check_current:
        return
    latest = read_candidate(root / 'public-rate-catalogue-candidate.json')
    if (latest['generationId'] != source['generationId'] or candidate_digest(latest) != candidate_digest(source)
            or read_source_state(root, candidate['generationId'], include_clean=source['generationId'] != candidate['generationId']) != state):
        raise SupersededCandidate('public_pricing_warning_source_state_superseded')
