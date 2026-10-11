"""Submit one supervised shared-host job on demand; never creates a timer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import signal
import time
import re
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
        'RuntimeMaxSec': str(args.max_runtime),
        'TimeoutStartSec': str(args.wait_timeout + 60), 'NotifyAccess': 'main',
        'TimeoutStopSec': '45s', 'TasksMax': '128',
        'SendSIGKILL': 'yes',
    }
    result = ['sudo', '-n', 'systemd-run', '--wait', '--pipe', '--collect',
              '--service-type=notify', '--expand-environment=no', '--unit=' + unit]
    result += ['--property=' + key + '=' + value for key, value in properties.items()]
    result += ['--setenv=PYTHONUNBUFFERED=1', '--setenv=HOME=' + str(Path.home()),
               '--', '/usr/bin/python3', str(RUNTIME), 'run', '--project', args.project,
               '--mode', args.mode, '--cpu-slots', str(args.cpu_slots),
               '--max-runtime', str(args.max_runtime), '--wait-timeout', str(args.wait_timeout)]
    for resource in resources:
        result += ['--resource', resource]
    return result + ['--'] + command


class LaunchCancellation:
    def __init__(self):
        self.signum = None

    def handle(self, signum, frame):
        if self.signum is None:
            self.signum = signum

    @property
    def exit_code(self):
        return 130 if self.signum == signal.SIGINT else 143


def unit_inactive(unit):
    from pi_shared_queue_store import Supervisor
    if not re.fullmatch(r'(?:ar-local-queue-task-|shared-pi-task-)[0-9a-f]{32}\.service', unit):
        raise ValueError('invalid submitted unit identity')
    supervisor = Supervisor()
    details = supervisor.show(unit)
    expected = '/system.slice/' + unit
    if (details.get('ActiveState') not in ('inactive', 'failed')
            or details.get('MainPID') != '0'
            or details.get('ControlGroup') not in ('', expected)):
        return False
    return supervisor.members(expected) == []


def control_unit(unit, operation):
    command = ['sudo', '-n', '/usr/bin/systemctl']
    if operation == 'stop':
        command += ['stop', '--no-block', unit]
    elif operation == 'kill':
        command += ['kill', '--kill-whom=all', '--signal=SIGKILL', unit]
    else:
        raise ValueError('unsupported submitted unit control')
    subprocess.run(command, text=True, capture_output=True, timeout=10, check=True)


def cancel_submission(unit, monitor, cancellation, timeout=90):
    """Stop the exact transient unit; the monitor alone does not own its job."""
    deadline, next_stop = time.monotonic() + timeout, 0.0
    while time.monotonic() < deadline:
        if time.monotonic() >= next_stop:
            try:
                control_unit(unit, 'stop')
            except (OSError, subprocess.SubprocessError):
                pass  # Creation may still be in flight; retry the same unit only.
            next_stop = time.monotonic() + 2
        try:
            if unit_inactive(unit) and monitor.poll() is not None:
                return cancellation.exit_code
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(.25)
    try:
        control_unit(unit, 'kill')
    except (OSError, subprocess.SubprocessError):
        pass
    # Give PID 1 and the wait monitor bounded time to report cgroup termination.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if unit_inactive(unit) and monitor.poll() is not None:
                return cancellation.exit_code
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(.25)
    print('Shared task cancellation could not confirm whole-unit shutdown', file=sys.stderr)
    return 75


def run_submission(command, unit):
    cancellation = LaunchCancellation()
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    for signum in previous:
        signal.signal(signum, cancellation.handle)
    try:
        if cancellation.signum is not None:
            return cancellation.exit_code
        # Isolate the monitor's terminal signals. Ctrl-C is handled here and
        # stops its service, including all command descendants, through PID 1.
        monitor = subprocess.Popen(command, start_new_session=True)
        while True:
            if cancellation.signum is not None:
                return cancel_submission(unit, monitor, cancellation)
            result = monitor.poll()
            if result is not None:
                return result if result >= 0 else 128 - result
            time.sleep(.1)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


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
    return run_submission(command, unit)


if __name__ == '__main__':
    raise SystemExit(main())
