from datetime import datetime, timezone
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


def test_main_records_state_but_always_returns_success(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "capacity.json"
    monkeypatch.setattr(
        monitor.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=2_000, used=1_000, free=1_000),
    )
    assert monitor.main(["--data-root", str(tmp_path), "--state", str(state)]) == 0
    assert state.is_file()


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
