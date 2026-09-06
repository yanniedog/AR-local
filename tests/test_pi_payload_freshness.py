import io
import json
import subprocess

import pytest

import pi_daily_watchdog as watchdog
import pi_payload_freshness as freshness
from scripts import pi_ingest_manifest_check as command


DATE = "2026-09-06"


def documents(manifest_date=DATE, index_date=DATE):
    manifest = {"schema_version": 1, "run_date": manifest_date, "files": {
        kind: {"name": f"{kind}.json.gz", "bytes": 100, "sha256": "a" * 64,
               "url": f"https://example.org/{kind}.json.gz"}
        for kind in ("core", "details")
    }}
    index = {"schema_version": 1, "dates": [index_date], "latest_date": index_date, "count": 1}
    return lambda url: index if "dates-index" in url else manifest


def test_current_manifest_and_index_are_both_required():
    assert freshness.check_publication(DATE, fetch=documents())["publication_current"] is True
    result = freshness.check_publication(DATE, fetch=documents(index_date="2026-09-05"))
    assert result["publication_current"] is False
    assert set(result["publication_issues"]) == {
        "dates_index_stale", "expected_date_not_indexed", "rolling_index_mismatch",
    }


@pytest.mark.parametrize("bad", [None, [], {}, {"dates": [DATE]}, {
    "schema_version": 1, "dates": [DATE, DATE], "latest_date": DATE,
}, {"schema_version": 1, "dates": [DATE], "latest_date": DATE, "count": 2}, {
    "schema_version": 1, "dates": [DATE], "latest_date": DATE}])
def test_invalid_index_is_not_publication_success(bad):
    result = freshness.check_publication(
        DATE, fetch=lambda url: bad if "dates-index" in url else documents()(url),
    )
    assert not result["publication_current"]
    assert "dates_index_unavailable_or_invalid" in result["publication_issues"]


def test_future_dates_do_not_hide_a_missing_day():
    result = freshness.check_publication(DATE, fetch=documents("2026-09-07", "2026-09-07"))
    assert not result["publication_current"]
    assert "manifest_future" in result["publication_issues"]


def test_diagnostic_manifest_is_not_a_published_app_day():
    def fetch(url):
        payload = documents()(url)
        if "manifest.json" in url:
            payload["publication_state"] = "diagnostic"
        return payload

    assert not freshness.check_publication(DATE, fetch=fetch)["publication_current"]


def test_fetch_failure_is_reported_without_raw_exception_text():
    calls = []

    def fail(url):
        calls.append(url)
        raise OSError("untrusted upstream text")

    result = freshness.check_publication(DATE, fetch=fail)
    assert len(calls) == 2
    assert not result["publication_current"]
    assert "untrusted" not in json.dumps(result)


def test_public_documents_have_a_read_bound(monkeypatch):
    monkeypatch.setattr(freshness.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(
        b" " * (freshness.MAX_DOCUMENT_BYTES + 1),
    ))
    with pytest.raises(ValueError, match="too_large"):
        freshness.fetch_document(freshness.MANIFEST_URL)


def stage_watchdog(monkeypatch, *, active=False, enabled=True):
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1" if enabled else "0")
    monkeypatch.setattr(watchdog, "ensure_runtime_data_writable", lambda _: None)
    monkeypatch.setattr(watchdog, "run_complete", lambda _: True)
    monkeypatch.setattr(watchdog, "service_active", lambda: active)
    monkeypatch.setattr(watchdog, "payload_publication_pending", lambda _: False)
    monkeypatch.setattr(watchdog, "latest_daily_due_utc", lambda now: now - watchdog.timedelta(hours=2))
    monkeypatch.setattr(watchdog, "expected_run_date_for_due", lambda _: DATE)
    monkeypatch.setattr(watchdog, "run_daily_ingest", lambda *a: pytest.fail("must not reingest"))
    monkeypatch.setattr(watchdog, "run_payload_retry", lambda *a: pytest.fail("must not invent retry"))


def test_finalized_but_unpublished_day_fails_without_a_pending_marker(monkeypatch, capsys):
    stage_watchdog(monkeypatch)
    monkeypatch.setattr(watchdog, "check_publication", lambda day: freshness.check_publication(
        day, fetch=documents("2026-09-05", "2026-09-05"),
    ))
    assert watchdog.main(["--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["capture_finalized"] is True
    assert result["publication_state"] == "stale_or_withheld"
    assert result["payload_pending"] is False


@pytest.mark.parametrize("active,enabled", [(True, True), (False, False)])
def test_active_capture_or_disabled_publisher_does_not_probe(monkeypatch, active, enabled):
    stage_watchdog(monkeypatch, active=active, enabled=enabled)
    monkeypatch.setattr(watchdog, "check_publication", lambda _: pytest.fail("unexpected probe"))
    assert watchdog.main(["--json"]) == 0


def test_github_checker_rejects_missing_date_in_index(monkeypatch, capsys):
    monkeypatch.setattr(command, "fetch_manifest", documents(index_date="2026-09-05"))
    monkeypatch.setattr(command, "expected_run_date_for_due", lambda _: DATE)
    monkeypatch.setattr(command, "latest_daily_due_utc", lambda now: now - watchdog.timedelta(hours=2))
    assert command.main(["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["stale"] is True


def test_manual_revision_is_an_active_capture(monkeypatch):
    seen = []

    def running(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, "inactive\nactivating\n")

    monkeypatch.setattr(watchdog.subprocess, "run", running)
    assert watchdog.service_active() is True
    assert seen == [["systemctl", "is-active", watchdog.SERVICE_NAME, "ar-local-ingest-now.service"]]


def test_successful_alert_does_not_turn_a_stale_feed_green(monkeypatch):
    import pi_ingest_alert

    monkeypatch.setattr(command, "fetch_manifest", documents(index_date="2026-09-05"))
    monkeypatch.setattr(command, "expected_run_date_for_due", lambda _: DATE)
    monkeypatch.setattr(command, "latest_daily_due_utc", lambda now: now - watchdog.timedelta(hours=2))
    monkeypatch.setattr(pi_ingest_alert, "main", lambda argv: 0)
    assert command.main(["--alert", "--json"]) == 1


@pytest.mark.parametrize("enabled", ["1", "true", "yes", "on", " TRUE "])
def test_watchdog_uses_publisher_enablement_semantics(monkeypatch, enabled):
    stage_watchdog(monkeypatch)
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", enabled)
    monkeypatch.setattr(watchdog, "check_publication", lambda _: {
        "publication_current": False, "publication_issues": ["manifest_stale"],
    })
    assert watchdog.main(["--json"]) == 1


@pytest.mark.parametrize("bad_files", [None, {}, {"core": {}}, {
    "core": {"name": "core.json.gz", "bytes": 0, "sha256": "bad", "url": "https://example.org"},
    "details": {},
}])
def test_truncated_or_invalid_manifest_cannot_close_an_incident(bad_files):
    def fetch(url):
        value = documents()(url)
        if "manifest.json" in url:
            value["files"] = bad_files
        return value

    result = freshness.check_publication(DATE, fetch=fetch)
    assert not result["publication_current"]
    assert "manifest_unavailable_or_invalid" in result["publication_issues"]


def test_configured_target_cannot_be_masked_by_the_default_feed(monkeypatch):
    monkeypatch.setenv("AR_LOCAL_REPO", "owner/other-repo")
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD_TAG", "other-feed")
    seen = []

    def fetch(url):
        seen.append(url)
        return documents("2026-09-05", "2026-09-05")(url) if "other-feed" in url else documents()(url)

    assert not freshness.check_publication(DATE, fetch=fetch)["publication_current"]
    assert len(seen) == 2
    assert all("owner/other-repo/releases/download/other-feed/" in url for url in seen)
    assert command.parse_args([]).manifest_url == seen[0]
