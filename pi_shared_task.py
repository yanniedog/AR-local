"""Submit one supervised shared-host job on demand; never creates a timer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

RUNTIME = Path('/usr/local/lib/shared-pi-queue/pi_shared_queue.py')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--project', required=True)
    result.add_argument('--resource', action='append', default=[])
    result.add_argument('--mode', choices=('shared', 'exclusive'), default='exclusive')
    result.add_argument('--cpu-slots', type=int, default=1)
    result.add_argument('--max-runtime', type=int, default=1800)
    result.add_argument('--wait-timeout', type=int, default=14400)
    result.add_argument('--dry-run', action='store_true')
    result.add_argument('command', nargs=argparse.REMAINDER)
    return result


def launch_spec(args, user: str, cwd: Path, unit: str) -> list[str]:
    from pi_shared_queue_policy import admission
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    resources = args.resource or [args.project]
    job = {'id': unit, 'unit': unit, 'project': args.project, 'resources': resources,
           'mode': args.mode, 'cpu_slots': args.cpu_slots, 'sequence': 0,
           'ready_since': now.isoformat(), 'state': 'waiting',
           'max_duration_seconds': args.max_runtime}
    allowed, reason = admission(job, [job], now)
    # A valid job may be held by the time window, but malformed input may not
    # reach systemd even through diagnostic execution.
    if reason.startswith('invalid'):
        raise ValueError(reason)
    if args.project != 'ar-local' and args.cpu_slots != 1:
        raise ValueError('Other projects have a one-core maximum')
    if not 1 <= args.wait_timeout <= 86400:
        raise ValueError('Wait timeout must be between 1 and 86400 seconds')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or sum(len(part) for part in command) > 32768:
        raise ValueError('A bounded command is required after --')
    properties = {
        'User': user, 'WorkingDirectory': str(cwd), 'KillMode': 'control-group',
        'CPUQuota': f'{args.cpu_slots * 100}%',
        'CPUWeight': '500' if args.project == 'ar-local' else '25',
        'IOWeight': '500' if args.project == 'ar-local' else '20',
        'Nice': '0' if args.project == 'ar-local' else '10',
        'MemoryHigh': '1536M' if args.project == 'ar-local' else '768M',
        'MemoryMax': '2048M' if args.project == 'ar-local' else '1024M',
        'RuntimeMaxSec': str(args.wait_timeout + args.max_runtime + 120),
        'TimeoutStopSec': '45s', 'TasksMax': '128',
        'SendSIGKILL': 'yes',
    }
    result = ['sudo', '-n', 'systemd-run', '--wait', '--pipe', '--collect',
              '--service-type=exec', '--unit=' + unit]
    result += ['--property=' + key + '=' + value for key, value in properties.items()]
    result += ['--setenv=PYTHONUNBUFFERED=1', '--setenv=HOME=' + str(Path.home()),
               '--', '/usr/bin/python3', str(RUNTIME), 'run', '--project', args.project,
               '--mode', args.mode, '--cpu-slots', str(args.cpu_slots),
               '--max-runtime', str(args.max_runtime), '--wait-timeout', str(args.wait_timeout)]
    for resource in resources:
        result += ['--resource', resource]
    return result + ['--'] + command


def main(argv=None):
    args = parser().parse_args(argv)
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise SystemExit('Submit as a normal Linux user; commands never run as root')
    import pwd
    user = pwd.getpwuid(os.geteuid()).pw_name
    prefix = 'ar-local-queue-task-' if args.project == 'ar-local' else 'shared-pi-task-'
    unit = prefix + uuid.uuid4().hex + '.service'
    try:
        command = launch_spec(args, user, Path.cwd().resolve(), unit)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    if args.dry_run:
        print(json.dumps({'unit': unit, 'project': args.project,
                          'resources': args.resource or [args.project],
                          'cpu_slots': args.cpu_slots, 'max_runtime': args.max_runtime,
                          'wait_timeout': args.wait_timeout,
                          'command_sha256': hashlib.sha256(json.dumps(args.command).encode()).hexdigest(),
                          'scheduled_timer': False}))
        return 0
    if not RUNTIME.is_file():
        raise SystemExit('Shared queue runtime is not installed')
    return subprocess.call(command)


if __name__ == '__main__':
    raise SystemExit(main())
