import json
import smtplib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pi_capacity_monitor as monitor


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, tzinfo=timezone.utc)


def test_capacity_report_uses_daily_growth_and_never_authorizes_deletion() -> None:
    report = monitor.capacity_report(
        total_bytes=2_000 * monitor.GIB,
        used_bytes=1_700 * monitor.GIB,
        free_bytes=300 * monitor.GIB,
        prior_samples=[
            {"day": "2026-08-13", "free_bytes": 330 * monitor.GIB},
            {"day": "2026-08-14", "free_bytes": 320 * monitor.GIB},
            {"day": "2026-08-15", "free_bytes": 310 * monitor.GIB},
        ],
        now=_at(16),
    )
    assert report["growth_bytes_per_day_p90"] == 10 * monitor.GIB
    assert report["runway_days"] == 30
    assert report["status"] == "critical"
    assert report["policy"]["retained_evidence_deleted"] is False
    assert report["policy"]["blocks_daily_ingest"] is False


def test_repeated_same_day_sample_does_not_invent_growth() -> None:
    report = monitor.capacity_report(
        total_bytes=2_000 * monitor.GIB,
        used_bytes=200 * monitor.GIB,
        free_bytes=1_800 * monitor.GIB,
        prior_samples=[{"day": "2026-08-16", "free_bytes": 1_700 * monitor.GIB}],
        now=_at(16),
    )
    assert report["growth_bytes_per_day_p90"] is None
    assert report["runway_days"] is None
    assert report["status"] == "healthy"


def test_main_records_capacity_without_notification(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "capacity.json"
    monkeypatch.setattr(
        monitor.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=2_000, used=1_000, free=1_000),
    )
    monkeypatch.setattr(monitor, "_now", lambda: _at(16))
    assert monitor.main(["--data-root", str(tmp_path), "--state", str(state)]) == 0
    saved = json.loads(state.read_text())
    assert saved["checked_at"] == _at(16).isoformat()
    assert saved["status"] == "critical"
    assert saved["filesystem"] == {"total_bytes": 2000, "used_bytes": 1000, "free_bytes": 1000}
    assert saved["samples"] == [{"day": "2026-08-16", "free_bytes": 1000}]


def test_capacity_service_is_independent_from_daily_ingest() -> None:
    root = Path(__file__).resolve().parents[1]
    daily = (root / "deploy/pi/ar-local-daily.service").read_text(encoding="utf-8")
    watchdog = (root / "deploy/pi/ar-local-daily-watchdog.service").read_text(encoding="utf-8")
    capacity = (root / "deploy/pi/ar-local-capacity-monitor.service").read_text(encoding="utf-8")
    assert "capacity" not in daily.lower()
    assert "capacity" not in watchdog.lower()
    assert "pi_capacity_monitor.py" in capacity
    install = (root / "deploy/pi/install-pi-systemd.sh").read_text(encoding="utf-8")
    apply_units = (root / "deploy/pi/apply-pi-runtime-units.sh").read_text(encoding="utf-8")
    assert "ar-local-capacity-monitor.timer" in install
    assert "ar-local-capacity-monitor.timer" in apply_units


def test_notification_cooldown_survives_skipped_monitor_samples(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(monitor, "email_configured", lambda: True)
    monkeypatch.setattr(
        monitor,
        "send_email",
        lambda subject, _body: sent.append(subject) is None or True,
    )
    base = datetime(2026, 8, 16, tzinfo=timezone.utc)

    first = monitor.capacity_report(
        total_bytes=1_000 * monitor.GIB,
        used_bytes=800 * monitor.GIB,
        free_bytes=200 * monitor.GIB,
        prior_samples=[],
        now=base,
    )
    monitor._maybe_notify(first, {}, base)
    assert len(sent) == 1

    second = monitor.capacity_report(
        total_bytes=1_000 * monitor.GIB,
        used_bytes=800 * monitor.GIB,
        free_bytes=200 * monitor.GIB,
        prior_samples=first["samples"],
        now=base.replace(hour=6),
    )
    monitor._maybe_notify(second, first, base.replace(hour=6))
    assert len(sent) == 1
    assert second["last_alert_at"] == first["last_alert_at"]

    third = monitor.capacity_report(
        total_bytes=1_000 * monitor.GIB,
        used_bytes=800 * monitor.GIB,
        free_bytes=200 * monitor.GIB,
        prior_samples=second["samples"],
        now=base.replace(hour=12),
    )
    monitor._maybe_notify(third, second, base.replace(hour=12))
    assert len(sent) == 1
    assert third["last_alert_status"] == "warning"


def test_smtp_disconnect_preserves_assessment_and_retries_after_backoff(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    state_path = tmp_path / "capacity.json"
    base = datetime(2026, 11, 13, tzinfo=timezone.utc)
    clock = [base]
    monkeypatch.setattr(monitor, "_now", lambda: clock[0])
    monkeypatch.setattr(monitor, "email_configured", lambda: True)
    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda _path: SimpleNamespace(
        total=1_000 * monitor.GIB, used=800 * monitor.GIB, free=200 * monitor.GIB,
    ))
    attempts = []

    def disconnect(_subject, _body):
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        # Both the current assessment and in-flight retry reservation predate SMTP.
        assert saved["checked_at"] == clock[0].isoformat()
        assert saved["status"] == "warning"
        assert saved["samples"][-1]["day"] == clock[0].date().isoformat()
        assert saved["notification"]["status"] == "ATTEMPTING"
        attempts.append(clock[0])
        raise smtplib.SMTPServerDisconnected("private-server-response")

    monkeypatch.setattr(monitor, "send_email", disconnect)
    args = ["--data-root", str(tmp_path), "--state", str(state_path), "--notify"]
    assert monitor.main(args) == 1
    failed = json.loads(state_path.read_text(encoding="utf-8"))
    assert failed["notification"]["status"] == "FAILED"
    assert failed["notification"]["error_class"] == "SMTPServerDisconnected"
    assert "last_alert_at" not in failed
    assert "private-server-response" not in state_path.read_text(encoding="utf-8")
    assert "private-server-response" not in capsys.readouterr().out

    clock[0] += timedelta(minutes=30)
    assert monitor.main(args) == 1
    assert len(attempts) == 1
    waiting = json.loads(state_path.read_text(encoding="utf-8"))
    assert waiting["checked_at"] == clock[0].isoformat()
    assert waiting["notification"] == failed["notification"]

    clock[0] = base + timedelta(seconds=monitor.ALERT_RETRY_SECONDS)
    monkeypatch.setattr(monitor, "send_email", lambda *_: attempts.append(clock[0]) is None)
    assert monitor.main(args) == 0
    sent = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(attempts) == 2
    assert sent["notification"]["status"] == "SENT"
    assert sent["last_alert_at"] == clock[0].timestamp()
    assert "error_class" not in sent["notification"]

    clock[0] += timedelta(hours=1)
    assert monitor.main(args[:-1]) == 0  # Sampling without --notify retains cooldown.
    clock[0] += timedelta(hours=1)
    assert monitor.main(args) == 0
    assert len(attempts) == 2


def test_capacity_escalation_bypasses_failed_warning_backoff(monkeypatch) -> None:
    base = datetime(2026, 11, 13, tzinfo=timezone.utc)
    state = {"notification": {
        "status": "FAILED", "capacity_status": "warning",
        "attempted_at": base.timestamp(),
        "retry_after": base.timestamp() + monitor.ALERT_RETRY_SECONDS,
    }}
    report = monitor.capacity_report(
        total_bytes=1_000 * monitor.GIB, used_bytes=950 * monitor.GIB,
        free_bytes=50 * monitor.GIB, prior_samples=[], now=base,
    )
    sent = []
    monkeypatch.setattr(monitor, "email_configured", lambda: True)
    monkeypatch.setattr(monitor, "send_email", lambda *_: sent.append(True) is None)
    assert monitor._maybe_notify(report, state, base)
    assert sent == [True]
    assert report["status"] == "critical"
    assert report["notification"]["capacity_status"] == "critical"


def test_sender_false_is_not_recorded_as_success(monkeypatch) -> None:
    base = datetime(2026, 11, 13, tzinfo=timezone.utc)
    report = monitor.capacity_report(
        total_bytes=1_000 * monitor.GIB, used_bytes=800 * monitor.GIB,
        free_bytes=200 * monitor.GIB, prior_samples=[], now=base,
    )
    monkeypatch.setattr(monitor, "email_configured", lambda: True)
    monkeypatch.setattr(monitor, "send_email", lambda *_: False)
    assert not monitor._maybe_notify(report, {}, base)
    assert report["notification"]["status"] == "NOT_SENT"
    assert "last_alert_at" not in report
