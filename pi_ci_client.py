"""Hosted restricted protocol client. Never sends remote shell programs."""
from __future__ import annotations
import json
import os
import re
import subprocess

from pi_ci_snapshot import check_snapshot


def call(command, *, host, timeout=120):
    if not re.fullmatch(r'[A-Za-z0-9_.@:-]+', host) or host.startswith('-'):
        raise ValueError('invalid restricted SSH destination')
    if command != 'status' and not re.fullmatch(r'(?:check|activate) [0-9a-f]{64}', command):
        raise ValueError('unsupported restricted SSH request')
    response = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=30', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
        host, command], capture_output=True, text=True, timeout=timeout, shell=False, check=True)
    if len(response.stdout.encode()) > 1024 * 1024:
        raise ValueError('restricted response exceeds transport bound')
    value = json.loads(response.stdout)
    if not isinstance(value, dict) or value.get('result') == 'BLOCKED':
        raise ValueError('restricted helper refused request')
    return value


def execute(args, *, host, expected_commit, canary_sha256='', canary_tag=''):
    if not re.fullmatch('[0-9a-f]{40}', expected_commit):
        raise ValueError('restricted verification requires an exact expected commit')
    if args.allow_empty_rates:
        raise ValueError('restricted verification requires real bank rates')
    if args.dry_run:
        print(json.dumps(dict(result='DRY_RUN', target_commit=expected_commit, mutated=False,
                              action='check-plan-and-activate' if args.deploy else 'read-only-status')))
        return 0
    if args.deploy:
        if (not re.fullmatch('[0-9a-f]{64}', args.approved_plan)
                or not re.fullmatch('[0-9a-f]{64}', canary_sha256)
                or not re.fullmatch('[A-Za-z0-9._-]+', canary_tag)):
            raise ValueError('root plan and protected canary identity are required')
        approved = call('check ' + args.approved_plan, host=host)
        required = {'result': 'APPROVED_PLAN', 'plan': args.approved_plan, 'target_commit': expected_commit,
                    'canary_manifest_sha256': canary_sha256, 'canary_release_tag': canary_tag, 'mutated': False}
        if approved != required:
            raise ValueError('root-approved intent differs from protected hosted canary')
        result = call('activate ' + args.approved_plan, host=host, timeout=3900)
        if result.get('result') != 'WORKER_COMPLETED' or result.get('plan') != args.approved_plan:
            raise ValueError('activation completion is unavailable; never retry an ambiguous plan')
    snapshot = check_snapshot(call('status', host=host), expected_commit)
    if args.deploy and (snapshot.get('last_plan') != args.approved_plan
                        or snapshot.get('acceptance') != 'POST_SWITCH_D027_VERIFIED'):
        raise ValueError('post-switch accepted release receipt differs')
    return 0
