"""Attest the exact finalized prior database before deriving recovery work."""
import json
from datetime import date
from pathlib import Path
import time

from cdr_export_contract import hash_file
from cdr_observation_selection import load_pointer_observation, safe_child
from cdr_population_sanity import population_report


def finalized_population_report(current_db, state_dir, *, run_date):
    """An unfinalized/path-only database is diagnostic evidence, not authority."""
    unresolved = []
    try:
        # Selection can name a repaired revision, not the primary date export.
        path = Path(state_dir) / 'observation-pointers-v2/latest-observation.json'
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('invalid baseline pointer')
        pointer = json.loads(path.read_bytes())
        day = pointer['observation_date']
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('invalid baseline date')
        marker_path = safe_child(Path(state_dir), pointer['marker_path'])
        if marker_path.stat().st_size > 65536:
            raise ValueError('baseline marker exceeds metadata budget')
        marker = json.loads(marker_path.read_bytes())
        contract_path = safe_child(Path(state_dir), marker['export_contract_path'])
        if contract_path.stat().st_size > 16*1024*1024:
            raise ValueError('baseline contract exceeds metadata budget')
        observation = load_pointer_observation(Path(state_dir), pointer)
        contract = observation['contract']
        unresolved = contract['coverage'].get('provider_population_unverified', [])
        if not isinstance(unresolved, list) or any(not isinstance(row, dict)
                or not isinstance(row.get('provider'), str) for row in unresolved):
            raise ValueError('invalid prior population disposition')
        if date.fromisoformat(run_date).isoformat() != run_date or day >= run_date:
            raise ValueError('selected observation is not a prior day')
        prior_db = observation['export_root'] / 'local-cdr.sqlite'
        if prior_db.is_symlink() or safe_child(observation['export_root'], prior_db.name) != prior_db.resolve():
            raise ValueError('baseline database escaped its finalized root')
        records = [row for row in contract['artifacts'] if row['path'] == prior_db.name]
        if len(records) != 1 or records[0]['bytes'] != prior_db.stat().st_size:
            raise ValueError('baseline database not uniquely bound')
        deadline = time.monotonic()+8
        def budget(**unused):
            if time.monotonic() > deadline:
                raise ValueError('baseline verification budget exhausted')
        if hash_file(prior_db, budget=budget) != records[0]['sha256']:
            raise ValueError('baseline database changed after finalization')
        result = population_report(current_db, prior_db, unresolved_prior=unresolved,
                                   current_date=run_date,prior_date=day)
        if result['status'] == 'UNKNOWN' and unresolved:
            result['unresolved_prior'] = unresolved
        if result['status'] in {'PASS','WARN'}:
            result['baseline'] = {'observation_date':day,'generation_id':contract['generation_id'],
                'contract_digest':contract['contract_digest'],'database_sha256':records[0]['sha256'],
                'ledger_event_digest':marker['ledger_event_digest'],
                'unresolved_provider_populations':unresolved}
            for finding in result['findings']:
                from cdr_population_identity import prior_provider_identity
                if not finding.get('provider_identity'):
                    finding['provider_identity'] = prior_provider_identity(observation,
                        finding['provider'],result['baseline'])
                if not finding.get('carried_unresolved'):
                    finding['last_nonempty'] = {'observation_date':day,
                        'products':finding['products_prev'],'rates':finding.get('rates_prev',0)}
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return {'status':'UNKNOWN','reason':'baseline_not_finalized_or_verified','findings':[],
            **({'unresolved_prior':unresolved} if isinstance(unresolved,list) and unresolved else {})}
