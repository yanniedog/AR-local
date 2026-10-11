from pathlib import Path

import pytest

from pi_shared_task import launch_spec, parser


def options(*extra):
    return parser().parse_args(['--project', 'crypto-mining', *extra, '--', '/bin/true'])


def test_submission_is_non_root_supervised_and_has_no_schedule():
    result = launch_spec(options('--resource', 'host'), 'pi', Path('/srv/project'),
                         'shared-pi-task-test.service')
    assert '--property=User=pi' in result
    assert '--property=CPUQuota=100%' in result
    assert '--property=RuntimeMaxSec=1800' in result
    assert '--service-type=notify' in result
    assert '--property=TimeoutStartSec=14460' in result
    assert '--property=NotifyAccess=main' in result
    assert '--on-calendar' not in result
    assert result[-2:] == ['--', '/bin/true']


@pytest.mark.parametrize('args', [('--cpu-slots', '2'), ('--max-runtime', '1801'),
                                  ('--project', 'invalid project'), ('--wait-timeout', '86401')])
def test_invalid_submission_never_reaches_systemd(args):
    with pytest.raises(ValueError):
        launch_spec(options(*args), 'pi', Path('/srv/project'), 'shared-pi-task-test.service')


def test_ar_submission_uses_priority_and_declares_ar_data():
    args = parser().parse_args(['--project', 'ar-local', '--cpu-slots', '3',
                               '--max-runtime', '21600', '--', '/bin/true'])
    result = launch_spec(args, 'pi', Path('/srv/ar-local/AR-local'),
                         'ar-local-queue-task-test.service')
    assert '--property=CPUQuota=300%' in result
    assert '--property=CPUWeight=500' in result
    position = result.index('--resource')
    assert result[position + 1] == 'ar-local'


def test_command_arguments_are_not_shell_interpreted():
    args = parser().parse_args(['--project', 'jcs2', '--', '/bin/echo', '$(touch /bad)'])
    result = launch_spec(args, 'pi', Path('/srv/project'), 'shared-pi-task-test.service')
    assert result[-2:] == ['/bin/echo', '$(touch /bad)']
    assert '--expand-environment=no' in result


def test_deployed_entry_point_preserves_arguments():
    entry = Path(__file__).resolve().parents[1] / 'deploy' / 'pi' / 'pi-shared-task'
    assert entry.read_text().splitlines() == [
        '#!/bin/sh',
        'exec /usr/bin/python3 /usr/local/lib/shared-pi-queue/pi_shared_task.py "$@"',
    ]

import signal
import subprocess

import pi_shared_task as task


UNIT = 'shared-pi-task-' + 'a' * 32 + '.service'


@pytest.mark.parametrize('signum,expected', [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_launcher_signal_cancels_exact_unit_and_restores_handlers(monkeypatch, signum, expected):
    handlers, cancelled = {}, []
    monkeypatch.setattr(signal, 'getsignal', lambda value: 'previous')
    monkeypatch.setattr(signal, 'signal', lambda value, handler: handlers.__setitem__(value, handler))
    class Monitor:
        def poll(self): return None
    def spawn(command, **kwargs):
        assert kwargs['start_new_session'] is True
        handlers[signum](signum, None)
        return Monitor()
    def stop(unit, monitor, cancellation):
        cancelled.append((unit, cancellation.signum))
        return cancellation.exit_code
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    monkeypatch.setattr(task, 'cancel_submission', stop)
    assert task.run_submission(['sudo', '-n', 'systemd-run'], UNIT) == expected
    assert cancelled == [(UNIT, signum)]
    assert handlers == {signal.SIGINT: 'previous', signal.SIGTERM: 'previous'}


def test_cancel_does_not_accept_missing_unit_while_creation_monitor_is_alive(monkeypatch):
    clock, attempts, polls = [100.0], [], [0]
    cancellation = task.LaunchCancellation()
    cancellation.signum = signal.SIGTERM
    class Monitor:
        def poll(self):
            polls[0] += 1
            return 1 if polls[0] >= 4 else None
    monkeypatch.setattr(task.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(task.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(task, 'control_unit', lambda unit, operation: attempts.append((unit, operation)))
    monkeypatch.setattr(task, 'unit_inactive', lambda unit: True)
    assert task.cancel_submission(UNIT, Monitor(), cancellation, timeout=2) == 143
    assert polls[0] == 4 and attempts == [(UNIT, 'stop')]


def test_cancellation_kills_exact_unit_after_bounded_stop_grace(monkeypatch):
    clock, attempts, killed = [100.0], [], [False]
    cancellation = task.LaunchCancellation()
    cancellation.signum = signal.SIGINT
    class Monitor:
        def poll(self): return 1 if killed[0] else None
    def control(unit, operation):
        assert unit == UNIT
        attempts.append(operation)
        if operation == 'kill': killed[0] = True
    monkeypatch.setattr(task.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(task.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(task, 'control_unit', control)
    monkeypatch.setattr(task, 'unit_inactive', lambda unit: killed[0])
    assert task.cancel_submission(UNIT, Monitor(), cancellation, timeout=1) == 130
    assert attempts == ['stop', 'kill']


def test_shutdown_observation_failure_returns_error_not_false_cancellation_success(monkeypatch, capsys):
    clock = [100.0]
    cancellation = task.LaunchCancellation()
    cancellation.signum = signal.SIGTERM
    class Monitor:
        def poll(self): return 1
    def unavailable(unit): raise PermissionError()
    monkeypatch.setattr(task.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(task.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(task, 'control_unit', lambda *args: None)
    monkeypatch.setattr(task, 'unit_inactive', unavailable)
    assert task.cancel_submission(UNIT, Monitor(), cancellation, timeout=1) == 75
    assert clock[0] <= 116
    assert 'could not confirm whole-unit shutdown' in capsys.readouterr().err


@pytest.mark.parametrize('wait_fails', [False, True])
def test_unconfirmed_cancellation_reaps_submission_monitor_without_releasing_job(monkeypatch, capsys, wait_fails):
    clock, events = [100.0], []
    cancellation = task.LaunchCancellation()
    cancellation.signum = signal.SIGTERM
    class Monitor:
        def poll(self): return None
        def kill(self): events.append('monitor-kill')
        def wait(self, timeout):
            events.append(('monitor-wait', timeout))
            if wait_fails:
                raise subprocess.TimeoutExpired('systemd-run', timeout)
            return -9
    def unavailable(unit):
        raise PermissionError()
    monkeypatch.setattr(task.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(task.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(task, 'control_unit', lambda unit, operation: events.append((unit, operation)))
    monkeypatch.setattr(task, 'unit_inactive', unavailable)
    assert task.cancel_submission(UNIT, Monitor(), cancellation, timeout=1) == 75
    assert events == [(UNIT, 'stop'), (UNIT, 'kill'), 'monitor-kill', ('monitor-wait', 5)]
    assert 'could not confirm whole-unit shutdown' in capsys.readouterr().err


def test_unconfirmed_shutdown_does_not_kill_an_already_finished_monitor(monkeypatch):
    clock = [100.0]
    cancellation = task.LaunchCancellation()
    cancellation.signum = signal.SIGTERM
    class Monitor:
        def poll(self): return 1
        def kill(self): pytest.fail('finished monitor must not be killed')
        def wait(self, timeout): pytest.fail('poll already reaped finished monitor')
    monkeypatch.setattr(task.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(task.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(task, 'control_unit', lambda *args: None)
    monkeypatch.setattr(task, 'unit_inactive', lambda unit: False)
    assert task.cancel_submission(UNIT, Monitor(), cancellation, timeout=1) == 75


def test_whole_unit_shutdown_requires_empty_cgroup_and_zero_mainpid(monkeypatch):
    import pi_shared_queue_store as store
    details = {'Id': UNIT, 'ActiveState': 'inactive', 'MainPID': '0', 'ControlGroup': ''}
    members = []
    class Supervisor:
        def show(self, unit): return details
        def members(self, group):
            assert group == '/system.slice/' + UNIT
            return members
    monkeypatch.setattr(store, 'Supervisor', Supervisor)
    assert task.unit_inactive(UNIT)
    members.append(999)
    assert not task.unit_inactive(UNIT)
    members.clear()
    details['MainPID'] = '999'
    assert not task.unit_inactive(UNIT)


def test_stop_control_is_exact_argument_list_without_shell_interpretation(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: seen.append(command))
    task.control_unit(UNIT, 'stop')
    task.control_unit(UNIT, 'kill')
    assert seen == [
        ['sudo', '-n', '/usr/bin/systemctl', 'stop', '--no-block', UNIT],
        ['sudo', '-n', '/usr/bin/systemctl', 'kill', '--kill-whom=all', '--signal=SIGKILL', UNIT],
    ]
