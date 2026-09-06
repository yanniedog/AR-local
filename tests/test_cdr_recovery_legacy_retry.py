"""Legacy queue regressions replaying the retained September 7 index pages."""

from __future__ import annotations

import json

import pytest

import cdr_recovery_legacy as legacy
from cdr_atomic import canonical_json_bytes
from cdr_observation_selection import provider_directories, selected_observation
from cdr_raw_attempt_journal import RawAttemptJournal
from tests.test_cdr_canary_compatibility import _ingest_index, _pages
from tests.test_cdr_same_day_selection import DATE, finish, make_export


def _observation(tmp_path, monkeypatch, failure, *, diagnostics=True):
    pages = _pages("Defence Bank")
    if failure == "pagination_incomplete":
        del pages[1]["links"]["next"]  # Controlled truncation of the captured chain.
    elif failure == "conflicting_product_identity":
        duplicate = next(row for row in pages[1]["data"]["products"] if row["productId"] == "284")
        duplicate["name"] += " conflict injected by regression test"
    ingest = tmp_path / "ingest"
    ingest.mkdir()
    _, fetched, products, diagnostic, failures = _ingest_index(
        ingest, monkeypatch, "Defence Bank", pages,
    )
    assert [row["status"] for row in failures] == ([failure] if failure else [])
    root, state = tmp_path / "runs" / DATE / "_exports", tmp_path / "state"
    # Reuse the observation/SQLite control fixture with the actual captured IDs.
    # A healthy index is paired with an unrelated terminal detail failure so the
    # provider remains affected without establishing an index failure.
    status = make_export(root, products, failures=1)
    status.update(index_diagnostics={"Provider": diagnostic},
                  by_phase={"products_index" if failure else "product_detail": 1})
    if not diagnostics:
        status.pop("index_diagnostics")
    journal = RawAttemptJournal(root / "attempt-evidence" / "raw-attempt-journals-v1", "legacy-index")
    events = []
    for page in fetched:
        events.append(journal.record(
            f"page-{page}", request_url=pages[page - 1]["links"]["self"],
            status=200, outcome="success", body=json.dumps(pages[page - 1]).encode(),
            started_at=DATE + "T00:00:00Z", completed_at=DATE + "T00:00:01Z",
            context={"provider": "Provider", "phase": "products_index", "page": page},
        ))
    status["raw_attempt_journal"] = {
        "session_id": journal.session_id, "path": journal.root.relative_to(root).as_posix(),
    }
    (root / "ingest-status.json").write_text(json.dumps(status), encoding="utf-8")
    finish(root, state, "done")
    return selected_observation(state, DATE), state / "cdr-recovery-v1" / DATE, events


def _snapshot(root):
    return {path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def _binding(observation):
    return {"generation_id": observation["contract"]["generation_id"],
            "contract_digest": observation["contract"]["contract_digest"],
            "event_digest": observation["event"]["event_digest"]}


@pytest.mark.parametrize("failure", ["pagination_incomplete", "conflicting_product_identity"])
def test_valid_200_pages_remain_eligible_after_terminal_local_index_failure(tmp_path, monkeypatch, failure):
    observation, cache, events = _observation(tmp_path, monkeypatch, failure)
    before = _snapshot(observation["export_root"])
    requests = legacy.legacy_recovery_requests(observation, provider_directories(observation["status"]), cache)
    assert len(requests) == len(events)
    assert {row["source_attempt_event_digest"] for row in requests} == {row["event_digest"] for row in events}
    assert all(row["phase"] == "products_index" and row["status"] == 200 for row in requests)
    assert all(not row["product_id"] for row in requests)
    assert _snapshot(observation["export_root"]) == before


@pytest.mark.parametrize("diagnostics", ["healthy", "absent"])
def test_detail_failure_does_not_turn_healthy_index_into_retry_work(tmp_path, monkeypatch, diagnostics):
    observation, cache, _ = _observation(tmp_path, monkeypatch, None, diagnostics=diagnostics == "healthy")
    assert not legacy.terminal_index_failure(observation["status"], "Provider")
    assert legacy.legacy_recovery_requests(observation, provider_directories(observation["status"]), cache) == []


@pytest.mark.parametrize("previous_requests", [[], [{"phase": "product_detail", "product_id": "obsolete-cache-entry"}]])
def test_old_queue_cache_is_preserved_and_rederived_even_when_empty(tmp_path, monkeypatch, previous_requests):
    observation, cache, events = _observation(tmp_path, monkeypatch, "pagination_incomplete")
    source = _binding(observation)
    cache.mkdir(parents=True)
    old = cache / f"legacy-queue-{source['event_digest']}.json"
    old.write_bytes(canonical_json_bytes({"schema_version": 1, "source": source,
        "requests": previous_requests, "queue_is_complete_failure_inventory": False}))
    before = _snapshot(observation["export_root"]) | _snapshot(cache)
    requests = legacy.legacy_recovery_requests(observation, provider_directories(observation["status"]), cache)
    assert len(requests) == len(events)
    assert all(row["phase"] == "products_index" for row in requests)
    assert all((path.read_bytes(), path.stat().st_mtime_ns) == original for path, original in before.items())
    current = cache / f"legacy-queue-v2-{source['event_digest']}.json"
    saved = json.loads(current.read_bytes())
    assert saved == {"schema_version": 2, "source": source, "requests": requests,
                     "queue_is_complete_failure_inventory": False}
    current_before = (current.read_bytes(), current.stat().st_mtime_ns)
    monkeypatch.setattr(legacy, "_bound_events", lambda *a: pytest.fail("current queue should be cached"))
    monkeypatch.setattr(legacy, "captured_identities", lambda *a: pytest.fail("current queue should be cached"))
    assert legacy.legacy_recovery_requests(observation, provider_directories(observation["status"]), cache) == requests
    assert (current.read_bytes(), current.stat().st_mtime_ns) == current_before


def test_local_index_diagnostic_never_bypasses_body_integrity(tmp_path, monkeypatch):
    observation, cache, events = _observation(tmp_path, monkeypatch, "pagination_incomplete")
    journal_path = observation["status"]["raw_attempt_journal"]["path"]
    body = observation["export_root"] / journal_path / events[0]["body_path"]
    body.write_bytes(body.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed after finalization"):
        legacy.legacy_recovery_requests(observation, provider_directories(observation["status"]), cache)
    assert not cache.exists()


def test_index_recovery_preserves_bounded_journal_scan(tmp_path, monkeypatch):
    observation, cache, _ = _observation(tmp_path, monkeypatch, "pagination_incomplete")
    monkeypatch.setattr(legacy, "MAX_LEGACY_EVENTS", 1)
    with pytest.raises(ValueError, match="scan budget"):
        legacy.legacy_recovery_requests(observation, provider_directories(observation["status"]), cache)
    assert not cache.exists()
