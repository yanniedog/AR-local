"""Validate pending source identities without settling or reordering any upload."""
from datetime import date
from pathlib import PurePosixPath
import re


def only_historical(pending, run_date):
    queued = pending.get('queued_pointers', [])
    if 'selection_retry' in pending or not isinstance(queued, list):
        return False
    for pointer in [pending.get('pointer'), *queued]:
        if not isinstance(pointer, dict) or pointer.get('schema_version') != 2:
            return False
        day = pointer.get('observation_date')
        try:
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or day >= run_date:
                return False
        except ValueError:
            return False
        generation, digest = pointer.get('generation_id'), pointer.get('ledger_event_digest')
        if (not isinstance(generation, str) or not re.fullmatch(rf'obs-{day}-[0-9a-f]{{16}}', generation)
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or not isinstance(pointer.get('observation_state'), str)
                or pointer['observation_state'] not in {'complete', 'partial', 'failed'}):
            return False
        for name in ('marker_path', 'export_path'):
            value = pointer.get(name)
            if (not isinstance(value, str) or not value or '\\' in value or ':' in value
                    or PurePosixPath(value).is_absolute() or '..' in PurePosixPath(value).parts):
                return False
        parts = PurePosixPath(pointer['export_path']).parts
        if parts == ('runs', day, '_exports'):
            marker = f'{day}.done.json'
        elif len(parts) == 5 and parts[:3] == ('runs', day, '_revisions') and parts[4] == '_exports':
            marker = f'{day}.revision.{parts[3]}.json'
        else:
            return False
        if pointer['marker_path'] != marker:
            return False
    return pending.get('run_date', pending['pointer']['observation_date']) == pending['pointer']['observation_date']


def population_queue(pending, day, *, successor=None):
    """Return one current source and ordered entries; reject ambiguous metadata.

    The caller must bind the current source to a verified observation. An exact
    successor already queued by an interrupted publisher may be removed only
    after the caller proves its same-day lineage. Historical entries are retained.
    """
    try:
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            return None
    except ValueError:
        return None
    if not isinstance(pending, dict) or 'selection_retry' in pending:
        return None
    head, queued = pending.get('pointer'), pending.get('queued_pointers', [])
    if (not isinstance(head, dict) or not isinstance(queued, list)
            or pending.get('run_date') != head.get('observation_date')):
        return None
    entries = [head, *queued]
    generations, digests = set(), set()
    for row in entries:
        if not isinstance(row, dict) or not row.get('generation_id'):
            return None
        generation, digest = row['generation_id'], row.get('ledger_event_digest')
        if not isinstance(generation, str) or generation in generations:
            return None
        generations.add(generation)
        if digest is not None:
            if not isinstance(digest, str) or digest in digests:
                return None
            digests.add(digest)
    entries = [row for row in entries if row != successor]
    current = [row for row in entries if row.get('observation_date') == day]
    if len(current) != 1:
        return None
    historical = [row for row in entries if row != current[0]]
    if historical and not only_historical({'pointer': historical[0], 'queued_pointers': historical[1:]}, day):
        return None
    return current[0], entries
