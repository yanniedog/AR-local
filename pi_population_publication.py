"""Archive superseded population holds without claiming publication or resetting budgets."""
import hashlib

from app_payload_observation_gate import publication_allowed
from cdr_atomic import atomic_write_json,canonical_json_bytes
from cdr_observation_selection import load_pointer_observation,selected_observation


def _verified_replacement(state,previous,pointer):
    if (not isinstance(pointer,dict) or not pointer or previous.get('pointer')==pointer
            or 'selection_retry' in previous):
        return None
    queued=previous.get('queued_pointers',[])
    if not isinstance(queued,list) or any(row!=pointer for row in queued):
        return None
    old_pointer=previous.get('pointer')
    if (not isinstance(old_pointer,dict) or old_pointer.get('observation_date')!=pointer.get('observation_date')
            or previous.get('run_date')!=pointer.get('observation_date')):
        return None
    try:
        old=load_pointer_observation(state,previous['pointer'])
        new=load_pointer_observation(state,pointer)
        day=old['contract']['observation_date']
        selected=selected_observation(state,day)
        reuse=(new['status'].get('same_day_reuse') or {})
        source=reuse.get('baseline') or {}
        if (previous.get('run_date')!=day or new['contract']['observation_date']!=day
                or not selected or selected['pointer']!=pointer
                or publication_allowed(old['contract'])!=(False,'unverified_provider_population')
                or new['contract']['observation_state'] not in {'complete','partial'}
                or new['event'].get('parent_generation_id')!=old['contract']['generation_id']
                or new['event'].get('parent_event_digest')!=old['event']['event_digest']
                or reuse.get('reconciled') is not True
                or source.get('generation_id')!=old['contract']['generation_id']
                or source.get('ledger_event_digest')!=old['event']['event_digest']
                or source.get('export_contract_digest')!=old['contract']['contract_digest']):
            return None
        admission=publication_allowed(new['contract'])
        if not admission[0] and admission[1]!='unverified_provider_population':
            return None
        return old,new
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return None  # Unproven sources retain the ordinary pending queue.


def supersede_population_pending(state,previous,pointer,replacement):
    """Caller holds the production lock; archive before its atomic marker write.

    A crash before replacement leaves the old marker and an idempotent receipt.
    A crash afterward leaves the selected replacement reserved for retry.
    """
    sources=_verified_replacement(state,previous,pointer)
    if sources is None:
        return None
    old,new=sources
    receipt={'schema_version':1,'reason':'selected_same_day_population_recovery',
        'previous_pending':previous,'replacement_pointer':pointer,'publication_confirmed':False,
        'previous_contract_digest':old['contract']['contract_digest'],
        'replacement_contract_digest':new['contract']['contract_digest']}
    raw=canonical_json_bytes(receipt)
    if len(raw)>65536:
        raise ValueError('population supersession receipt exceeds metadata budget')
    name=hashlib.sha256(raw).hexdigest()+'.json'
    relative='population-publication-supersessions-v1/'+name
    atomic_write_json(state/relative,receipt,create_once=True)
    return {**replacement,'policy_supersession_receipt':relative}


def reconcile_selected_population_pending(repo_root,run_date):
    """Repair a pre-publication interruption under the existing production lease."""
    from ar_local_pi_runtime import data_state_root
    from pi_daily_sync import DailyIngestLock,read_payload_publication_pending,mark_payload_publication_pending
    from pi_cdr_recovery import recovery_block_reason
    state=data_state_root(repo_root)
    selected=selected_observation(state,run_date)
    pending=read_payload_publication_pending(repo_root)
    if not selected or _verified_replacement(state,pending,selected['pointer']) is None:
        return False
    with DailyIngestLock(state/'daily-ingest.lock'):
        if recovery_block_reason(repo_root,include_ingest_lock=False):
            return False
        selected=selected_observation(state,run_date)
        pending=read_payload_publication_pending(repo_root)
        if not selected or _verified_replacement(state,pending,selected['pointer']) is None:
            return False
        mark_payload_publication_pending(repo_root,'selected_population_recovery',selected['pointer'],
                                         allow_policy_supersession=True)
        return True
