"""One permanent May23 work claim with a bounded append-only attempt journal."""
from __future__ import annotations

import copy
import time
from datetime import datetime, timezone
from pathlib import Path

from cdr_historical_fee_archive import safe_path
from cdr_historical_fee_ledger_io import canonical, digest, names, parse, read_control, same_links, write_record
from cdr_historical_fee_plan import hash_value, keys, owner_value
from cdr_historical_fee_plan_budget import CONTROL, LIMITS, integer

MAX_RECORDS = 128
PAYLOADS = {
    'SCOPE_GRANTED': {'approval_sha256', 'registry_sha256', 'limits', 'control_precharged', 'launcher_sha256'},
    'ATTEMPT_RESERVED': {'paths', 'remaining_deadline_nanoseconds', 'phase_limits'},
    'PHASE_RESERVED': {'limits'},
    'PHASE_SETTLED': {'reservation_sha256', 'counts', 'result_sha256'},
    'ATTEMPT_TERMINAL': {'status', 'result', 'body_integrity', 'automatic_reuse'},
    'ACCOUNTING_UNKNOWN': {'reason', 'reservation_sha256', 'upper_bounds', 'automatic_reuse'},
}
SEQUENCE = ('SCOPE_GRANTED', 'ATTEMPT_RESERVED', 'PHASE_RESERVED', 'PHASE_SETTLED', 'ATTEMPT_TERMINAL')


def _counts(value):
    if type(value) is not dict or not set(value) <= LIMITS.keys():
        raise ValueError('counter_shape_invalid')
    for key, amount in value.items():
        if integer(amount) > LIMITS[key]:
            raise ValueError('settlement_exceeds_phase_grant')


def _result(value, plan, approval):
    keys(value, ('candidate_receipt', 'candidate_receipt_value', 'phase_counters_final'))
    _counts(value['phase_counters_final'])
    identity, receipt = value['candidate_receipt'], value['candidate_receipt_value']
    keys(identity, ('bytes', 'sha256'))
    body = canonical(receipt)[:-1]
    if type(identity['bytes']) is not int or identity['bytes'] != len(body) or identity['sha256'] != digest(body):
        raise ValueError('candidate_receipt_snapshot_mismatch')
    if (receipt.get('work_id') != plan['work_id'] or receipt.get('plan_sha256') != approval['plan_sha256']
            or receipt.get('observation_date') != '2026-05-23' or receipt.get('publication') != 'NOT_ATTEMPTED'
            or receipt.get('result') != 'CANDIDATE_SEALED_UNREVIEWED'):
        raise ValueError('candidate_receipt_scope_mismatch')


def _record(value, plan, approval, previous, sequence):
    keys(value, ('schema_version', 'record_type', 'work_id', 'plan_sha256', 'budget_scope_id',
                 'attempt_id', 'sequence', 'previous_record_sha256', 'recorded_at_utc', 'owner', 'payload'))
    if (type(value['schema_version']) is not int or value['schema_version'] != 1
            or type(value['sequence']) is not int or value['sequence'] != sequence
            or value['previous_record_sha256'] != previous
            or value['work_id'] != plan['work_id'] or value['plan_sha256'] != approval['plan_sha256']
            or value['budget_scope_id'] != approval['budget_scope_id'] or value['attempt_id'] != approval['attempt_id']
            or canonical(value['owner']) != canonical(approval['owner'])):
        raise ValueError('ledger_identity_or_sequence_mismatch')
    owner_value(value['owner'])
    stamp = value['recorded_at_utc']
    if type(stamp) is not str or not stamp.endswith('+00:00'):
        raise ValueError('ledger_utc_instant_required')
    datetime.fromisoformat(stamp)
    kind, payload = value['record_type'], value['payload']
    if kind not in PAYLOADS:
        raise ValueError('unsupported_ledger_record')
    keys(payload, PAYLOADS[kind])
    if kind == 'ACCOUNTING_UNKNOWN':
        if sequence == 0 or payload['automatic_reuse'] is not False or payload['upper_bounds'] != LIMITS:
            raise ValueError('unknown_accounting_must_retain_full_reservation')
        if type(payload['reason']) is not str or len(payload['reason']) > 1000:
            raise ValueError('unknown_reason_bound')
    elif sequence >= len(SEQUENCE) or kind != SEQUENCE[sequence]:
        raise ValueError('ledger_transition_refused')
    if kind == 'SCOPE_GRANTED':
        if (payload['limits'] != plan['limits'] or payload['control_precharged'] != CONTROL
                or payload['registry_sha256'] != plan['registry_sha256']):
            raise ValueError('scope_budget_or_registry_mismatch')
        hash_value(payload['approval_sha256'])
        hash_value(payload['launcher_sha256'])
    elif kind == 'ATTEMPT_RESERVED':
        if payload['paths'] != plan['paths'] or payload['phase_limits'] != LIMITS:
            raise ValueError('attempt_path_or_budget_mismatch')
        if integer(payload['remaining_deadline_nanoseconds']) > 600 * 10**9:
            raise ValueError('shared_deadline_bound')
    elif kind == 'PHASE_RESERVED' and payload['limits'] != LIMITS:
        raise ValueError('phase_budget_mismatch')
    elif kind == 'PHASE_SETTLED':
        _counts(payload['counts'])
        hash_value(payload['reservation_sha256'])
        hash_value(payload['result_sha256'])
    elif kind == 'ATTEMPT_TERMINAL':
        if (payload['status'] != 'SEALED_UNREVIEWED' or payload['automatic_reuse'] is not False
                or payload['body_integrity'] != 'AT_ATTEMPT_ONLY'):
            raise ValueError('terminal_cannot_authorize_new_work')
        _result(payload['result'], plan, approval)


class Ledger:
    def __init__(self, plan, approval, meter):
        self.plan, self.approval = copy.deepcopy(plan), copy.deepcopy(approval)
        self.meter = meter
        self.root = safe_path(plan['paths']['ledger'], directory=True) / plan['work_id']
        self.records, self.hashes = [], []
        self.expected_names = set()
        self.directory_identity = None

    def _directory(self):
        info = safe_path(self.root, directory=True).stat()
        identity = (info.st_dev, info.st_ino)
        if not info.st_ino or self.directory_identity is not None and identity != self.directory_identity:
            raise ValueError('ledger_directory_identity_changed')
        self.directory_identity = identity
        return names(self.root, MAX_RECORDS * 3)

    def create(self, proof):
        # mkdir is the single-owner, create-once admission. It is never removed,
        # even after a crash before the first record or after a settled result.
        self.root.mkdir()
        self._directory()
        self.append('SCOPE_GRANTED', {'approval_sha256': proof.approval_sha256,
                    'registry_sha256': self.plan['registry_sha256'], 'limits': self.plan['limits'],
                    'control_precharged': CONTROL, 'launcher_sha256': proof.launcher_sha256})
        self.append('ATTEMPT_RESERVED', {'paths': self.plan['paths'], 'phase_limits': dict(LIMITS),
                    'remaining_deadline_nanoseconds': max(0, int((self.meter.deadline - time.monotonic()) * 10**9))})
        return self.append('PHASE_RESERVED', {'limits': dict(LIMITS)})

    def append(self, kind, payload):
        self.meter.check()
        if self._directory() != self.expected_names:
            raise ValueError('ledger_orphan_fork_or_changed_head')
        seq = len(self.records)
        if seq >= MAX_RECORDS or self.records and self.records[-1]['record_type'] in ('ACCOUNTING_UNKNOWN', 'ATTEMPT_TERMINAL'):
            raise ValueError('ledger_terminal_or_record_bound')
        value = {'schema_version': 1, 'record_type': kind, 'work_id': self.plan['work_id'],
                 'plan_sha256': self.approval['plan_sha256'], 'budget_scope_id': self.approval['budget_scope_id'],
                 'attempt_id': self.approval['attempt_id'], 'sequence': seq,
                 'previous_record_sha256': self.hashes[-1] if self.hashes else None,
                 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
                 'owner': self.approval['owner'], 'payload': payload}
        _record(value, self.plan, self.approval, value['previous_record_sha256'], seq)
        identity = write_record(self.root, seq, value, self.meter)
        self.records.append(copy.deepcopy(value))
        self.hashes.append(identity)
        self.expected_names.update((f'{seq:03}.pending', f'{seq:03}.head', identity + '.record'))
        return identity

    def read(self):
        inventory = self._directory()
        if not inventory or len(inventory) % 3:
            raise ValueError('ledger_partial_or_missing_head')
        count = len(inventory) // 3
        previous = None
        for seq in range(count):
            body = read_control(self.root / f'{seq:03}.head', self.meter)
            identity, value = digest(body), parse(body)
            same_links(self.root, seq, identity)
            _record(value, self.plan, self.approval, previous, seq)
            if self.records and self.records[-1]['record_type'] in ('ACCOUNTING_UNKNOWN', 'ATTEMPT_TERMINAL'):
                raise ValueError('records_after_terminal')
            self.records.append(value)
            self.hashes.append(identity)
            self.expected_names.update((f'{seq:03}.pending', f'{seq:03}.head', identity + '.record'))
            previous = identity
        if inventory != self.expected_names or self._directory() != inventory:
            raise ValueError('ledger_unknown_inventory')
        if self.records[0]['payload']['approval_sha256'] != digest(canonical(self.approval)):
            raise ValueError('ledger_approval_changed')
        return self.status()

    def status(self):
        binding = {'work_id': self.plan['work_id'], 'plan_sha256': self.approval['plan_sha256'],
                   'budget_scope_id': self.approval['budget_scope_id'], 'attempt_id': self.approval['attempt_id'],
                   'head_sha256': self.hashes[-1] if self.hashes else None, 'control_precharged': CONTROL}
        if not self.records or self.records[-1]['record_type'] != 'ATTEMPT_TERMINAL':
            return {**binding, 'status': 'ACCOUNTING_UNKNOWN', 'due': False, 'upper_bounds': dict(LIMITS),
                    'reason': 'No complete accepted terminal; no automatic reuse.'}
        settlement, terminal = self.records[-2]['payload'], self.records[-1]['payload']
        body = canonical(terminal['result'])
        self.meter.charge('read_checksum', len(body))
        if settlement['result_sha256'] != digest(body) or settlement['reservation_sha256'] != self.hashes[2]:
            raise ValueError('terminal_settlement_identity_mismatch')
        if terminal['result']['phase_counters_final'] != settlement['counts']:
            raise ValueError('terminal_counter_snapshot_mismatch')
        return {**binding, 'status': 'SEALED_UNREVIEWED', 'due': False, 'body_integrity': 'NOT_RECHECKED',
                'result': copy.deepcopy(terminal['result'])}

    def finish(self, result, counts):
        _counts(counts)
        _result(result, self.plan, self.approval)
        if result['phase_counters_final'] != counts:
            raise ValueError('terminal_counter_snapshot_mismatch')
        body = canonical(result)
        self.meter.charge('read_checksum', len(body))
        self.append('PHASE_SETTLED', {'reservation_sha256': self.hashes[2], 'counts': copy.deepcopy(counts),
                                     'result_sha256': digest(body)})
        self.append('ATTEMPT_TERMINAL', {'status': 'SEALED_UNREVIEWED', 'result': copy.deepcopy(result),
                    'body_integrity': 'AT_ATTEMPT_ONLY', 'automatic_reuse': False})
        return self.status()

    def unknown(self, error):
        # If even this cannot be committed, the nonterminal permanent claim
        # already means unknown. No fresh reserve or cleanup is granted.
        return self.append('ACCOUNTING_UNKNOWN', {'reason': str(error)[:1000],
                           'reservation_sha256': self.hashes[2] if len(self.hashes) > 2 else None,
                           'upper_bounds': dict(LIMITS), 'automatic_reuse': False})
