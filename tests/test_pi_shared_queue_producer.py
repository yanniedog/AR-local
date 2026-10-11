from pathlib import Path
from unittest.mock import Mock

import pytest

import pi_shared_queue_producer as producer


def test_custom_repository_is_rejected_before_default_checkout_execution(tmp_path):
    verify = Mock()
    with pytest.raises(ValueError, match='commissioned repository'):
        producer.producer_command(['pi_daily_sync.py'], cwd=tmp_path, verify=verify)
    verify.assert_not_called()


def test_commissioned_repository_checks_environment_before_launch(monkeypatch):
    monkeypatch.setattr(Path, 'resolve', lambda path, strict=False: path)
    verify = Mock()
    assert producer.producer_command(['pi_daily_sync.py', '--banks-only'], cwd=producer.REPO,
                                     verify=verify) == ['/usr/bin/python3', str(producer.REPO / 'pi_daily_sync.py'), '--banks-only']
    verify.assert_called_once_with()
    verify.side_effect = ValueError('custom data root')
    with pytest.raises(ValueError):
        producer.producer_command(['pi_daily_sync.py'], cwd=producer.REPO, verify=verify)


def test_all_fixed_override_commands_use_guarded_producer():
    root = Path(__file__).resolve().parents[1]
    for name in ('daily', 'ingest-now', 'watchdog'):
        text = (root / f'deploy/pi/shared-queue-{name}.conf').read_text()
        assert '/usr/local/lib/shared-pi-queue/pi_shared_queue_producer.py pi_daily_' in text
        assert '/srv/ar-local/AR-local/pi_daily_' not in text
