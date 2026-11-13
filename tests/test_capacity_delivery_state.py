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


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), {"nested": float("nan")}])
@pytest.mark.parametrize("field", ["attempted_at", "retry_after", "error_class"])
def test_nonfinite_retained_notification_cannot_block_sampling(tmp_path, monkeypatch, bad, field):
    clock, state, args = configured(tmp_path, monkeypatch)
    prior = {"status": "FAILED", "capacity_status": "warning",
             "attempted_at": clock[0].timestamp(),
             "retry_after": clock[0].timestamp() + 3600, "error_class": "OSError"}
    prior[field] = bad
    state.write_text(json.dumps({"notification": prior}))
    assert monitor.main(args[:-1]) == 0
    saved = json.loads(state.read_text())
    assert saved["samples"] and saved["checked_at"] == clock[0].isoformat()
    assert field not in saved["notification"]
    assert saved["notification"] == {k: v for k, v in prior.items() if k != field}
    json.dumps(saved, allow_nan=False)


def test_invalid_prior_field_preserves_valid_retry_reservation(tmp_path, monkeypatch):
    clock, state, args = configured(tmp_path, monkeypatch)
    until = clock[0].timestamp() + 3600
    state.write_text(json.dumps({"notification": {"status": "FAILED", "capacity_status": "warning",
        "attempted_at": float("nan"), "retry_after": until}}))
    monkeypatch.setattr(monitor, "send_email", lambda *_: pytest.fail("retry reservation lost"))
    assert monitor.main(args) == 1
    assert json.loads(state.read_text())["notification"]["retry_after"] == until


def test_invalid_utf8_notification_config_retains_sanitized_failure_and_retry(tmp_path, monkeypatch, capsys):
    import ar_local_email_notify
    clock, state, args = configured(tmp_path, monkeypatch)
    config = tmp_path / "private-notify.env"
    config.write_bytes(b"private-config-detail=\xff\n")
    monkeypatch.setenv("AR_LOCAL_NOTIFY_ENV", str(config))
    monkeypatch.setattr(monitor, "email_configured", ar_local_email_notify.email_configured)
    monkeypatch.setattr(monitor, "send_email", lambda *_: pytest.fail("invalid config sent"))
    assert monitor.main(args) == 1
    saved = json.loads(state.read_text())
    assert saved["samples"] and saved["status"] == "warning"
    assert saved["notification"]["status"] == "FAILED"
    assert saved["notification"]["error_class"] == "UnicodeDecodeError"
    assert saved["notification"]["retry_after"] == clock[0].timestamp() + monitor.ALERT_RETRY_SECONDS
    clock[0] += timedelta(minutes=1)
    monkeypatch.setattr(monitor, "email_configured", lambda: pytest.fail("config retry reservation lost"))
    assert monitor.main(args) == 1
    output = capsys.readouterr()
    assert "private-config-detail" not in state.read_text() + output.out + output.err
    assert str(config) not in output.out + output.err
