"""Bounded off-Pi publication check and one GitHub incident per due date."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ar_local_ingest_schedule import expected_run_date_for_due, latest_daily_due_utc
from pi_github_alerts import DeliveryError, GitHub

REPOSITORY = "yanniedog/AR-local"
OWNER = "yanniedog"
LABEL = "ingest-missed"
GRACE = timedelta(minutes=90)
MAX_CHECK_BYTES = 65536
PUBLICATION_TITLE = "Pi app publication needs attention: "


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate check field")
        result[key] = value
    return result


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("naive check timestamp")
    return parsed.astimezone(timezone.utc)


def validate_check(raw: bytes, returncode: int, now: datetime) -> tuple[dict, str]:
    """Only a complete, consistent receipt check can resolve an incident."""
    if len(raw) > MAX_CHECK_BYTES:
        raise ValueError("check response exceeds limit")
    value = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError("check object required")
    observed = timestamp(value["now_utc"])
    due = latest_daily_due_utc(observed)
    expected = expected_run_date_for_due(due)
    if (abs((now - observed).total_seconds()) > 300
            or timestamp(value["due_utc"]) != due
            or timestamp(value["ready_at_utc"]) != due + GRACE
            or value["expected_run_date"] != expected
            or value["schedule_timezone"] != "Australia/Hobart"
            or value["schedule_local_hour"] != 1
            or value["verification_scope"] != "public_ciphertext_receipt"):
        raise ValueError("check schedule or scope differs")
    for name in ("manifest_run_date", "dates_index_latest_date"):
        day = value[name]
        if not isinstance(day, str) or (day and date.fromisoformat(day).isoformat() != day):
            raise ValueError("invalid publication date")
    issues = value["publication_issues"]
    if (not isinstance(issues, list) or len(issues) > 32
            or any(not isinstance(item, str) or not re.fullmatch(r"[a-z0-9_]{1,100}", item) for item in issues)):
        raise ValueError("invalid publication categories")
    current, stale = value["publication_current"], value["stale"]
    if type(current) is not bool or type(stale) is not bool:
        raise ValueError("explicit check booleans required")
    if current and (issues or value["manifest_run_date"] != expected
                    or value["dates_index_latest_date"] != expected
                    or value["manifest_error"] is not None or value["dates_index_error"] is not None):
        raise ValueError("contradictory current publication")
    if stale != (observed >= due + GRACE and not current) or returncode != int(stale):
        raise ValueError("check outcome or exit status differs")
    status = "GRACE" if observed < due + GRACE else ("CURRENT" if current else "STALE")
    return value, status


def collect_check(*, unavailable=False, run=subprocess.run, clock=None) -> dict:
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    report = {"schema_version": 1, "observed_at": now.isoformat(),
              "expected_run_date": expected_run_date_for_due(latest_daily_due_utc(now)),
              "status": "UNKNOWN", "reason": "CHECK_INFRASTRUCTURE_FAILED",
              "verification_scope": "public_ciphertext_receipt", "publication": None,
              "reported_ingest_incidents": [],
              "delivery": {"status": "NOT_ATTEMPTED"}}
    if unavailable:
        return report
    try:
        result = run([sys.executable, "-B", str(ROOT / "scripts/pi_ingest_manifest_check.py"),
                      "--public-receipt", "--grace-minutes", "90", "--json"],
                     cwd=ROOT, capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.SubprocessError):
        report["reason"] = "CHECK_PROCESS_FAILED"
        return report
    try:
        value, status = validate_check(result.stdout, result.returncode, clock())
    except (ValueError, KeyError, TypeError, OverflowError):
        report["reason"] = "CHECK_INVALID_RESULT"
        return report
    report.update(expected_run_date=value["expected_run_date"], status=status,
                  reason="PUBLICATION_" + status, publication=value)
    return report


def find_incidents(client, expected):
    """Bounded enumeration also retains distinct, already-reported Pi failures."""
    titles = {"Pi ingest missed: " + expected, PUBLICATION_TITLE + expected}
    pi_titles = {"Pi ingest needs attention: " + expected: "ingest:",
                 "Pi scheduled ingest missed: " + expected: "ingest-schedule:",
                 "Pi ingest watchdog failed: " + expected: "ingest-watchdog:",
                 "Pi ingest/publication check needs attention: " + expected: "ingest-watchdog:"}
    matches, reported, reported_keys = [], [], set()
    for page in range(1, 21):
        rows = client.request("GET", f"issues?state=all&per_page=100&page={page}")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DeliveryError("GITHUB_INVALID_ISSUE_LIST")
        for row in rows:
            if "pull_request" in row:
                continue
            if row.get("title") in titles:
                creator = row.get("user")
                labels = row.get("labels", [])
                legacy = isinstance(labels, list) and any(
                    isinstance(label, dict) and label.get("name") == LABEL for label in labels)
                marker = "<!-- ar-local-cloud-publication:" + expected + " -->"
                if (not isinstance(creator, dict) or creator.get("login") != "github-actions[bot]"
                        or not (legacy or marker in str(row.get("body", "")))):
                    raise DeliveryError("GITHUB_PUBLICATION_INCIDENT_IDENTITY_CHANGED")
                matches.append(row)
            if row.get("state") == "open" and row.get("title") in pi_titles:
                key = pi_titles[row["title"]] + expected
                digest = hashlib.sha256((REPOSITORY + ":" + key).encode()).hexdigest()
                creator = row.get("user")
                if (not isinstance(creator, dict) or creator.get("login") != OWNER
                        or "<!-- ar-local-pi-incident:" + digest + " -->" not in str(row.get("body", ""))):
                    raise DeliveryError("GITHUB_PI_INCIDENT_IDENTITY_CHANGED")
                if key in reported_keys:
                    raise DeliveryError("GITHUB_AMBIGUOUS_PI_INCIDENT")
                reported_keys.add(key)
                reported.append((key, row))
        if len(rows) < 100:
            if len(matches) > 1:
                raise DeliveryError("GITHUB_AMBIGUOUS_DATE_INCIDENT")
            return (matches[0] if matches else None), reported
    raise DeliveryError("GITHUB_ISSUE_ENUMERATION_LIMIT")


def issue_body(report):
    publication = report["publication"] or {}
    return "\n".join([
        "<!-- ar-local-cloud-publication:" + report["expected_run_date"] + " -->", "",
        "Off-Pi public app publication check: **" + report["status"] + "**.", "",
        "- Expected run_date: **" + report["expected_run_date"] + "**",
        "- Manifest run_date: **" + (publication.get("manifest_run_date") or "unknown") + "**",
        "- Dates index latest_date: **" + (publication.get("dates_index_latest_date") or "unknown") + "**",
        "- Check category: `" + report["reason"] + "`",
        "- Publication issues: " + (", ".join(publication.get("publication_issues", [])) or "none reported"), "",
        "Scope: operational ciphertext receipt only. A current publication does not prove a full ingest, "
        "complete provider capture, or continuous historical coverage. Pi capture incidents remain separate.",
        "A missing receipt or failed check does not identify whether the router, Pi, publication, or monitor failed.", "",
        "Expected ingest: 01:00 Australia/Hobart; publication grace: 90 minutes. "
        "Checks are scheduled every 30 minutes; GitHub may delay or skip a run.",
        "This issue retains one date's identity. Unchanged checks do not add comments.",
    ])


def ensure_label(client):
    try:
        client.request("GET", "labels/" + LABEL)
    except DeliveryError as error:
        if str(error) != "GITHUB_HTTP_404":
            raise
        client.request("POST", "labels", {"name": LABEL, "color": "B60205",
                       "description": "Public daily app publication unavailable or unverified"})


def issue_identity(issue):
    number = issue.get("number")
    assignees = issue.get("assignees")
    if (type(number) is not int or number <= 0 or issue.get("state") not in {"open", "closed"}
            or not isinstance(assignees, list)
            or any(not isinstance(row, dict) or not isinstance(row.get("login"), str) for row in assignees)):
        raise DeliveryError("GITHUB_INVALID_INCIDENT")
    return number, [row["login"] for row in assignees]


def reconcile(client, report):
    issue, reported = find_incidents(client, report["expected_run_date"])
    report["reported_ingest_incidents"] = [
        {"key": key, "issue": issue_identity(row)[0],
         "evidence_scope": "open_github_incident_not_fresh_pi_health"}
        for key, row in reported]
    assigned_now = []
    for _, row in reported:
        number, assigned = issue_identity(row)
        if OWNER not in assigned:
            client.request("PATCH", f"issues/{number}", {"assignees": [*assigned, OWNER]})
            assigned_now.append(number)
    evidence = {"assigned_ingest_issues": assigned_now, "new_attention": bool(assigned_now)}
    if report["status"] == "GRACE":
        return {"status": "GRACE_NO_PUBLICATION_CHANGE", **evidence}
    if issue is None and report["status"] == "CURRENT":
        return {"status": "CURRENT_NO_PUBLICATION_INCIDENT", **evidence}
    state = "closed" if report["status"] == "CURRENT" else "open"
    body = issue_body(report)
    if issue is None:
        ensure_label(client)
        title = PUBLICATION_TITLE + report["expected_run_date"]
        created = client.request("POST", "issues", {"title": title, "body": body,
                                  "labels": [LABEL], "assignees": [OWNER]})
        if not isinstance(created, dict) or type(created.get("number")) is not int or created["number"] <= 0:
            raise DeliveryError("GITHUB_INVALID_CREATED_ISSUE")
        return {"status": "CREATED", "issue": created["number"], **evidence, "new_attention": True}
    number, assigned = issue_identity(issue)
    changes = {}
    title = PUBLICATION_TITLE + report["expected_run_date"]
    if issue.get("title") != title:
        changes["title"] = title
    stored_body = issue.get("body")
    # GitHub may return CRLF for the LF body we submitted. Preserve all other
    # whitespace/content distinctions so real changes still trigger an update.
    if not isinstance(stored_body, str) or stored_body.replace("\r\n", "\n") != body:
        changes["body"] = body
    if issue["state"] != state:
        changes["state"] = state
    if OWNER not in assigned:
        changes["assignees"] = [*assigned, OWNER]
    if changes:
        client.request("PATCH", f"issues/{number}", changes)
    return {"status": "UPDATED" if changes else "UNCHANGED", "issue": number, **evidence,
            "new_attention": bool(assigned_now) or (state == "open" and bool(changes))}


def write_report(path, report):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def workflow_outputs(report):
    attention = str(report["attention_required"]).lower()
    scope = "Receipt verification cannot certify a complete ingest; open Pi issues are reported evidence, not fresh Pi health."
    if report["attention_required"]:
        print("::warning::Daily ingest/publication still requires attention; see check.json and the existing issues.")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"attention_required={attention}\npublication_status={report['status']}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        issues = ", ".join("#" + str(row["issue"]) for row in report["reported_ingest_incidents"]) or "none observed"
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(f"Publication: **{report['status']}**. Attention required: **{attention}**.\n\n"
                         f"Reported Pi incidents: {issues}. Incident delivery: {report['delivery']['status']}.\n\n"
                         "An unchanged known incident can have a successful monitoring run while still requiring attention. "
                         + scope + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("check.json"))
    parser.add_argument("--checker-unavailable", action="store_true")
    args = parser.parse_args(argv)
    report = collect_check(unavailable=args.checker_unavailable)
    write_report(args.output, report)
    try:
        client = GitHub(REPOSITORY, os.environ.get("GH_TOKEN", ""))
        report["delivery"] = reconcile(client, report)
    except (DeliveryError, OSError, ValueError, TypeError, KeyError):
        # No raw API/credential/checker error text enters public incidents.
        report["delivery"] = {"status": "FAILED", "reason": "INCIDENT_DELIVERY_FAILED"}
    report["attention_required"] = (report["status"] in {"STALE", "UNKNOWN"}
                                    or bool(report["reported_ingest_incidents"])
                                    or report["delivery"]["status"] == "FAILED")
    write_report(args.output, report)
    workflow_outputs(report)
    print(json.dumps(report, sort_keys=True))
    return int(report["status"] == "UNKNOWN" or report["delivery"]["status"] == "FAILED"
               or report["delivery"].get("new_attention", False))


if __name__ == "__main__":
    raise SystemExit(main())
