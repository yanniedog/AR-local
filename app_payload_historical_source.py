"""Recover a date's selection from immutable decisions, never filename order."""
import hashlib
import json
from datetime import date
from pathlib import Path

from cdr_atomic import canonical_json_bytes
from cdr_export_contract import load_contract
from cdr_ledger_v2 import verify_event
from cdr_observation_selection import safe_child


def historical_contract(state: Path, run_date: str) -> dict | None:
    from app_payload_observation_gate import contract_for_run_date

    if date.fromisoformat(run_date).isoformat() != run_date:
        raise ValueError('Invalid observation date')
    paths = list((state / 'export-contracts-v2' / run_date).glob('*.json'))
    if len(paths) <= 1:
        return contract_for_run_date(state, run_date)
    contracts, events = {}, {}
    for path in paths:
        contract = load_contract(safe_child(state, path.relative_to(state).as_posix()))
        generation = contract['generation_id']
        if contract['observation_date'] != run_date or generation in contracts:
            raise ValueError('Ambiguous historical contracts')
        event = json.loads(safe_child(state, f'ledger-v2/events/{run_date}/{generation}.json').read_bytes())
        if not isinstance(event, dict):
            raise ValueError('Invalid historical event')
        verify_event(state, event)
        if event['contract_digest'] != contract['contract_digest']:
            raise ValueError('Historical event/contract mismatch')
        contracts[generation], events[generation] = contract, event['event_digest']
    decisions, decision_states = {}, {}
    for path in (state / 'observation-selections-v1' / run_date).glob('*.json'):
        decision = json.loads(safe_child(state, path.relative_to(state).as_posix()).read_bytes())
        if (not isinstance(decision, dict)
                or hashlib.sha256(canonical_json_bytes(decision)).hexdigest() != path.stem
                or decision.get('schema_version') != 1 or decision.get('observation_date') != run_date
                or type(decision.get('selected')) is not bool):
            raise ValueError('Invalid historical selection receipt')
        candidate, previous = decision['candidate_generation_id'], decision['previous_generation_id']
        if (candidate == previous or candidate not in events
                or previous not in events or decision['candidate_event_digest'] != events[candidate]
                or decision['previous_event_digest'] != events[previous]):
            raise ValueError('Historical selection binding differs')
        prior = decisions.get(candidate)
        if prior is not None:
            # A refusal can be reconsidered after explicit scope evidence is
            # reconciled (the retained 13 Sep repair has both receipts). An
            # accepted immutable selection wins over its same-pair refusal;
            # duplicate decisions or a different predecessor stay ambiguous.
            if (prior['previous_generation_id'] != previous
                    or decision['selected'] in decision_states[candidate]):
                raise ValueError('Historical selection binding differs')
            decisions[candidate] = decision if decision['selected'] else prior
        else:
            decisions[candidate] = decision
        decision_states.setdefault(candidate, set()).add(decision['selected'])
    initial = set(contracts) - set(decisions)
    if len(initial) != 1 or len(decisions) != len(contracts) - 1:
        raise ValueError('Historical selection history incomplete')
    selected = initial.pop()
    while decisions:
        ready = [key for key, item in decisions.items() if item['previous_generation_id'] == selected]
        accepted = [key for key in ready if decisions[key]['selected']]
        if not ready or len(accepted) > 1:
            raise ValueError('Historical selection history ambiguous')
        for key in ready:
            del decisions[key]
        if accepted:
            selected = accepted[0]
    return contracts[selected]
