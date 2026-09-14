"""Library-only May23 controller. No CLI, date overrides, retries or publication."""
from __future__ import annotations

import copy
import shutil
import time
from collections import Counter
from contextvars import ContextVar
from pathlib import Path

from cdr_historical_fee_archive import private_path, read_verified, safe_path, seal_exclusive, write_exclusive
from cdr_historical_fee_archive_admission import load, recheck_inputs
from cdr_historical_fee_archive_candidate import _payloads
from cdr_historical_fee_exact import encode, sha
from cdr_historical_fee_ledger import Ledger
from cdr_historical_fee_ledger_io import canonical, control_work, digest, parse
from cdr_historical_fee_plan import admit, registry, validate_plan, verify_code
from cdr_historical_fee_plan_budget import CONTROL, ControlBudget, PhaseBudget, exact_meter

_REGISTRY = ContextVar('historical_reviewed_registry', default=None)


def active_registry():
    value = _REGISTRY.get()
    if value is None:
        raise ValueError('reviewed_profile_requires_active_plan')
    return copy.deepcopy(value)


def validate_selected_members(files, chosen):
    value = active_registry()
    meta = value['source_metadata_pins']
    if len(files) != meta['inventory_files'] or sum(row['size'] for row in files) != meta['inventory_payload_bytes']:
        raise ValueError('reviewed_inventory_totals_mismatch')
    for role, identity in value['work_identity']['parent']['assets'].items():
        if chosen[role] != identity['archive_member']:
            raise ValueError('original_public_parent_exact_member_required')
    for index, identity in enumerate(meta['control_members']):
        selected = [row for row in files if row['path'] == chosen['control' + str(index)]]
        if len(selected) != 1 or any(selected[0][key] != identity[key] for key in ('path', 'size', 'sha256')):
            raise ValueError('reviewed_control_member_mismatch')


def _paths(plan):
    paths = {key: Path(value) for key, value in plan['paths'].items()}
    for key in ('archive', 'anchor', 'ledger'):
        if safe_path(paths[key], directory=True) != paths[key]:
            raise ValueError('canonical_execution_root_required')
    for key in ('cache', 'output'):
        if private_path(paths[key]) != paths[key] or paths[key].exists():
            raise ValueError('candidate_output_collision')
    for key, path in paths.items():
        for other, other_path in paths.items():
            if key != other and (path == other_path or path in other_path.parents or other_path in path.parents):
                raise ValueError('source_output_ledger_roots_must_be_separate')
    for key in ('cache', 'output', 'ledger'):
        volume_path = paths[key] if key == 'ledger' else paths[key].parent
        if shutil.disk_usage(volume_path).free < 3 * 1024**3:
            raise ValueError('candidate_requires_3gib_free_space')
    return paths


def _admission(loaded, audit, payloads, plan, approval):
    files = {name: {'bytes': len(body), 'sha256': sha(body)} for name, body in payloads.items()}
    return {'schema_version': 2, 'contract': 'reviewed_original_anchor_fee_admission_v2',
            'policy_version': 'may23-reviewed-original-anchor-fees-v2',
            'work_id': plan['work_id'], 'plan_sha256': approval['plan_sha256'],
            'observation_date': '2026-05-23', 'parent': active_registry()['work_identity']['parent'],
            'container': loaded['container'], 'generation': loaded['generation'], 'inputs': loaded['inputs'],
            'source_code': plan['code'], 'core_bytes_preserved': True,
            'untouched_optional_assets': {key: value for key, value in loaded['manifest']['files'].items()
                                          if key not in ('core', 'details')},
            'membership': {'products': len(audit['products']), 'rates': len(audit['rates']),
                           'fee_dispositions': dict(Counter(row['status'] for row in audit['fees'])),
                           'products_canonical_sha256': sha(encode(audit['products']))},
            'output_files': files, 'publication': 'NOT_ATTEMPTED', 'full_fee_applicability': 'UNKNOWN',
            'calculation_completeness': 'UNKNOWN', 'source_http_capture': 'NOT_SUPPLIED'}


def _candidate(paths, plan, approval, budget, schema_body):
    from cdr_historical_fee_embedded import VARIABLE_ZERO_RULE
    if VARIABLE_ZERO_RULE != 'variable_zero_placeholder_v3':
        raise ValueError('reviewed_fee_v3_dependency_required_before_source_io')
    budget.claim_directory(paths['output'])
    loaded = load(paths['archive'], paths['anchor'], paths['cache'], budget,
                  profile='may23-reviewed-original-anchor-fees-v2')
    # _payloads is the existing wrapper around the one reviewed fee transform,
    # including exact product/rate membership and restoration verification.
    payloads, audit = _payloads(loaded, budget)
    admission = _admission(loaded, audit, payloads, plan, approval)
    import json
    from jsonschema import Draft202012Validator, FormatChecker
    Draft202012Validator(json.loads(schema_body), format_checker=FormatChecker()).validate(admission)
    payloads['admission.json'] = encode(admission)
    identities = {}
    for name, body in payloads.items():
        budget.check()
        identity = {'bytes': len(body), 'sha256': sha(body)}
        write_exclusive(paths['output'] / name, body, budget)
        read_verified(paths['output'] / name, identity, budget, limit=512 * 1024**2, capture=False)
        identities[name] = identity
    recheck_inputs(loaded, budget)
    # A before-seal snapshot is explicitly named; never alias budget.counts.
    receipt = {'schema_version': 2, 'result': 'CANDIDATE_SEALED_UNREVIEWED',
               'work_id': plan['work_id'], 'plan_sha256': approval['plan_sha256'],
               'publication': 'NOT_ATTEMPTED', 'observation_date': '2026-05-23', 'files': identities,
               'resources': {'phase_counters_before_seal': budget.snapshot(),
                             'control_work_precharged': CONTROL, 'control_output_reserved': CONTROL},
               'required_next': ['Independent reconstruction', 'Separate immutable publication approval'],
               'limitations': ['Embedded export is not HTTP capture.', 'Legal effective dates remain unknown.']}
    body = encode(receipt)
    receipt_identity = {'bytes': len(body), 'sha256': sha(body)}
    seal_exclusive(paths['output'] / 'receipt.json', body, budget)
    return {'candidate_receipt': receipt_identity, 'candidate_receipt_value': receipt,
            'phase_counters_final': budget.snapshot()}


def execute(plan_body, approval_body, *, trusted_verifier=None, control_budget=None):
    """Only a separately root-reviewed exact launcher may supply the verifier.

    This API never launches a process. The attested 660s outer timeout must
    actually be installed by that launcher; library code cannot attest itself.
    """
    started = time.monotonic()
    control = control_budget or ControlBudget(deadline=started + 600)
    if type(control) is not ControlBudget or control.deadline > started + 600:
        raise ValueError('shared_bootstrap_control_deadline_required')
    with control_work(control):
        return _execute(plan_body, approval_body, trusted_verifier, control)


def _execute(plan_body, approval_body, trusted_verifier, control):
    if len(plan_body) > 65536 or len(approval_body) > 65536:
        raise ValueError('plan_or_approval_byte_bound')
    control.admit_read('private_plan_bytes', len(plan_body))
    control.admit_read('private_approval_bytes', len(approval_body))
    reviewed = registry(control)
    plan, approval, proof = admit(plan_body, approval_body, reviewed, trusted_verifier, control=control)
    control.check()
    ledger = Ledger(plan, approval, control)
    # Existing work is metadata-only, never a new attempt under a new alias.
    if ledger.root.exists():
        return ledger.read()
    paths = _paths(plan)
    ledger.create(proof)
    budget = PhaseBudget(deadline=control.deadline)
    budget.guard_directories((paths['archive'], paths['anchor'], paths['ledger'], paths['output'].parent, paths['cache'].parent))
    try:
        code = verify_code(plan, control)
        if _REGISTRY.get() is not None:
            raise ValueError('nested_plan_execution_refused')
        token = _REGISTRY.set(copy.deepcopy(reviewed))
        try:
            with exact_meter(budget):
                result = _candidate(paths, plan, approval, budget,
                                    code['contracts/historical-fees/reviewed-plan-admission-v2.schema.json'])
        finally:
            _REGISTRY.reset(token)
        verify_code(plan, control)
        registry(control)
        budget.check()
        frozen = copy.deepcopy(result)
        budget.closed = True
        return ledger.finish(frozen, frozen['phase_counters_final'])
    except BaseException as exc:
        budget.closed = True
        try:
            ledger.unknown(exc)
        except Exception:
            pass  # Permanent nonterminal claim is already ACCOUNTING_UNKNOWN.
        raise


def replay(plan_body, approval_body):
    """Bounded metadata inspection only: no authority, source reads or fresh caps."""
    meter = ControlBudget(deadline=time.monotonic() + 30)
    with control_work(meter):
        return _replay(plan_body, approval_body, meter)


def _replay(plan_body, approval_body, meter):
    for name, body in (('plan', plan_body), ('approval', approval_body)):
        if len(body) > 65536:
            raise ValueError('replay_control_byte_bound')
        meter.admit_read(name, len(body))
    plan, approval = parse(plan_body), parse(approval_body)
    validate_plan(plan, registry(meter))
    if approval.get('plan_sha256') != digest(plan_body):
        raise ValueError('replay_plan_identity_mismatch')
    ledger = Ledger(plan, approval, meter)
    if not ledger.root.exists():
        return {'status': 'DESIGN_UNAPPROVED', 'due': False}
    return ledger.read()
