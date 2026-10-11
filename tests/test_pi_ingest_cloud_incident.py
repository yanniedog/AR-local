"""Control-plane regression cases; no business data or external delivery."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import pi_ingest_cloud_incident as cloud

NOW = datetime(2026, 10, 11, 6, tzinfo=timezone.utc)


def check(now=NOW, current=False):
    due = cloud.latest_daily_due_utc(now)
    day = cloud.expected_run_date_for_due(due)
    return {"now_utc": now.isoformat(), "due_utc": due.isoformat(),
            "ready_at_utc": (due + cloud.GRACE).isoformat(), "expected_run_date": day,
            "schedule_timezone": "Australia/Hobart", "schedule_local_hour": 1,
            "verification_scope": "public_ciphertext_receipt",
            "manifest_run_date": day if current else "", "dates_index_latest_date": day if current else "",
            "publication_current": current, "stale": now >= due + cloud.GRACE and not current,
            "manifest_error": None if current else "ValueError", "dates_index_error": None,
            "publication_issues": [] if current else ["operational_receipt_unavailable_or_inconsistent"]}


def report(now=NOW, current=False):
    value = check(now, current)
    return cloud.collect_check(clock=lambda: now, run=lambda *a, **k: SimpleNamespace(
        stdout=json.dumps(value).encode(), returncode=int(value["stale"])))


class API:
    def __init__(self, rows=()):
        self.rows = {row["number"]: dict(row) for row in rows}
        self.calls = []
        self.label = True
        self.ambiguous_create = False

    def request(self, method, path, value=None):
        self.calls.append((method, path, value))
        if method == "GET" and path.startswith("issues?"):
            page = int(path.rsplit("=", 1)[1])
            return list(self.rows.values())[(page - 1) * 100:page * 100]
        if method == "GET" and path == "labels/ingest-missed":
            if not self.label:
                raise cloud.DeliveryError("GITHUB_HTTP_404")
            return {"name": "ingest-missed"}
        if method == "POST" and path == "labels":
            self.label = True
            return value
        if method == "POST" and path == "issues":
            number = max(self.rows, default=0) + 1
            self.rows[number] = {**value, "number": number, "state": "open",
                                 "user": {"login": "github-actions[bot]"},
                                 "assignees": [{"login": name} for name in value["assignees"]]}
            if self.ambiguous_create:
                self.ambiguous_create = False
                raise cloud.DeliveryError("GITHUB_REQUEST_TIMEOUT")
            return self.rows[number]
        if method == "PATCH":
            row = self.rows[int(path.split("/")[1])]
            row.update(value)
            if "assignees" in value:
                row["assignees"] = [{"login": name} for name in value["assignees"]]
            return row
        raise AssertionError((method, path, value))


def legacy(number=1, state="open"):
    return {"number": number, "title": "Pi ingest missed: 2026-10-11",
            "user": {"login": "github-actions[bot]"}, "labels": [{"name": "ingest-missed"}],
            "body": "old watchdog publication incident", "state": state, "assignees": []}


def pi_incident(number=879, kind="ingest", day="2026-10-11"):
    title = {"ingest": "Pi ingest needs attention: ",
             "ingest-schedule": "Pi scheduled ingest missed: ",
             "ingest-watchdog": "Pi ingest watchdog failed: "}[kind] + day
    marker = hashlib.sha256((cloud.REPOSITORY + ":" + kind + ":" + day).encode()).hexdigest()
    return {"number": number, "title": title, "state": "open", "assignees": [],
            "user": {"login": cloud.OWNER},
            "body": "<!-- ar-local-pi-incident:" + marker + " -->\nPrivate-looking text must not be copied"}


@pytest.mark.parametrize("local,expected,status", [
    ("2026-10-11T00:17:00+11:00", "2026-10-10", "STALE"),
    ("2026-10-11T01:17:00+11:00", "2026-10-11", "GRACE"),
    ("2026-10-11T02:29:59+11:00", "2026-10-11", "GRACE"),
    ("2026-10-11T02:30:00+11:00", "2026-10-11", "STALE"),
    ("2026-10-04T03:17:00+11:00", "2026-10-04", "GRACE"),
    ("2026-10-04T03:47:00+11:00", "2026-10-04", "STALE"),
    ("2026-04-05T02:17:00+11:00", "2026-04-05", "GRACE"),
    ("2026-04-05T02:17:00+10:00", "2026-04-05", "STALE"),
])
def test_due_and_elapsed_grace_across_midnight_and_dst(local, expected, status):
    result = report(datetime.fromisoformat(local).astimezone(timezone.utc))
    assert result["expected_run_date"] == expected
    assert result["status"] == status


@pytest.mark.parametrize("raw,code", [(b"", 1), (b"{bad", 0), (b"{}", 0), (b"[]", 0),
                                     (b'{"stale":false,"stale":true}', 0),
                                     (b"x" * (cloud.MAX_CHECK_BYTES + 1), 0)],
                         ids=["missing", "malformed", "empty-object", "wrong-type", "duplicate-field", "oversized"])
def test_missing_or_malformed_check_never_becomes_current(raw, code):
    result = cloud.collect_check(clock=lambda: NOW, run=lambda *a, **k: SimpleNamespace(stdout=raw, returncode=code))
    assert result["status"] == "UNKNOWN" and result["publication"] is None


@pytest.mark.parametrize("field,value", [("stale", "false"), ("expected_run_date", "2026-10-10"),
    ("verification_scope", "unverified"), ("publication_issues", ["@everyone\nsecret"]),
    ("manifest_run_date", "2026-10-10"), ("schedule_timezone", "Australia/Brisbane"),
    ("due_utc", "2026-10-10T00:00:00+00:00"), ("manifest_error", "error")])
def test_inconsistent_current_result_fails_closed(field, value):
    payload = check(current=True); payload[field] = value
    result = cloud.collect_check(clock=lambda: NOW, run=lambda *a, **k: SimpleNamespace(
        stdout=json.dumps(payload).encode(), returncode=0))
    assert result["status"] == "UNKNOWN"


def test_child_failure_despite_current_json_is_unknown():
    result = cloud.collect_check(clock=lambda: NOW, run=lambda *a, **k: SimpleNamespace(
        stdout=json.dumps(check(current=True)).encode(), returncode=1))
    assert result["status"] == "UNKNOWN"


@pytest.mark.parametrize("error", [OSError("private text"), subprocess.TimeoutExpired("check", 180)])
def test_check_infrastructure_failure_is_explicit_and_sanitized(error):
    def failed(*args, **kwargs): raise error
    result = cloud.collect_check(clock=lambda: NOW, run=failed)
    assert result["reason"] == "CHECK_PROCESS_FAILED"
    assert "private text" not in json.dumps(result)
    result = cloud.collect_check(clock=lambda: NOW, run=failed, unavailable=True)
    assert result["reason"] == "CHECK_INFRASTRUCTURE_FAILED"


def test_checker_uses_shared_schedule_without_calendar_day_override():
    def run(args, **kwargs):
        assert args[-4:] == ["--public-receipt", "--grace-minutes", "90", "--json"]
        assert kwargs["timeout"] == 180
        return SimpleNamespace(stdout=json.dumps(check()).encode(), returncode=1)
    assert cloud.collect_check(run=run, clock=lambda: NOW)["status"] == "STALE"


def test_repeated_failure_creates_one_assigned_issue_without_comments_or_updates():
    api = API(); api.label = False
    assert cloud.reconcile(api, report())["status"] == "CREATED"
    assert cloud.reconcile(api, report())["status"] == "UNCHANGED"
    mutations = [(method, path) for method, path, _ in api.calls if method != "GET"]
    assert mutations == [("POST", "labels"), ("POST", "issues")]
    assert api.rows[1]["assignees"] == [{"login": "yanniedog"}]
    assert "does not prove a full ingest" in api.rows[1]["body"]


def test_closed_legacy_issue_reopens_instead_of_duplicate():
    api = API([legacy(state="closed")])
    cloud.reconcile(api, report())
    assert list(api.rows) == [1] and api.rows[1]["state"] == "open"
    assert not any(method == "POST" for method, _, _ in api.calls)


@pytest.mark.parametrize("fault", ["untrusted-author", "unlabelled-legacy", "forged-new-marker"])
def test_matching_public_title_cannot_adopt_unowned_issue(fault):
    row = legacy()
    if fault != "unlabelled-legacy": row["user"] = {"login": "unrelated-user"}
    if fault == "unlabelled-legacy": row["labels"] = []
    if fault == "forged-new-marker": row["body"] = cloud.issue_body(report())
    api = API([row])
    with pytest.raises(cloud.DeliveryError, match="IDENTITY_CHANGED"):
        cloud.reconcile(api, report())
    assert all(method == "GET" for method, _, _ in api.calls)
    assert api.rows[1] == row


def test_forged_pi_marker_from_untrusted_author_is_not_assigned():
    row = pi_incident(); row["user"] = {"login": "unrelated-user"}
    api = API([row])
    with pytest.raises(cloud.DeliveryError, match="PI_INCIDENT_IDENTITY_CHANGED"):
        cloud.reconcile(api, report(current=True))
    assert all(method == "GET" for method, _, _ in api.calls)


def test_ambiguous_post_is_reconciled_by_all_state_enumeration():
    api = API(); api.ambiguous_create = True
    with pytest.raises(cloud.DeliveryError): cloud.reconcile(api, report())
    assert cloud.reconcile(api, report())["status"] == "UNCHANGED"
    assert sum(method == "POST" and path == "issues" for method, path, _ in api.calls) == 1


def test_unknown_never_closes_existing_incident():
    api = API([legacy(state="closed")])
    cloud.reconcile(api, cloud.collect_check(unavailable=True, clock=lambda: NOW))
    assert api.rows[1]["state"] == "open" and "UNKNOWN" in api.rows[1]["body"]


def test_grace_neither_creates_nor_closes_publication_issue():
    api = API([legacy()])
    result = report(datetime.fromisoformat("2026-10-11T01:17:00+11:00"))
    assert cloud.reconcile(api, result)["status"] == "GRACE_NO_PUBLICATION_CHANGE"
    assert all(method == "GET" for method, _, _ in api.calls)


def test_current_receipt_closes_only_publication_not_reported_partial_capture():
    partial = pi_incident(); api = API([legacy(), partial])
    result = report(current=True)
    cloud.reconcile(api, result)
    assert api.rows[1]["state"] == "closed"
    assert api.rows[879]["state"] == "open" and api.rows[879]["body"] == partial["body"]
    assert api.rows[879]["assignees"] == [{"login": "yanniedog"}]
    assert result["reported_ingest_incidents"] == [{"key": "ingest:2026-10-11", "issue": 879,
                                                   "evidence_scope": "open_github_incident_not_fresh_pi_health"}]
    assert "Private-looking" not in json.dumps(result)


def test_pi_incident_selection_requires_exact_date_type_and_binding():
    api = API([pi_incident(2, day="2026-10-10"), pi_incident(3, "ingest-watchdog"),
               {**pi_incident(4), "pull_request": {}}])
    result = report(current=True); cloud.reconcile(api, result)
    assert [row["issue"] for row in result["reported_ingest_incidents"]] == [3]
    forged = pi_incident(); forged["body"] = "wrong marker"
    with pytest.raises(cloud.DeliveryError, match="IDENTITY_CHANGED"):
        cloud.reconcile(API([forged]), report(current=True))


def test_pagination_finds_existing_issue_beyond_first_page():
    rows = [{"number": n, "title": "unrelated"} for n in range(1, 101)] + [legacy(101, "closed")]
    api = API(rows); cloud.reconcile(api, report())
    assert len(api.rows) == 101 and api.rows[101]["state"] == "open"
    assert any("page=2" in path for _, path, _ in api.calls)


@pytest.mark.parametrize("mode", ["error", "malformed", "limit", "duplicate"])
def test_unproven_issue_lookup_never_creates(mode):
    api = API([legacy(1), legacy(2)])
    original = api.request
    def request(method, path, value=None):
        assert method == "GET"
        if mode == "error": raise cloud.DeliveryError("GITHUB_HTTP_503")
        if mode == "malformed": return {"error": "unexpected"}
        if mode == "limit": return [{"title": "other"} for _ in range(100)]
        return original(method, path, value)
    api.request = request
    with pytest.raises(cloud.DeliveryError): cloud.reconcile(api, report())


def test_failed_delivery_artifact_retains_unknown_and_exit_failure(tmp_path, monkeypatch):
    cloud_report = report()
    monkeypatch.setattr(cloud, "collect_check", lambda **k: cloud_report)
    def failure(*args, **kwargs): raise cloud.DeliveryError("GITHUB_HTTP_503")
    monkeypatch.setattr(cloud, "GitHub", failure)
    output = tmp_path / "check.json"
    assert cloud.main(["--output", str(output)]) == 1
    value = json.loads(output.read_text())
    assert value["status"] == "STALE" and value["delivery"]["status"] == "FAILED"
    assert value["attention_required"] is True


def test_current_publication_with_open_pi_incident_still_fails_run(tmp_path, monkeypatch):
    value = report(current=True); api = API([pi_incident()])
    monkeypatch.setattr(cloud, "collect_check", lambda **k: value)
    monkeypatch.setattr(cloud, "GitHub", lambda *a: api)
    output = tmp_path / "check.json"
    assert cloud.main(["--output", str(output)]) == 1
    saved = json.loads(output.read_text())
    assert saved["status"] == "CURRENT" and saved["attention_required"] is True
    assert saved["reported_ingest_incidents"][0]["issue"] == 879
    assert not any(method == "POST" for method, _, _ in api.calls)


def test_unchanged_partial_incident_warns_without_repeated_failure_notification(tmp_path, monkeypatch, capsys):
    value = report(current=True); row = pi_incident(); row["assignees"] = [{"login": cloud.OWNER}]
    api = API([row])
    monkeypatch.setattr(cloud, "collect_check", lambda **k: value)
    monkeypatch.setattr(cloud, "GitHub", lambda *a: api)
    summary = tmp_path / "summary.md"; outputs = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary)); monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    output = tmp_path / "check.json"
    assert cloud.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["attention_required"] is True
    assert "::warning::" in capsys.readouterr().out
    assert "attention_required=true" in outputs.read_text()
    assert "cannot certify a complete ingest" in summary.read_text()
    assert all(method == "GET" for method, _, _ in api.calls)


def test_unchanged_stale_publication_does_not_repeat_failure_escalation(tmp_path, monkeypatch):
    value = report(); api = API(); cloud.reconcile(api, value)
    monkeypatch.setattr(cloud, "collect_check", lambda **k: value)
    monkeypatch.setattr(cloud, "GitHub", lambda *a: api)
    output = tmp_path / "check.json"
    assert cloud.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["attention_required"] is True


def test_unknown_check_fails_even_when_its_issue_is_unchanged(tmp_path, monkeypatch):
    value = cloud.collect_check(unavailable=True, clock=lambda: NOW)
    api = API(); cloud.reconcile(api, value)
    monkeypatch.setattr(cloud, "collect_check", lambda **k: value)
    monkeypatch.setattr(cloud, "GitHub", lambda *a: api)
    assert cloud.main(["--output", str(tmp_path / "check.json")]) == 1
