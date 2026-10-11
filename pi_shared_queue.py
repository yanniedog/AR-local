"""Demand-driven shared Pi admission; no worker, daemon or scheduled task.

Run only as a non-root systemd service MainPID. The supervised command inherits
that service's cgroup. Existing project transaction locks remain mandatory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from pi_shared_queue_policy import admission
from pi_shared_queue_store import Store, Supervisor, FIXED_AR_UNITS
from pi_shared_queue_native import NativeHostBusy, NativeHostGuard


def pressure_ready(path=Path('/proc/meminfo')):
    try:
        fields = dict(line.split(':', 1) for line in path.read_text().splitlines())
        return int(fields['MemAvailable'].split()[0]) >= 1024 * 1024
    except (OSError, KeyError, ValueError, IndexError):
        return False


def policy_view(jobs, now, monotonic):
    result = []
    for record in jobs:
        age = monotonic - record['queued_monotonic']
        if age < 0:
            raise ValueError('monotonic clock or boot mismatch')
        job = dict(record)
        job['ready_since'] = now - timedelta(seconds=age)
        result.append(job)
    return result


def register(store, spec, ownership, monotonic):
    with store.transaction() as state:
        if not store.reconcile(state):
            raise ValueError('queue ownership observation temporarily unavailable')
        if len(state['jobs']) >= 128:
            raise ValueError('queue capacity reached')
        job = dict(spec, **ownership, id=uuid.uuid4().hex,
                   sequence=state['next_sequence'], queued_monotonic=monotonic, state='waiting')
        if job['unit'] in FIXED_AR_UNITS:
            job['command_started'] = False
        state['next_sequence'] += 1
        view = policy_view([*state['jobs'], job], datetime.now(timezone.utc), monotonic)
        if admission(view[-1], view, datetime.now(timezone.utc))[1] == 'invalid-state':
            raise ValueError('invalid or quarantined queue state')
        state['jobs'].append(job)
    return job


def admit(store, job_id, now, monotonic, pressure=pressure_ready):
    with store.transaction() as state:
        if not store.reconcile(state):
            return False, 'ownership-observation-deferred'
        view = policy_view(state['jobs'], now, monotonic)
        matches = [record for record in view if record['id'] == job_id]
        if not matches:
            raise ValueError('request ownership lost')
        allowed, reason = admission(matches[0], view, now)
        if allowed and not pressure():
            allowed, reason = False, 'memory-pressure'
        if allowed:
            for record in state['jobs']:
                if record['id'] == job_id:
                    record['state'] = 'running'
        return allowed, reason


def descendants_done(store, job):
    supervisor = store.supervisor
    return supervisor.ownership(job) == 'live' and supervisor.members(job['cgroup']) == [os.getpid()]


def release(store, job):
    # The live systemd invocation must still match and contain only this wrapper.
    if job['unit'] in FIXED_AR_UNITS or not descendants_done(store, job):
        return False
    with store.transaction() as state:
        state['jobs'] = [record for record in state['jobs'] if record['id'] != job['id']]
    return True


def log(job, reason):
    print(json.dumps({'job_id': job['id'], 'project': job['project'], 'reason': reason}), flush=True)


class Cancellation:
    def __init__(self):
        self.requested = False
        self.stop_reason = None
        self.child = None

    def handle(self, signum, frame):
        self.requested = True
        if self.stop_reason is None:
            self.stop_reason = 'operator'
        if self.child is not None and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def wait_admission(store, job, wait_seconds, cancelled, deadline=None):
    deadline = time.monotonic() + wait_seconds if deadline is None else deadline
    previous = None
    while not cancelled.requested:
        allowed, reason = admit(store, job['id'], datetime.now(timezone.utc), time.monotonic())
        if reason != previous:
            log(job, reason)
            previous = reason
        if allowed:
            return True
        if time.monotonic() >= deadline:
            log(job, 'wait-timeout')
            return False
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    return False


def enforce_cgroup_deadline(store, job, deadline, stop_started, cancelled=None):
    now = time.monotonic()
    requested = cancelled is not None and cancelled.requested
    if stop_started is None and now < deadline and not requested:
        return stop_started
    if stop_started is None and cancelled is not None:
        cancelled.stop_reason = 'operator' if requested else 'deadline'
    signum = 'SIGTERM' if stop_started is None else 'SIGKILL' if now - stop_started >= 30 else None
    if signum is None:
        return stop_started
    try:
        store.supervisor.terminate(job, signum)
        log(job, 'execution-cgroup-' + signum.lower())
    except (OSError, ValueError, subprocess.SubprocessError):
        log(job, 'execution-cgroup-termination-unavailable')
    # Failure keeps all claims and the manual native hold. The independently
    # verified hard systemd deadline remains the final termination boundary.
    return now if stop_started is None else stop_started


def mark_command_started(store, job):
    """Publish the fixed service spawn receipt before polling its command."""
    if job['unit'] not in FIXED_AR_UNITS:
        return
    with store.transaction() as state:
        matches = [record for record in state['jobs'] if record['id'] == job['id']]
        if len(matches) != 1 or matches[0]['state'] != 'running':
            raise ValueError('admitted command ownership lost before spawn receipt')
        record = matches[0]
        ownership = ('pid', 'start_ticks', 'boot_id', 'unit', 'invocation_id', 'cgroup')
        if any(record[key] != job[key] for key in ownership):
            raise ValueError('command invocation changed before spawn receipt')
        record['command_started'] = True


def execute(store, job, command, cancelled, deadline=None, release_claim=True):
    if job['unit'] in FIXED_AR_UNITS:
        release_claim = False  # systemd post hooks run after this wrapper returns.
    deadline = time.monotonic() + job['max_duration_seconds'] if deadline is None else deadline
    if time.monotonic() >= deadline:
        log(job, 'execution-budget-exhausted')
        return 75
    if cancelled.requested:
        return 143
    # Record admission before spawning; a crash here leaves a conservative held
    # record until the exact service is proven inactive with an empty cgroup.
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
    try:
        if cancelled.requested:
            return 143
        # This wrapper is single-threaded. Restore its original signal mask in
        # the forked child; restore_signals alone does not unblock TERM/INT.
        child = subprocess.Popen(command, start_new_session=True,
                                 preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, blocked))
        cancelled.child = child
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    mark_command_started(store, job)
    termination_at, cgroup_stop = None, None
    while child.poll() is None:
        cgroup_stop = enforce_cgroup_deadline(store, job, deadline, cgroup_stop, cancelled)
        if cancelled.requested or time.monotonic() >= deadline:
            if termination_at is None:
                termination_at = time.monotonic()
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            elif time.monotonic() - termination_at >= 30:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        time.sleep(.2)
    cancelled.child = None
    # A child that daemonizes or escapes its process group still inherits the
    # service cgroup. Keep its slot until all descendants end or systemd kills
    # the whole service at the independently verified hard deadline.
    finished = release if release_claim else descendants_done
    while not finished(store, job):
        cgroup_stop = enforce_cgroup_deadline(store, job, deadline, cgroup_stop, cancelled)
        log_once = getattr(cancelled, 'descendants_logged', False)
        if not log_once:
            log(job, 'awaiting-supervised-descendants')
            cancelled.descendants_logged = True
        time.sleep(1)
    if cgroup_stop is not None and cancelled.stop_reason == 'deadline':
        log(job, 'runtime-timeout')
        return 124
    if cancelled.requested:
        return 143
    return child.returncode if child.returncode >= 0 else 128 - child.returncode


def demote(store, job):
    """No child has started: relinquish queue admission without resetting age."""
    with store.transaction() as state:
        for record in state['jobs']:
            if record['id'] == job['id']:
                record['state'] = 'waiting'
                return
        raise ValueError('host task request ownership lost')


def run_supervised(store, job, command, wait_seconds, cancelled, guard_factory=NativeHostGuard):
    deadline = time.monotonic() + wait_seconds
    native_host = 'host' in job['resources']
    while not cancelled.requested:
        if not wait_admission(store, job, wait_seconds, cancelled, deadline=deadline):
            return 143 if cancelled.requested else 75
        execution_deadline = time.monotonic() + job['max_duration_seconds']
        if not native_host:
            return execute(store, job, command, cancelled, deadline=execution_deadline)
        try:
            with guard_factory(store).hold(job, deadline=execution_deadline):
                return execute(store, job, command, cancelled, deadline=execution_deadline, release_claim=False)
        except NativeHostBusy:
            demote(store, job)
            log(job, 'native-ar-local-operation-deferred')
            if time.monotonic() >= deadline:
                return 75
            time.sleep(min(1, max(0, deadline - time.monotonic())))
    return 143


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--state-dir', type=Path, default=Path('/var/lib/shared-pi-queue'))
    commands = result.add_subparsers(dest='action', required=True)
    commands.add_parser('status')
    run = commands.add_parser('run')
    run.add_argument('--project', required=True)
    run.add_argument('--resource', action='append', required=True)
    run.add_argument('--mode', choices=('shared', 'exclusive'), default='exclusive')
    run.add_argument('--cpu-slots', type=int, default=1)
    run.add_argument('--max-runtime', type=int, required=True)
    run.add_argument('--wait-timeout', type=int, default=7200)
    run.add_argument('command', nargs=argparse.REMAINDER)
    return result


def status(path):
    # Read-only: status never creates directories, acquires ownership or rewrites state.
    file = path / 'state.json'
    if file.is_symlink() or path.is_symlink():
        raise ValueError('unsafe queue state path')
    if not file.exists():
        print(json.dumps({'version': 1, 'jobs': []}))
        return 0
    if file.stat().st_size > 1024 * 1024:
        raise ValueError('oversized queue state')
    state = json.loads(file.read_text())
    Store.validate(state)
    print(json.dumps({'version': 1, 'jobs': [
        {key: job[key] for key in ('id', 'project', 'state', 'sequence', 'resources', 'unit')}
        for job in state['jobs']]}))
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == 'status':
            return status(args.state_dir)
        if sys.platform != 'linux' or os.getuid() == 0:
            raise ValueError('run requires a non-root Linux service')
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command or not 0 <= args.wait_timeout <= 86400:
            raise ValueError('command and bounded wait timeout required')
        maximum = 21600 if args.project == 'ar-local' else 1800
        if not 1 <= args.max_runtime <= maximum or not 1 <= args.cpu_slots <= 3:
            raise ValueError('invalid runtime or CPU slot budget')
        if args.project != 'ar-local' and args.cpu_slots != 1:
            raise ValueError('other projects require one CPU slot')
        supervisor = Supervisor()
        ownership = supervisor.current(args.cpu_slots, args.wait_timeout + args.max_runtime + 60)
        if args.project == 'ar-local' and not ownership['unit'].startswith('ar-local-'):
            raise ValueError('AR-local requests require an AR-local service')
        if args.project != 'ar-local' and not ownership['unit'].startswith('shared-pi-task-'):
            raise ValueError('other projects require a shared-pi-task service')
        store = Store(args.state_dir, supervisor)
        spec = {'project': args.project, 'resources': args.resource, 'mode': args.mode,
                'cpu_slots': args.cpu_slots, 'max_duration_seconds': args.max_runtime}
        job = register(store, spec, ownership, time.monotonic())
        cancelled = Cancellation()
        signal.signal(signal.SIGTERM, cancelled.handle)
        signal.signal(signal.SIGINT, cancelled.handle)
        try:
            return run_supervised(store, job, command, args.wait_timeout, cancelled)
        finally:
            # This never frees a slot occupied by surviving supervised descendants.
            if job['unit'] not in FIXED_AR_UNITS:
                release(store, job)
    except (OSError, ValueError, ImportError, subprocess.SubprocessError) as exc:
        # Commands and their environment can contain secrets; don't print either.
        print('shared Pi queue failed closed: ' + type(exc).__name__, file=sys.stderr)
        return 75


if __name__ == '__main__':
    raise SystemExit(main())
