"""Attest the exact finalized prior database before deriving recovery work."""
import json
from pathlib import Path
import time

from cdr_export_contract import hash_file
from cdr_observation_selection import load_pointer_observation, safe_child
from cdr_population_sanity import population_report


def finalized_population_report(current_db, prior_db, state_dir):
    """An unfinalized/path-only database is diagnostic evidence, not authority."""
    unresolved = []
    try:
        day = prior_db.parent.parent.name
        marker_path = Path(state_dir) / f'{day}.done.json'
        if marker_path.is_symlink() or marker_path.stat().st_size > 65536:
            raise ValueError('invalid baseline marker')
        marker = json.loads(marker_path.read_bytes())
        contract_path = safe_child(Path(state_dir), marker['export_contract_path'])
        # load_pointer_observation validates containment, contract, event and status.
        if contract_path.stat().st_size > 16*1024*1024:
            raise ValueError('baseline contract exceeds metadata budget')
        contract = json.loads(contract_path.read_bytes())
        pointer = {key:contract[key] for key in ['generation_id','observation_state','observation_date']}
        pointer.update(marker_path=marker_path.name, ledger_event_digest=marker['ledger_event_digest'],
            export_path=contract['source_path'])
        observation = load_pointer_observation(Path(state_dir), pointer)
        contract = observation['contract']
        unresolved = contract['coverage'].get('provider_population_unverified', [])
        if not isinstance(unresolved, list) or any(not isinstance(row, dict)
                or not isinstance(row.get('provider'), str) for row in unresolved):
            raise ValueError('invalid prior population disposition')
        if observation['export_root'] != prior_db.parent.resolve() or contract['observation_date'] != day:
            raise ValueError('baseline does not bind this database')
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
        result = population_report(current_db, prior_db, unresolved_prior=unresolved)
        if result['status'] == 'UNKNOWN' and unresolved:
            result['unresolved_prior'] = unresolved
        if result['status'] in {'PASS','WARN'}:
            result['baseline'] = {'observation_date':day,'generation_id':contract['generation_id'],
                'contract_digest':contract['contract_digest'],'database_sha256':records[0]['sha256'],
                'ledger_event_digest':marker['ledger_event_digest'],
                'unresolved_provider_populations':unresolved}
            for finding in result['findings']:
                if not finding.get('carried_unresolved'):
                    finding['last_nonempty'] = {'observation_date':day,
                        'products':finding['products_prev'],'rates':finding.get('rates_prev',0)}
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return {'status':'UNKNOWN','reason':'baseline_not_finalized_or_verified','findings':[],
            **({'unresolved_prior':unresolved} if isinstance(unresolved,list) and unresolved else {})}
