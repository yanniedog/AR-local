"""Crash recovery and sanitization contracts for immutable HTTP evidence."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from cdr_raw_attempt_journal import AttemptJournalError, RawAttemptJournal


FIXED = {
    "request_url": "https://holder.example/products?page=2&token=do-not-store",
    "request_headers": {
        "Accept": "application/json",
        "Authorization": "Bearer do-not-store",
        "x-v": "4",
    },
    "started_at": "2026-08-15T00:00:00.000000Z",
    "completed_at": "2026-08-15T00:00:01.000000Z",
    "status": 503,
    "outcome": "http_error",
    "response_headers": {
        "Content-Type": "application/json",
        "Retry-After": "5",
        "Set-Cookie": "session=do-not-store",
    },
    "body": b'{"errors":[]}',
    "wire_bytes": 13,
    "inflated_bytes": 13,
    "peer_ip": "8.8.8.8",
    "retry_after_seconds": 5.0,
    "error_code": "upstream_unavailable",
    "error_message": "retry https://holder.example/path?api_key=do-not-store",
    "context": {
        "phase": "products_index",
        "provider": "Holder",
        "api_key": "do-not-store",
        "nested": {"token": "do-not-store"},
    },
}


def test_attempt_evidence_is_sanitized_and_body_is_content_addressed(tmp_path):
    journal = RawAttemptJournal(tmp_path, "session-1")
    event = journal.record("attempt-1", **FIXED)
    serialized = json.dumps(event, sort_keys=True)

    assert "do-not-store" not in serialized
    assert event["request"]["url"].endswith("page=2&token=%5BREDACTED%5D")
    assert event["request"]["headers"] == {
        "accept": "application/json",
        "x-v": "4",
    }
    assert "set-cookie" not in event["response"]["headers"]
    assert event["context"]["api_key"] == "[REDACTED]"
    assert event["context"]["nested"]["token"] == "[REDACTED]"
    assert (journal.root / event["body_path"]).read_bytes() == FIXED["body"]
    assert journal.summary()["verified"] is True


def test_same_attempt_key_is_idempotent_but_conflicting_evidence_fails(tmp_path):
    journal = RawAttemptJournal(tmp_path, "session-1")
    first = journal.record("attempt-1", **FIXED)
    replay = journal.record("attempt-1", **FIXED)
    assert replay == first
    assert len(list(journal.events.glob("*.json"))) == 1

    conflicting = {**FIXED, "body": b"different", "wire_bytes": 9, "inflated_bytes": 9}
    with pytest.raises(AttemptJournalError, match="different evidence"):
        journal.record("attempt-1", **conflicting)


@pytest.mark.parametrize(
    "override,match",
    [
        ({"wire_bytes": -1}, "byte counts"),
        ({"inflated_bytes": 12}, "must match"),
        ({"wire_sha256": "not-a-digest"}, "wire digest"),
        ({"retry_after_seconds": 61}, "outside the policy"),
    ],
)
def test_invalid_or_uncapped_transport_metadata_is_rejected(tmp_path, override, match):
    journal = RawAttemptJournal(tmp_path, "session-1")
    with pytest.raises(AttemptJournalError, match=match):
        journal.record("attempt-1", **{**FIXED, **override})


@pytest.mark.parametrize("failure_stage", ["after_body", "after_event", "after_key", "after_current"])
def test_each_atomic_failure_boundary_recovers_without_duplicate_sequence(
    tmp_path,
    failure_stage,
):
    failed = False

    def inject(stage):
        nonlocal failed
        if stage == failure_stage and not failed:
            failed = True
            raise RuntimeError(f"simulated crash at {stage}")

    journal = RawAttemptJournal(tmp_path, "session-1", fault_injector=inject)
    with pytest.raises(RuntimeError, match="simulated crash"):
        journal.record("attempt-1", **FIXED)

    recovered = journal.record("attempt-1", **FIXED)
    assert recovered["sequence"] == 1
    assert len(list(journal.events.glob("*.json"))) == 1
    assert len(list(journal.keys.glob("*.json"))) == 1
    assert journal.summary()["attempts"] == 1


def test_concurrent_attempts_receive_one_contiguous_sequence(tmp_path):
    journal = RawAttemptJournal(tmp_path, "session-1")

    def record(index):
        evidence = {
            **FIXED,
            "request_url": f"https://holder.example/products/{index}",
            "context": {"phase": "product_detail", "product_id": f"P{index}"},
        }
        return journal.record(f"attempt-{index}", **evidence)

    with ThreadPoolExecutor(max_workers=8) as pool:
        events = list(pool.map(record, range(24)))

    assert sorted(event["sequence"] for event in events) == list(range(1, 25))
    summary = journal.summary()
    assert summary["attempts"] == 24
    assert summary["verified"] is True


def test_tampered_committed_event_or_body_fails_verification(tmp_path):
    journal = RawAttemptJournal(tmp_path, "session-1")
    event = journal.record("attempt-1", **FIXED)
    event_path = next(journal.events.glob("*.json"))
    event_payload = json.loads(event_path.read_text(encoding="utf-8"))
    event_payload["response"]["status"] = 200
    event_path.write_text(json.dumps(event_payload), encoding="utf-8")
    with pytest.raises(AttemptJournalError, match="digest mismatch"):
        journal.summary()

    second = RawAttemptJournal(tmp_path, "session-2")
    second_event = second.record("attempt-1", **FIXED)
    (second.root / second_event["body_path"]).write_bytes(b"tampered")
    with pytest.raises(AttemptJournalError, match="does not match"):
        second.summary()


@pytest.mark.parametrize(
    "session_id",
    ["", "../escape", "two/parts", "bad space", "CON", "lpt1.txt", "trailing."],
)
def test_session_id_is_one_safe_path_segment(tmp_path, session_id):
    with pytest.raises(ValueError):
        RawAttemptJournal(tmp_path, session_id)


def test_uncommitted_out_of_sequence_event_is_not_ignored(tmp_path):
    journal = RawAttemptJournal(tmp_path, "session-1")
    journal.record("attempt-1", **FIXED)
    stray = journal.events / "00000099-deadbeefdeadbeef.json"
    stray.write_text("{}", encoding="utf-8")
    with pytest.raises(AttemptJournalError, match="uncommitted event"):
        journal.summary()
