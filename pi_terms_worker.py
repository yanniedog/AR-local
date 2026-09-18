"""At most one bounded subscription job, with durable account-wide backoff.

Only the derived evidence queue and private receipts are writable. Successful
format/binding validation means staging only: independent review is separate.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import time as monotonic_time
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jsonschema.exceptions import ValidationError

from ar_local_operation_lock import production_lock
from cdr_atomic import atomic_write_json
from cdr_terms.identity import byte_digest, canonical_json, timestamp
from cdr_terms.queue import STAGING_SCHEMA, StagingValidationError, TermsQueue, staging_schema
from cdr_terms.store import EvidenceStore
from pi_cdr_quality_resources import Limits, require_receipt, supervise
from pi_terms_codex import (MAX_INPUT_BYTES, MAX_LOG_BYTES, MAX_RECEIPT_BYTES,
                            MAX_RESULT_BYTES, file_hash, input_hashes, private_directory,
                            read_bounded, subscription_environment, write_receipt)

HOBART = ZoneInfo('Australia/Hobart')
STATE_NAME = 'interpreter-state.json'
PUBLIC_CONTEXT_FIELDS = frozenset({
    'product_keys', 'source_product_sha256', 'document_schema_version',
    'structured_fact_normalization', 'interpretation_contract', 'executable_rules',
    'historical_target', 'incorporated_target', 'parameter_registry', 'interpretation_schema_sha256',
    'structure_review',
})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parsed_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('retry timestamp requires timezone')
    return result.astimezone(timezone.utc)


def operating_window(now: datetime) -> bool:
    local = now.astimezone(HOBART)
    return time(3, 30) <= local.time().replace(tzinfo=None) < time(21, 45)


def runtime_window(now: datetime) -> bool:
    local = now.astimezone(HOBART)
    return time(3, 30) <= local.time().replace(tzinfo=None) < time(22)


def admission(repo: Path, root: Path, now: datetime) -> str | None:
    if sys.platform != 'linux':
        return 'pi_linux_runtime_required'
    if not operating_window(now):
        return 'outside_analysis_window'
    if shutil.disk_usage(root).free < 2 * 1024**3:
        return 'analysis_disk_reserve'
    from pi_cdr_recovery import recovery_block_reason
    from pi_daily_sync import payload_publication_pending
    blocked = recovery_block_reason(repo)
    if blocked:
        return blocked
    return 'publication_pending' if payload_publication_pending(repo) else None


def priority_guard(repo: Path, root: Path) -> str | None:
    """Fast fail-closed reads every resource tick; no systemctl subprocess.

    The prelaunch admission also checks service activation. While running we
    observe unit membership and the shared lock, including its creation race.
    A stale lock defers conservatively; this worker never reclaims that lock.
    """
    from ar_local_pi_runtime import data_state_root
    from pi_cdr_recovery import _backup_source_active
    from pi_daily_sync import payload_publication_pending
    try:
        if not runtime_window(utc_now()):
            return 'outside_analysis_window'
        if (data_state_root(repo) / 'daily-ingest.lock').exists():
            return 'production_ingest_or_backup_lock_present'
        units = Path('/sys/fs/cgroup/system.slice')
        if not units.is_dir():
            return 'production_activity_unavailable'
        for name in ('ar-local-daily.service', 'ar-local-ingest-now.service'):
            unit = units / name
            if unit.exists() and (unit / 'cgroup.procs').read_text().strip():
                return 'scheduled_or_manual_ingest_active'
        if payload_publication_pending(repo):
            return 'publication_pending'
        if _backup_source_active():
            return 'backup_source_active'
        if shutil.disk_usage(root).free < 2 * 1024**3:
            return 'analysis_disk_reserve'
    except (OSError, RuntimeError, ValueError):
        return 'production_activity_unavailable'
    return None


def prepare_job(store: EvidenceStore, job: dict, root: Path) -> None:
    if root.resolve() != root:
        raise ValueError('canonical private operation root required')
    context = TermsQueue(store).validate_input(job['job_id'])
    if not isinstance(context, dict) or set(context) - PUBLIC_CONTEXT_FIELDS:
        raise ValueError('unreviewed interpreter context; customer profiles are never uploaded')
    payload = {'extraction_id': job['extraction_id'], 'context_sha256': job['context_sha256'],
               'context': context,
               'source_text': store.read_blob(job['text_sha256']).decode('utf-8')}
    from cdr_terms.structured_admission import validate_context
    structure = validate_context(store, job['extraction_id'], context)
    if structure is not None:
        payload['reviewed_structure'] = structure
    if 'historical_target' in context:
        from cdr_terms.historical import historical_scope
        payload['expected_historical_scope'] = historical_scope(context['historical_target'])
    if 'incorporated_target' in context:
        from cdr_terms.incorporated import output_scope
        payload['expected_incorporated_scope'] = output_scope(context['incorporated_target'])
    if len(canonical_json(payload).encode('utf-8')) > MAX_INPUT_BYTES:
        raise ValueError('complete_document_chunking_required')
    root.mkdir(parents=True, mode=0o700)
    write_receipt(root / 'input.json', payload)
    from cdr_terms.transport_schema import transport_generation_schema
    write_receipt(root / 'schema.json', transport_generation_schema(context))
    binding={key: job[key] for key in
             ('job_id', 'lease_id', 'extraction_id', 'document_version_id', 'context_sha256')}
    if 'interpretation_schema_sha256' in context:
        binding['generation_schema_sha256']=byte_digest((root/'schema.json').read_bytes())
    write_receipt(root / 'binding.json', binding)


def complete_job(queue: TermsQueue, job: dict, root: Path, resources: dict) -> dict:
    require_receipt(resources)
    binding = json.loads(read_bounded(root / 'binding.json', MAX_RECEIPT_BYTES))
    expected={key: job[key] for key in
              ('job_id', 'lease_id', 'extraction_id', 'document_version_id', 'context_sha256')}
    context=queue.validate_input(job['job_id'])
    if 'interpretation_schema_sha256' in context:
        from cdr_terms.transport_schema import transport_generation_schema
        raw=read_bounded(root/'schema.json',MAX_RESULT_BYTES)
        if json.loads(raw)!=transport_generation_schema(context):raise ValueError('generation schema changed')
        expected['generation_schema_sha256']=byte_digest(raw)
    if binding != expected:
        raise ValueError('transport binding does not identify the current lease')
    transport = read_transport(root)
    if transport['result'] != 'STAGING_ONLY':
        raise ValueError('successful transport receipt required')
    result = read_bounded(root / 'result.json', MAX_RESULT_BYTES)
    if byte_digest(result) != transport.get('result_sha256'):
        raise ValueError('staging output changed after transport')
    staged = queue.save_staging(job['job_id'], json.loads(result), lease_id=job['lease_id'])
    receipt = {'result': 'STAGED', 'job_id': job['job_id'], 'staging_sha256': staged,
               'codex_called': transport['codex_called'], 'validation': 'FORMAT_AND_BINDING_ONLY',
               'publication': 'NOT_ATTEMPTED'}
    context = queue.validate_input(job['job_id'])
    if 'historical_target' in context:
        from cdr_terms.historical import historical_scope
        receipt.update(result='STAGED_HISTORICAL', historical_scope=historical_scope(context['historical_target']),
                       current_publication='PROHIBITED_HISTORICAL_SCOPE')
    if 'incorporated_target' in context:
        from cdr_terms.incorporated import output_scope
        receipt.update(result='STAGED_INCORPORATED_CANDIDATE', incorporated_scope=output_scope(context['incorporated_target']),
                       current_publication='PROHIBITED_UNREVIEWED_APPLICABILITY')
    return receipt


def read_transport(root: Path) -> dict:
    value = json.loads(read_bounded(root / 'transport.json', MAX_RECEIPT_BYTES))
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('invalid transport receipt')
    if value.get('result') not in {'STAGING_ONLY', 'DEFERRED'}:
        raise ValueError('invalid transport outcome')
    if value.get('codex_called') is not None and type(value['codex_called']) is not bool:
        raise ValueError('invalid call state')
    if parsed_time(value['finished_at']) < parsed_time(value['started_at']):
        raise ValueError('invalid transport timestamps')
    if any(value.get(key) != digest for key, digest in input_hashes(root).items()):
        raise ValueError('transport is bound to different inputs')
    for name in ('events.jsonl', 'stderr.log'):
        digest = value.get(name.replace('.', '_') + '_sha256')
        if digest is not None and digest != file_hash(root / name, MAX_LOG_BYTES):
            raise ValueError('transport diagnostics changed')
    return value


def read_state(root: Path) -> dict:
    path = root / STATE_NAME
    if path.is_symlink():
        raise ValueError('worker cooldown cannot be a symbolic link')
    if not path.exists():
        return {'schema_version': 1, 'failures': 0}
    value = json.loads(read_bounded(path, MAX_RECEIPT_BYTES))
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('invalid worker cooldown state')
    if type(value.get('failures')) is not int or not 0 <= value['failures'] <= 100:
        raise ValueError('invalid worker failure counter')
    if value.get('retry_after'):
        parsed_time(value['retry_after'])
    return value


def retry_deadline(reason: str, failures: int, now: datetime, reset_at: str | None = None) -> tuple[str, str]:
    if reason == 'quota' and reset_at:
        reset = parsed_time(reset_at)
        if now < reset <= now + timedelta(days=8):
            return timestamp(max(reset + timedelta(minutes=1), now + timedelta(minutes=15)).isoformat()), 'structured_reset'
    minutes, ceiling = {'quota': (120, 1440), 'authentication': (60, 1440),
                        'priority': (15, 60)}.get(reason, (30, 360))
    delay = min(ceiling, minutes * 2 ** min(max(failures - 1, 0), 6))
    return timestamp((now + timedelta(minutes=delay)).isoformat()), 'conservative_backoff'


def transition_owned(queue: TermsQueue, job: dict, status: str, *, reason: str, retry_after=None) -> str:
    """Never overwrite a superseding source or a replacement lease."""
    row = queue.store.db.execute('SELECT * FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1',
                                 (job['job_id'],)).fetchone()
    if row is None or row['status'] != 'running' or row['lease_id'] != job['lease_id']:
        return 'SUPERSEDED' if row and row['status'] == 'superseded' else 'STALE'
    if row['lease_expires_at'] <= timestamp(utc_now().isoformat()):
        return 'STALE'
    try:
        queue.event(job['job_id'], status, lease_id=job['lease_id'], error_code=reason, retry_after=retry_after)
    except ValueError:
        # The queue's compare-and-set can reject a race after this snapshot.
        return 'STALE'
    return 'BLOCKED' if status == 'blocked' else 'DEFERRED'


def reconcile_auth(queue: TermsQueue, state: dict, auth_sha: str, now: datetime) -> bool:
    if state.get('reason') != 'authentication':
        return False
    changed = state.get('auth_sha256') != auth_sha
    due = parsed_time(state['retry_after']) <= now
    if not (changed or due):
        return False
    job_id = state.get('job_id')
    row = queue.store.db.execute('SELECT status,error_code FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 1',
                                 (job_id,)).fetchone()
    if row and row['status'] == 'blocked' and row['error_code'] == 'interpreter_authentication_required':
        queue.event(job_id, 'queued', error_code='saved_subscription_auth_reconciled')
    return True


def defer(queue: TermsQueue, job: dict, root: Path, state: dict, reason: str,
          auth_sha: str, *, reset_at=None, codex_called=None) -> dict:
    failures = min(state.get('failures', 0) + 1, 100)
    retry_after, basis = retry_deadline(reason, failures, utc_now(), reset_at)
    updated = {'schema_version': 1, 'failures': failures, 'reason': reason,
               'retry_after': retry_after, 'retry_basis': basis,
               'job_id': job['job_id'], 'auth_sha256': auth_sha}
    # Account cooldown is written first, so a crash cannot hammer another job.
    atomic_write_json(root / STATE_NAME, updated)
    error = 'interpreter_authentication_required' if reason == 'authentication' else 'interpreter_' + reason
    status = transition_owned(queue, job, 'blocked' if reason == 'authentication' else 'retry_wait',
                              reason=error, retry_after=None if reason == 'authentication' else retry_after)
    return {'result': status, 'reason': error, 'job_id': job['job_id'], 'retry_after': retry_after,
            'retry_basis': basis, 'codex_called': codex_called, 'publication': 'NOT_ATTEMPTED'}


def process_job(queue: TermsQueue, job: dict, repo: Path, root: Path, auth_home: Path,
                executable: Path, state: dict, auth_sha: str) -> dict:
    operation = root / 'interpreter-runs' / uuid.uuid4().hex
    try:
        prepare_job(queue.store, job, operation)
    except (OSError, ValueError):
        result = {'result': transition_owned(queue, job, 'blocked', reason='complete_input_unavailable'),
                  'reason': 'complete_input_unavailable', 'job_id': job['job_id'], 'codex_called': False}
        return result
    command = [sys.executable, str(repo / 'pi_terms_codex.py'), '--codex-bin', str(executable),
               '--codex-home', str(auth_home), '--job-root', str(operation)]
    try:
        blocked = admission(repo, root, utc_now())
        if blocked:
            result = defer(queue, job, root, state, 'priority', auth_sha, codex_called=False)
        else:
            resources = supervise(command, operation / 'resources.json', Limits(runtime_seconds=720),
                                  priority_guard=lambda: priority_guard(repo, root))
            if resources.get('operational_outcome') == 'PRIORITY_YIELD':
                result = defer(queue, job, root, state, 'priority', auth_sha,
                               codex_called=False if resources.get('workload_started') is False else None)
            else:
                require_receipt(resources)
                transport = read_transport(operation)
                if transport['result'] == 'STAGING_ONLY':
                    result = complete_job(queue, job, operation, resources)
                    atomic_write_json(root / STATE_NAME, {'schema_version': 1, 'failures': 0})
                else:
                    reason = transport.get('reason')
                    if reason not in {'quota', 'authentication', 'timeout', 'transport'}:
                        reason = 'transport'
                    result = defer(queue, job, root, state, reason, auth_sha,
                                   reset_at=transport.get('reset_at'), codex_called=transport.get('codex_called'))
    except (ValidationError, StagingValidationError):
        result = {'result': transition_owned(queue, job, 'blocked', reason='invalid_staging_schema'),
                  'reason': 'invalid_staging_schema', 'job_id': job['job_id'], 'publication': 'NOT_ATTEMPTED'}
    except (OSError, ValueError, KeyError, RuntimeError):
        result = defer(queue, job, root, state, 'transport', auth_sha)
    write_receipt(operation / 'controller-result.json', result)
    return {**result, 'operation': str(operation)}


def run_one(repo: Path, root: Path, auth_home: Path, executable: Path) -> dict:
    from ar_local_pi_runtime import data_runs_root, data_state_root
    if root.resolve() != root or root.is_symlink():
        raise ValueError('private canonical evidence root outside checkout required')
    for protected in (repo, data_runs_root(repo), data_state_root(repo)):
        protected = protected.resolve()
        for private in (root, auth_home):
            resolved = private.resolve()
            if resolved == protected or protected in resolved.parents or resolved in protected.parents:
                raise ValueError('private evidence and auth must not overlap original sources or state')
    if auth_home == root or root in auth_home.parents or auth_home in root.parents:
        raise ValueError('separate dedicated auth and evidence directories required')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_directory(root)
    with production_lock(root / 'interpreter.lock', 'terms-interpreter'), EvidenceStore(root) as store:
        queue, now = TermsQueue(store), utc_now()
        blocked = admission(repo, root, now)
        if blocked:
            return {'result': 'DEFERRED', 'reason': blocked, 'codex_called': False}
        acquisition = collect_one(store, repo, root)
        if acquisition['result'] == 'DEFERRED':
            return acquisition
        result = interpret_one(queue, repo, root, auth_home, executable)
        return {**result, 'acquisition': acquisition}


def collect_one(store: EvidenceStore, repo: Path, root: Path) -> dict:
    from cdr_terms.acquisition_batch import ADMISSION_SECONDS, has_work
    from cdr_terms.ingest import registry_context
    if not has_work(store):
        return {'result': 'NO_WORK', 'network_called': False, 'codex_called': False}
    operation = root / 'acquisition-runs' / uuid.uuid4().hex
    if operation.resolve() != operation:
        raise ValueError('canonical private acquisition root required')
    operation.mkdir(parents=True, mode=0o700)
    write_receipt(operation / 'input.json', {'evidence_root': str(root), 'registry_context': registry_context(),
                  'admission_deadline': monotonic_time.monotonic() + ADMISSION_SECONDS})
    command = [sys.executable, str(repo / 'pi_terms_acquire.py'), '--job-root', str(operation)]
    try:
        resources = supervise(command, operation / 'resources.json', Limits(runtime_seconds=120),
                              priority_guard=lambda: priority_guard(repo, root))
        require_receipt(resources)
        result = read_acquisition_batch(operation, store=store)
        return {**result, 'operation': str(operation)}
    except (OSError, ValueError, KeyError, RuntimeError):
        # The acquisition queue owns its short lease and retry reconciliation.
        # The timer is the outer 15-minute cap if a child is interrupted.
        result = {'result': 'DEFERRED', 'reason': 'acquisition_not_accepted',
                  'network_called': None, 'codex_called': False, 'publication': 'NOT_ATTEMPTED'}
        write_receipt(operation / 'controller-result.json', result)
        return {**result, 'operation': str(operation)}


def read_acquisition_batch(operation: Path, *, store: EvidenceStore | None = None) -> dict:
    from cdr_terms.acquisition_batch import MAX_BATCH_RECEIPT_BYTES, validate_batch_evidence, validate_batch_receipt
    descriptor = json.loads(read_acquisition_file(operation, 'acquisition.json', MAX_RECEIPT_BYTES))
    body = read_acquisition_file(operation, 'batch.json', MAX_BATCH_RECEIPT_BYTES)
    result = json.loads(body)
    if not isinstance(descriptor, dict) or not isinstance(result, dict):
        raise ValueError('bound acquisition batch receipt required')
    if (type(descriptor.get('schema_version')) is not int or type(result.get('schema_version')) is not int
            or descriptor['schema_version'] != 2 or result['schema_version'] != 2
            or descriptor.get('batch_file_sha256') != byte_digest(body)
            or type(descriptor.get('batch_file_bytes')) is not int or descriptor['batch_file_bytes'] != len(body)
            or result.get('codex_called') is not False
            or result.get('input_sha256') != byte_digest(read_acquisition_file(operation, 'input.json', MAX_INPUT_BYTES))
            or any(result.get(key) != descriptor.get(key) for key in ('input_sha256', 'result', 'network_called', 'codex_called'))
            or result.get('result') not in {'NO_WORK', 'INCOMPLETE'}):
        raise ValueError('bound acquisition batch receipt required')
    validate_batch_receipt(result)
    if store is not None:
        validate_batch_evidence(store, result)
    return result


def read_acquisition_file(operation: Path, name: str, maximum: int) -> bytes:
    """Fixed private artifact paths, bounded bytes and stable unlinked identity."""
    private_directory(operation)
    path = operation / name
    if name not in {'batch.json', 'acquisition.json', 'input.json'} or path.resolve() != path:
        raise ValueError('canonical acquisition artifact required')
    before = path.lstat()
    def identity(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('regular unlinked acquisition artifact required')
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    expected = identity(before)
    with path.open('rb') as handle:
        if identity(os.fstat(handle.fileno())) != expected:
            raise ValueError('acquisition artifact changed before read')
        body = handle.read(maximum + 1)
        if identity(os.fstat(handle.fileno())) != expected:
            raise ValueError('acquisition artifact changed during read')
    if len(body) != before.st_size or identity(path.lstat()) != expected or path.resolve() != path:
        raise ValueError('acquisition artifact changed after read')
    return body


def interpret_one(queue: TermsQueue, repo: Path, root: Path, auth_home: Path, executable: Path) -> dict:
    now = utc_now()
    blocked = admission(repo, root, now)
    if blocked:
        return {'result': 'DEFERRED', 'reason': blocked, 'codex_called': False}
    state = read_state(root)
    # Read saved credentials afresh, allowing normal token refresh or a
    # repaired session to reconcile without network login or paid fallback.
    try:
        subscription_environment(auth_home, root)
        auth_sha = file_hash(auth_home / 'auth.json', 128 * 1024)
    except (OSError, ValueError):
        return {'result': 'DEFERRED', 'reason': 'saved_subscription_auth_unavailable', 'codex_called': False}
    reconciled = reconcile_auth(queue, state, auth_sha, now)
    if not reconciled and state.get('retry_after') and parsed_time(state['retry_after']) > now:
        return {'result': 'DEFERRED', 'reason': 'account_cooldown',
                'retry_after': state['retry_after'], 'codex_called': False}
    if not executable.is_absolute() or not executable.is_file():
        return {'result': 'DEFERRED', 'reason': 'installed_codex_unavailable', 'codex_called': False}
    # Claim also recovers expired leases; do not short-circuit on next_due.
    job = queue.claim(lease_seconds=900)
    if job is None:
        return {'result': 'NO_WORK', 'codex_called': False}
    return process_job(queue, job, repo, root, auth_home, executable, state, auth_sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--codex-home', type=Path, required=True)
    parser.add_argument('--codex-bin', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_one(Path(__file__).resolve().parent, args.evidence_root, args.codex_home, args.codex_bin)
    except (OSError, ValueError, RuntimeError):
        result = {'result': 'BLOCKED', 'reason': 'controller_admission_or_state_unavailable'}
    print(json.dumps(result))
    return 0 if result['result'] in {'STAGED', 'STAGED_HISTORICAL', 'NO_WORK', 'DEFERRED', 'SUPERSEDED', 'STALE'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
