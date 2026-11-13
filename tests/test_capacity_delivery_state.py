"""Capacity monitor protocol regressions; no SMTP or Pi access."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from threading import Event
from types import SimpleNamespace

import pytest
import pi_capacity_monitor as monitor


def configured(tmp_path, monkeypatch):
    clock = [datetime(2026, 11, 14, tzinfo=timezone.utc)]
    monkeypatch.setattr(monitor, "_now", lambda: clock[0])
    monkeypatch.setattr(monitor, "email_configured", lambda: True)
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda _: SimpleNamespace(
        total=1000 * monitor.GIB, used=800 * monitor.GIB, free=200 * monitor.GIB))
    state = tmp_path / "capacity.json"
    args = ["--data-root", str(tmp_path), "--state", str(state), "--notify"]
    return clock, state, args


@pytest.mark.parametrize("error", [ValueError, OverflowError])
def test_invalid_delivery_configuration_retains_failed_outcome(tmp_path, monkeypatch, capsys, error):
    _, state, args = configured(tmp_path, monkeypatch)
    def sender(*_):
        raise error("private-config-detail")
    monkeypatch.setattr(monitor, "send_email", sender)
    assert monitor.main(args) == 1
    result = json.loads(state.read_text())
    assert result["status"] == "warning" and result["samples"]
    assert result["notification"]["status"] == "FAILED"
    assert result["notification"]["error_class"] == error.__name__
    assert "private-config-detail" not in state.read_text() + capsys.readouterr().out


def test_unconfigured_notification_is_truthful_and_keeps_retry_reservation(tmp_path, monkeypatch):
    clock, state, args = configured(tmp_path, monkeypatch)
    attempts = []
    monkeypatch.setattr(monitor, "send_email", lambda *_: attempts.append(True) and False)
    assert monitor.main(args) == 1
    prior = json.loads(state.read_text())["notification"]
    clock[0] += timedelta(minutes=10)
    monkeypatch.setattr(monitor, "email_configured", lambda: False)
    assert monitor.main(args) == 1
    assert json.loads(state.read_text())["notification"] == prior
    clock[0] += timedelta(minutes=10)
    monkeypatch.setattr(monitor, "email_configured", lambda: True)
    assert monitor.main(args) == 1 and attempts == [True]
    clock[0] += timedelta(hours=1)
    monkeypatch.setattr(monitor, "email_configured", lambda: False)
    assert monitor.main(args) == 1
    assert json.loads(state.read_text())["notification"] == {"status": "NOT_CONFIGURED"}
    assert monitor.main(args[:-1]) == 0  # Sampling remains independent from optional delivery.


def test_concurrent_monitor_waits_for_delivery_outcome_before_reading(tmp_path, monkeypatch):
    _, state, args = configured(tmp_path, monkeypatch)
    sending, release, second_started, second_read = (Event() for _ in range(4))
    read_state = monitor._read_state
    reads, sent = [], []
    def reader(path):
        reads.append(True)
        if len(reads) > 1:
            second_read.set()
        return read_state(path)
    def sender(*_):
        sent.append(True)
        sending.set()
        assert release.wait(5)
        return True
    def second():
        second_started.set()
        return monitor.main(args)
    monkeypatch.setattr(monitor, "_read_state", reader)
    monkeypatch.setattr(monitor, "send_email", sender)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(monitor.main, args)
        assert sending.wait(3)
        other = pool.submit(second)
        try:
            assert second_started.wait(3)
            assert not second_read.wait(0.2)
        finally:
            release.set()
        assert first.result(timeout=5) == other.result(timeout=5) == 0
    assert reads == [True, True] and sent == [True]
    saved = json.loads(state.read_text())
    assert saved["notification"]["status"] == "SENT" and saved["samples"]
    assert saved["last_alert_status"] == "warning"
    assert not list(tmp_path.glob("*.tmp*"))
