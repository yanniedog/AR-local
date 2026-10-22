"""Recover a date's selection from immutable decisions, never filename order."""
import hashlib
from datetime import date
from pathlib import Path

from cdr_atomic import canonical_json_bytes
from cdr_export_contract import load_contract, read_json
from cdr_ledger_v2 import verify_event
from cdr_observation_selection import safe_child


def _snapshot_paths(state, run_date, kind, paths, maximum):
    values = [Path(path) for path in paths]
    root = (state/kind/run_date).resolve()
    if len(values) > maximum or len({path.resolve() for path in values}) != len(values) or any(path.suffix != '.json'
            or path.resolve().parent != root for path in values):
        raise ValueError('Historical snapshot paths escape their canonical date or budget')
    return values


def historical_contract(state: Path, run_date: str, *, paths=None, decision_paths=None,
                        budget=None) -> dict | None:
    from app_payload_observation_gate import contract_for_run_date

    if budget is not None:
        budget()
    if date.fromisoformat(run_date).isoformat() != run_date:
        raise ValueError('Invalid observation date')
    snapshot = paths is not None
    paths = (list((state / 'export-contracts-v2' / run_date).glob('*.json')) if paths is None
             else _snapshot_paths(state,run_date,'export-contracts-v2',paths,8))
    if decision_paths is not None:
        decision_paths = _snapshot_paths(state,run_date,'observation-selections-v1',decision_paths,16)
    if len(paths) <= 1:
        if snapshot:
            contract = (load_contract(safe_child(state, paths[0].relative_to(state).as_posix()),
                                     budget=budget) if paths else None)
            if contract and contract['observation_date'] != run_date:
                raise ValueError('Historical snapshot contract belongs to another date')
            return contract
        return contract_for_run_date(state, run_date)
    contracts, events = {}, {}
    for path in paths:
        if budget is not None:
            budget()
        contract = load_contract(safe_child(state, path.relative_to(state).as_posix()),budget=budget)
        generation = contract['generation_id']
        if contract['observation_date'] != run_date or generation in contracts:
            raise ValueError('Ambiguous historical contracts')
        event_path = safe_child(state, f'ledger-v2/events/{run_date}/{generation}.json')
        event = read_json(event_path,budget=budget)
        if not isinstance(event, dict):
            raise ValueError('Invalid historical event')
        verify_event(state, event,budget=budget)
        if event['contract_digest'] != contract['contract_digest']:
            raise ValueError('Historical event/contract mismatch')
        contracts[generation], events[generation] = contract, event['event_digest']
    decisions, decision_states = {}, {}
    decision_paths = ((state / 'observation-selections-v1' / run_date).glob('*.json')
                      if decision_paths is None else decision_paths)
    for path in decision_paths:
        if budget is not None:
            budget()
        decision = read_json(safe_child(state, path.relative_to(state).as_posix()),budget=budget)
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
