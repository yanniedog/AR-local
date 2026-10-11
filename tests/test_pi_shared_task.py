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
    assert '--property=RuntimeMaxSec=16320' in result
    assert '--service-type=exec' in result
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
