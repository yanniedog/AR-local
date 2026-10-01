"""Publication interruption must preserve capture and every pending observation."""
from unittest.mock import Mock

import pytest

import pi_daily_sync as sync
from pi_payload_retry_policy import publication_source_key


def pointer(day):
    return {"observation_date": day, "observation_state": "partial",
            "export_path": f"runs/{day}/_exports", "marker_path": f"{day}.done.json"}


@pytest.fixture
def daily(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "data_state_root", lambda _: tmp_path)
    monkeypatch.setattr(sync, "ensure_runtime_data_writable", lambda _: None)
    monkeypatch.setattr(sync, "payload_retry_window_reason", lambda: "")
    monkeypatch.setattr(sync, "pause_dashboard_for_ingest", lambda: False)
    monkeypatch.setattr(sync, "refresh_economic_data", lambda _: None)
    monkeypatch.setattr(sync, "queue_drive_backup", lambda _: None)
    monkeypatch.setattr(sync, "run_checked", Mock())
    monkeypatch.setattr(sync, "current_publication_pointer", lambda _: pointer("2026-10-01"))
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    return tmp_path


def test_pending_intent_is_durable_before_publisher_can_be_killed(daily, monkeypatch):
    def interrupted(repo, captured):
        assert sync.pending_publication_pointer(repo) == captured
        assert (daily / "daily-ingest.lock").is_file()
        raise KeyboardInterrupt
    monkeypatch.setattr(sync, "maybe_publish_app_payload", interrupted)
    with pytest.raises(KeyboardInterrupt):
        sync.main(["--banks-only"])
    assert sync.pending_publication_pointer(sync.REPO_ROOT) == pointer("2026-10-01")
    assert not (daily / "daily-ingest.lock").exists()


def test_new_daily_success_does_not_erase_older_pending_publication(daily, monkeypatch):
    older = pointer("2026-09-30")
    sync.mark_payload_publication_pending(sync.REPO_ROOT, "publish_failed", older)
    monkeypatch.setattr(sync, "maybe_publish_app_payload", lambda *args: "published")
    assert sync.main(["--banks-only"]) == 0
    assert sync.pending_publication_pointer(sync.REPO_ROOT) == older
    assert not sync.read_payload_publication_pending(sync.REPO_ROOT)["queued_pointers"]


def test_retry_of_older_day_keeps_newer_finalized_capture_pending(daily, monkeypatch):
    older = pointer("2026-09-30")
    sync.mark_payload_publication_pending(sync.REPO_ROOT, "publish_failed", older)
    monkeypatch.setattr(sync, "maybe_publish_app_payload", lambda *args: "published")
    assert sync.main(["--publish-existing-payload"]) == 0
    assert sync.pending_publication_pointer(sync.REPO_ROOT) == pointer("2026-10-01")


def test_failed_newer_capture_is_queued_once_and_survives_head_completion(daily):
    older, newer = pointer("2026-09-30"), pointer("2026-10-01")
    sync.mark_payload_publication_pending(sync.REPO_ROOT, "failed", older)
    for _ in range(2):
        sync.mark_payload_publication_pending(sync.REPO_ROOT, "started", newer)
    assert sync.read_payload_publication_pending(sync.REPO_ROOT)["queued_pointers"] == [newer]
    sync.clear_payload_publication_pending(sync.REPO_ROOT, older)
    assert sync.pending_publication_pointer(sync.REPO_ROOT) == newer


def test_admitted_newer_source_can_publish_while_older_source_remains_pending(daily, monkeypatch):
    older, newer = pointer("2026-09-30"), pointer("2026-10-01")
    sync.mark_payload_publication_pending(sync.REPO_ROOT, "failed", older)
    sync.mark_payload_publication_pending(sync.REPO_ROOT, "failed", newer)
    published = Mock(return_value="published")
    monkeypatch.setattr(sync, "maybe_publish_app_payload", published)
    assert sync.main(["--publish-existing-payload", "--publication-source-key",
                      publication_source_key({"pointer": newer})]) == 0
    published.assert_called_once_with(sync.REPO_ROOT, newer)
    assert sync.pending_publication_pointer(sync.REPO_ROOT) == older
    assert not sync.read_payload_publication_pending(sync.REPO_ROOT)["queued_pointers"]


def test_disappeared_admitted_source_does_not_publish_a_different_generation(daily, monkeypatch):
    sync.mark_payload_publication_pending(sync.REPO_ROOT, "failed", pointer("2026-10-01"))
    monkeypatch.setattr(sync, "maybe_publish_app_payload", lambda *_: pytest.fail("wrong generation"))
    assert sync.main(["--publish-existing-payload", "--publication-source-key", "0" * 64]) == 0
    assert sync.payload_publication_pending(sync.REPO_ROOT)


def test_quiet_window_retry_never_acquires_ingest_lock(daily, monkeypatch):
    monkeypatch.setattr(sync, "payload_retry_window_reason", lambda: "protected_natural_ingest_window")
    monkeypatch.setattr(sync, "DailyIngestLock", lambda *_: pytest.fail("blocked capture"))
    assert sync.main(["--publish-existing-payload"]) == 0


def test_admission_rechecked_after_lock_wait(daily, monkeypatch):
    reasons = iter(["", "protected_natural_ingest_window"])
    monkeypatch.setattr(sync, "payload_retry_window_reason", lambda: next(reasons))
    monkeypatch.setattr(sync, "maybe_publish_app_payload", lambda *_: pytest.fail("started late"))
    assert sync.main(["--publish-existing-payload"]) == 0
    assert not (daily / "daily-ingest.lock").exists()
