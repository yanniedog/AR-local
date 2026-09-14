"""Fixed May23 plan; private trusted-launcher approval is a separate boundary."""
from __future__ import annotations

import copy
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from cdr_historical_fee_ledger_io import canonical, digest, parse, read_control
from cdr_historical_fee_archive import safe_path
from cdr_historical_fee_plan_budget import CONTROL, ControlBudget

REGISTRY = 'contracts/historical-fees/may23-reviewed-registry-v1.json'
REGISTRY_SHA = '78906ab97dbd3cfa6d64cc0835d180015be1538ddfae44fbace9e1b296fbd314'
# Exact former Windows checkout: same reviewed bytes with one terminal CRLF.
_REGISTRY_CRLF_SHA = '44071664c6ab6867cde45821a5f7c87f2e4ce343d42b4203321b5308390eee58'
DEPENDENCIES = {'745': 'f4f5aa44129074a91b244e02adee90a8f9f3e212',
                '746': 'bc580b3d03527b18cb5aba66ecceb26228738fee'}
CODE_FILES = frozenset((
    'cdr_historical_fee_plan.py', 'cdr_historical_fee_plan_budget.py',
    'cdr_historical_fee_ledger.py', 'cdr_historical_fee_ledger_io.py',
    'cdr_historical_fee_plan_candidate.py', 'cdr_historical_fee_archive.py',
    'cdr_historical_fee_archive_admission.py', 'cdr_historical_fee_archive_candidate.py',
    'cdr_historical_fee_exact.py', 'cdr_historical_fee_embedded.py',
    'cdr_historical_fee_membership.py', 'cdr_historical_fee_admission.py',
    'app_payload_details.py', 'app_payload_common.py', 'cdr_clean_export.py',
    'cdr_savings_conditions.py', 'contracts/historical-fees/reviewed-plan-admission-v2.schema.json'))
PATHS = frozenset(('archive', 'anchor', 'cache', 'output', 'ledger'))


def keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('closed_contract_keys_required')


def hash_value(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('canonical_sha256_required')
    return value


def uuid_value(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError('canonical_uuid_required')
    return value


def owner_value(value):
    keys(value, ('instance_id', 'boot_id', 'pid', 'process_start', 'executable_sha256'))
    for key in ('instance_id', 'boot_id'):
        uuid_value(value[key])
    if type(value['pid']) is not int or value['pid'] <= 0:
        raise ValueError('owner_pid_required')
    if type(value['process_start']) is not str or not value['process_start'] or len(value['process_start']) > 128:
        raise ValueError('owner_start_identity_required')
    hash_value(value['executable_sha256'])


def registry(meter):
    body = read_control(Path(__file__).parent / REGISTRY, meter)
    raw_sha = digest(body)
    if len(body) == 2644 and raw_sha == _REGISTRY_CRLF_SHA:
        # Authenticate the entire raw representation before adapting its sole
        # line ending. Never normalize arbitrary JSON or mutate retained files.
        body = body[:-2] + b'\n'
        raw_sha = digest(body)
    if raw_sha != REGISTRY_SHA:
        raise ValueError('reviewed_registry_changed')
    return parse(body)


def work_id(value):
    # Match the reviewed proposal's newline-terminated canonical identity.
    return digest(canonical(value['work_identity']))


def validate_plan(value, reviewed):
    keys(value, ('schema_version', 'registry_sha256', 'work_id', 'code', 'paths', 'limits', 'dependency_commits'))
    if (type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['registry_sha256'] != REGISTRY_SHA or value['work_id'] != work_id(reviewed)
            or canonical(value['limits']) != canonical(reviewed['budgets'])
            or value['dependency_commits'] != DEPENDENCIES):
        raise ValueError('unreviewed_plan_or_budget')
    keys(value['code'], CODE_FILES)
    for row in value['code'].values():
        keys(row, ('bytes', 'sha256', 'lf_sha256'))
        if type(row['bytes']) is not int or not 0 < row['bytes'] <= 1024**2:
            raise ValueError('code_identity_byte_bound')
        hash_value(row['sha256'])
        hash_value(row['lf_sha256'])
    keys(value['paths'], PATHS)
    for path in value['paths'].values():
        if type(path) is not str or not Path(path).is_absolute() or len(path) > 4096:
            raise ValueError('absolute_private_execution_path_required')


def _cached_identity(path):
    info = safe_path(path).stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _cache_entries(plan, meter, bodies):
    keys(plan['code'], CODE_FILES)
    keys(bodies, CODE_FILES)
    if sum(len(body) for body in bodies.values() if type(body) is bytes) > CONTROL:
        raise ValueError('bootstrap_cache_byte_bound')
    entries = []
    for name in sorted(CODE_FILES):
        body, expected = bodies[name], plan['code'][name]
        if type(body) is not bytes or not 0 < len(body) <= 1024**2:
            raise ValueError('bootstrap_cache_body_required')
        path = safe_path(Path(__file__).parent / name)
        identity = _cached_identity(path)
        receipt = meter.completed_reads.get(str(path))
        if (not identity[1] or meter.reads.get(str(path)) != 1 or receipt != (1, identity, len(body))):
            raise ValueError('bootstrap_first_read_receipt_required')
        # Resident raw and LF hash passes consume the same meter, even when no
        # control_work context is active during trusted bootstrap construction.
        meter.charge('read_checksum', 2 * len(body))
        if (len(body) != expected['bytes'] or hashlib.sha256(body).hexdigest() != expected['sha256']
                or hashlib.sha256(body.replace(b'\r\n', b'\n')).hexdigest() != expected['lf_sha256']):
            raise ValueError('reviewed_code_identity_mismatch')
        meter.check()
        if _cached_identity(path) != identity:
            raise ValueError('bootstrap_code_identity_changed')
        entries.append((name, str(path), identity, body))
    return tuple(entries)


def _cache_digest(entries, meter):
    # Identity nanoseconds may exceed the exact JSON integer range; decimal text
    # preserves them without changing the public financial counter grammar.
    manifest = [{'name': name, 'path': path, 'file_identity': [str(v) for v in identity]}
                for name, path, identity, _ in entries]
    for row, (_, _, _, body) in zip(manifest, entries):
        meter.charge('read_checksum', 2 * len(body))
        row.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                   lf_sha256=hashlib.sha256(body.replace(b'\r\n', b'\n')).hexdigest())
    encoded = canonical(manifest)
    meter.charge('read_checksum', len(encoded))
    result = hashlib.sha256(encoded).hexdigest()
    meter.check()
    return result


@dataclass(frozen=True)
class BootstrapCodeCache:
    """Resident evidence for a separately trusted launcher, not authentication."""
    sha256: str
    _meter: ControlBudget = field(repr=False, compare=False)
    _deadline: float = field(repr=False)
    _entries: tuple = field(repr=False)
    _consumed: bool = field(default=False, init=False, repr=False)

    def check_binding(self, meter):
        if (type(meter) is not ControlBudget or self._meter is not meter
                or type(meter.deadline) not in (int, float) or not math.isfinite(meter.deadline)
                or self._deadline != meter.deadline or self._consumed):
            raise ValueError('bootstrap_cache_meter_deadline_or_lifetime_mismatch')
        meter.check()

    def consume(self, plan, meter):
        self.check_binding(meter)
        # Failed cache validation cannot silently retry this first pass.
        object.__setattr__(self, '_consumed', True)
        bodies = {name: body for name, _, _, body in self._entries}
        entries = _cache_entries(plan, meter, bodies)
        if entries != self._entries or _cache_digest(entries, meter) != self.sha256:
            raise ValueError('bootstrap_cache_identity_mismatch')
        return bodies


def seal_bootstrap_code(plan, control, resident_bodies):
    """Seal already-read bytes against successful read1 on the original meter.

    This never reads source files. The trusted bootstrap must load code from
    these exact bytes and transfer every prior debit/read into this same meter.
    """
    if (type(control) is not ControlBudget or type(control.deadline) not in (int, float)
            or not math.isfinite(control.deadline)):
        raise ValueError('same_concrete_control_budget_required')
    control.check()
    entries = _cache_entries(plan, control, resident_bodies)
    return BootstrapCodeCache(_cache_digest(entries, control), control, control.deadline, entries)


def verify_code(plan, meter, *, bootstrap_cache=None):
    if bootstrap_cache is not None:
        if type(bootstrap_cache) is not BootstrapCodeCache:
            raise ValueError('sealed_bootstrap_cache_required')
        return bootstrap_cache.consume(plan, meter)
    bodies = {}
    for name, identity in plan['code'].items():
        body = read_control(Path(__file__).parent / name, meter, limit=1024**2)
        meter.charge('read_checksum', len(body))  # Independent LF checksum pass.
        if (len(body) != identity['bytes'] or digest(body) != identity['sha256']
                or digest(body.replace(b'\r\n', b'\n')) != identity['lf_sha256']):
            raise ValueError('reviewed_code_identity_mismatch')
        bodies[name] = body
    return bodies


@dataclass(frozen=True)
class TrustedAttestation:
    """Issued by the separately reviewed launcher, never decoded from source JSON.

    The launcher must authenticate explicit root canary approval, immutable code,
    the one persistent ledger root, current OS process/boot/start identity and
    the 660s outer supervisor. This class itself is not an authentication system.
    """
    plan_sha256: str
    approval_sha256: str
    ledger_root: str
    owner_sha256: str
    launcher_sha256: str
    outer_timeout_seconds: int
    bootstrap_cache_sha256: str | None = None


def admit(plan_body, approval_body, reviewed, verifier, *, control=None, bootstrap_cache=None):
    if verifier is None or not callable(verifier):
        raise ValueError('trusted_root_canary_verifier_required')
    plan, approval = parse(plan_body), parse(approval_body)
    validate_plan(plan, reviewed)
    keys(approval, ('schema_version', 'kind', 'plan_sha256', 'work_id', 'attempt_id',
                    'budget_scope_id', 'approval_id', 'owner', 'prior_scopes'))
    if (type(approval['schema_version']) is not int or approval['schema_version'] != 1
            or approval['kind'] != 'ROOT_APPROVED_SINGLE_LOCAL_ATTEMPT'
            or approval['plan_sha256'] != digest(plan_body) or approval['work_id'] != plan['work_id']
            or approval['prior_scopes'] != []):
        raise ValueError('exact_initial_root_approval_required')
    for key in ('attempt_id', 'budget_scope_id', 'approval_id'):
        uuid_value(approval[key])
    owner_value(approval['owner'])
    # The verifier is trusted launcher code, not a source-supplied callable.
    # Every authentication/closure read made here must use the same explicit
    # control allowance. Its implementation is part of the reviewed launcher.
    if bootstrap_cache is None:
        proof = verifier(plan_body, approval_body, control=control)
    else:
        if type(bootstrap_cache) is not BootstrapCodeCache:
            raise ValueError('sealed_bootstrap_cache_required')
        bootstrap_cache.check_binding(control)
        proof = verifier(plan_body, approval_body, control=control, bootstrap_cache=bootstrap_cache)
    if (type(proof) is not TrustedAttestation or proof.plan_sha256 != digest(plan_body)
            or proof.approval_sha256 != digest(approval_body) or proof.ledger_root != plan['paths']['ledger']
            or proof.owner_sha256 != digest(canonical(approval['owner']))
            or type(proof.outer_timeout_seconds) is not int or proof.outer_timeout_seconds != 660):
        raise ValueError('trusted_attestation_binding_mismatch')
    hash_value(proof.launcher_sha256)
    expected_cache = None if bootstrap_cache is None else bootstrap_cache.sha256
    if proof.bootstrap_cache_sha256 != expected_cache:
        raise ValueError('trusted_bootstrap_cache_binding_mismatch')
    return plan, approval, proof


def archive_profile(profile):
    if profile != 'may23-reviewed-original-anchor-fees-v2':
        raise ValueError('unreviewed_archive_profile')
    # Static bytes are rechecked through the admitted control meter before this
    # seam is called. Avoid a second unmetered registry read here.
    from cdr_historical_fee_plan_candidate import active_registry
    value = active_registry()
    meta, work = value['source_metadata_pins'], value['work_identity']
    pins = {'source-manifest.json': meta['source_manifest'], 'receipt.json': meta['backup_receipt'],
            'observation.tar.zst': work['source_archive']}
    source = dict(work['selected_export'])
    source['path'] = source.pop('archive_member')
    anchor = {role: {key: row[key] for key in ('bytes', 'sha256')} for role, row in work['parent']['assets'].items()}
    return work['observation_date'], copy.deepcopy(pins), source, anchor
