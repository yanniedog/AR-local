"""Read-only hosted verification evidence, without Git fetch or remote shell text."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor

import pi_ci_release as release
from pi_ci_activate import PRODUCTION, STATE, RUNTIME, PROFILE_UNITS, check_profile, properties


def snapshot():
    deadline = time.monotonic() + 75
    def guard():
        if time.monotonic() >= deadline:
            raise RuntimeError('read-only snapshot deadline reached')
    profile = release.read(RUNTIME)
    check_profile(profile)
    current = release.read(STATE / 'accepted/current.json')
    if (current.get('schema') != 'ar-local-ci-accepted-v1'
            or not release.COMMIT.fullmatch(str(current.get('commit', '')))
            or not release.HEX.fullmatch(str(current.get('release_sha256', '')))):
        raise ValueError('accepted immutable release receipt unavailable')
    descriptor = release.read(STATE / 'accepted' / (current['release_sha256'] + '.json'), current['release_sha256'])
    if descriptor.get('commit') != current['commit']:
        raise ValueError('accepted source identity differs')
    plan = current.get('plan')
    if not isinstance(plan, str) or not release.HEX.fullmatch(plan):
        raise ValueError('accepted release lacks exact terminal plan')
    completed = release.read(STATE / 'completed' / (plan + '.json'))
    if (completed.get('plan') != plan or completed.get('result') != 'PASS'
            or completed.get('accepted_release_sha256') != current['release_sha256']
            or completed.get('restored_timers') is not True):
        raise ValueError('independent terminal restoration proof is unavailable')
    # No Git, hooks, configuration, imports or source execution occurs here.
    release.verify_tree(PRODUCTION, descriptor, guard)
    with ThreadPoolExecutor(max_workers=4) as pool:
        units = dict(zip(PROFILE_UNITS, pool.map(lambda unit: properties(
            unit, state_fields(unit)), PROFILE_UNITS)))
    guard()
    code = {name: row['sha256'] for name, row in descriptor['files'].items() if not name.startswith('.git/')}
    canonical = json.dumps(code, sort_keys=True, separators=(',', ':')).encode()
    return dict(schema='ar-local-ci-snapshot-v1', result='OBSERVED', commit=current['commit'],
                source_files_sha256=hashlib.sha256(canonical).hexdigest(), immutable_source_verified=True,
                effective_profile_verified=True, units=units, acceptance=current.get('acceptance', 'NOT_ASSESSED'),
                last_plan=current.get('plan'), public_payload='SEPARATE_HTTP_VERIFICATION_REQUIRED')


def check_snapshot(value, expected_commit):
    """Client-side fail-closed transport validation; does not grant approval."""
    if (not isinstance(value, dict) or value.get('schema') != 'ar-local-ci-snapshot-v1'
            or value.get('result') != 'OBSERVED' or value.get('commit') != expected_commit
            or value.get('immutable_source_verified') is not True
            or value.get('effective_profile_verified') is not True
            or not release.HEX.fullmatch(str(value.get('source_files_sha256', '')))
            or set(value.get('units', {})) != set(PROFILE_UNITS)):
        raise ValueError('restricted deployment snapshot is incomplete or differs from expected commit')
    for unit, state in value['units'].items():
        if set(state) != set(state_fields(unit)) or state['LoadState'] != 'loaded':
            raise ValueError('incomplete native unit state')
        if unit in ('ar-local-dashboard.service', 'ar-local-daily.timer') and state['ActiveState'] != 'active':
            raise ValueError('dashboard or mandatory natural ingest timer is inactive')
    return value


def state_fields(unit):
    common = ('LoadState', 'ActiveState', 'SubState')
    return (*common, 'Result', 'MainPID') if unit.endswith('.service') else common
