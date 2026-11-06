#!/usr/bin/env python3
"""Publish withheld daily payloads over an operator-waived policy gate.

Operator decisions (repository owner):
- 2026-11-06: observations withheld *only* by ``unverified_provider_population``
  may be published (``--policy population``).
- 2026-11-07: a GitHub payload must exist for every observed date. The CDR source
  data for past dates no longer exists upstream; the Pi's retained capture is the
  only copy. Any policy verdict may be waived (``--policy all``) so the best
  retained capture is published with its coverage disclosed in the payload.

Integrity is never waived. This runner reuses the production checkout's own daily
publication path (``pi_daily_sync.maybe_publish_app_payload``), so the sealed
contract/ledger/marker binding, payload format, revision coordination,
encryption, the dates index and the pending-marker queue behave exactly as on a
natural daily retry. The one change is a scoped wrapper around
``app_payload_observation_gate.publication_allowed`` that admits a refused
verdict only for the authorised dates and the exact contract digests pinned by
the preceding report, and records a receipt for each waived publication.

``--inventory`` lists every finalized ledger generation for a date with its
coverage so the most complete retained capture can be confirmed. ``--report``
and ``--inventory`` write nothing. Run inside a bounded systemd unit as the daily
service user with the daily service environment (the workflow does this).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WAIVED = "unverified_provider_population"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DIGEST = re.compile(r"[0-9a-f]{64}")
AUTHORITY = {
    "population": "repository owner, 2026-11-06 (population verdict only)",
    "all": "repository owner, 2026-11-07 (payload for every observed date)",
}


def emit(**row):
    print("WAIVER " + json.dumps(row, sort_keys=True), flush=True)


def policy_without_population(gate, contract):
    """``publication_allowed`` after its population check, on the original contract.

    The contract is never modified: its sealed source-generation and contract
    digests cover ``coverage``, and the reconciled-partial policy re-verifies
    them, so a stripped copy would fail integrity rather than policy. These are
    the production gate's own predicates, in its own order.
    """
    state = str(contract.get("observation_state") or "unknown")
    if state == "complete":
        return True, "complete"
    if state == "partial":
        if gate.bounded_partial_v1_allowed(contract):
            if gate.authentication_exclusions(contract)["failure_records"]:
                return True, "bounded_partial_with_nonblocking_authentication"
            return True, "bounded_partial"
        if gate.reconciled_partial_v1_allowed(contract):
            return True, "reconciled_partial"
        return False, "outside_bounded_v1_policy"
    return False, f"observation_state={state}"


def classify(gate, contract, policy="population"):
    """(decision, detail) for one contract under the operator waiver."""
    allowed, reason = gate.publication_allowed(contract)
    if allowed:
        return "admitted", reason
    if policy == "all":
        return "waivable", "operator_waived_all:" + reason
    if reason != WAIVED:
        return "refused", reason
    inner_allowed, inner = policy_without_population(gate, contract)
    return ("waivable", inner) if inner_allowed else ("refused", WAIVED + "+" + inner)


def sealed_status_intact(source, exports, contract):
    """Integrity half of ``reconciled_failure_statuses``: bytes match the seal."""
    import hashlib
    descriptors = [a for a in contract.get("artifacts") or []
                   if isinstance(a, dict) and a.get("path") == "ingest-status.json"]
    if not descriptors:
        return True
    if len(descriptors) != 1:
        return False
    descriptor = descriptors[0]
    try:
        size = descriptor["bytes"]
        if type(size) is not int or not 0 < size <= 8 * 1024 * 1024:
            return False
        with source._within(exports, "ingest-status.json").open("rb") as stream:
            raw = stream.read(size + 1)
        return len(raw) == size and hashlib.sha256(raw).hexdigest() == descriptor["sha256"]
    except (KeyError, OSError, ValueError, TypeError):
        return False


def dated_release_complete(day):
    """True only when ``app-payload-<day>`` serves a live manifest for ``day``.

    ``maybe_publish_app_payload`` can report success once the rolling manifest is
    confirmed even if the dated alias upload failed; the pending pointer must stay
    queued until the dated release itself is usable. This is the publisher's own
    check (``_published_history_dates`` uses it): the public manifest URL is
    fetched, decoded and its ``run_date`` compared.
    """
    from app_payload import DEFAULT_REPO, _live_manifest_status, dated_tag
    status, live = _live_manifest_status(DEFAULT_REPO, dated_tag(day))
    return status == "present" and isinstance(live, dict) and str(live.get("run_date") or "") == day


def completeness(contract):
    """Sort key: most complete retained capture first (higher is better)."""
    coverage = contract.get("coverage") or {}
    number = lambda key: coverage.get(key) if type(coverage.get(key)) is int else 0  # noqa: E731
    return (contract.get("observation_state") == "complete", number("eligible_rate_rows"),
            number("products_discovered"), -number("failure_records"),
            -len(coverage.get("provider_population_unverified") or []),
            str(contract.get("generation_id") or ""))


def ledger_candidates(state, day, load_contract, load_pointer_observation):
    """Verified (pointer, contract) pairs for every finalized ledger generation.

    The pointer is built exactly as pi_cdr_selection_recovery builds one and is
    then verified by load_pointer_observation (marker, event, contract binding).
    """
    found = []
    for path in sorted((state / "ledger-v2" / "events" / day).glob("*.json")):
        try:
            event = json.loads(path.read_bytes())
            contract = load_contract((state.resolve() / event["contract_path"]).resolve())
            pointer = {"schema_version": 2, "observation_date": day,
                       "generation_id": contract["generation_id"],
                       "observation_state": contract["observation_state"],
                       "ledger_event_digest": event.get("event_digest"),
                       "marker_path": contract.get("completion_marker_path"),
                       "export_path": contract.get("source_path")}
            found.append((pointer, load_pointer_observation(state, pointer)["contract"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def candidates_by_date(daily, retry, repo, dates):
    pending = daily.read_payload_publication_pending(repo)
    found = {}
    for candidate in retry.publication_retry_candidates(pending):
        pointer = candidate.get("pointer")
        if isinstance(pointer, dict) and pointer.get("observation_date") in dates:
            found.setdefault(pointer["observation_date"], []).append(pointer)
    return found


def coverage_summary(contract):
    coverage = contract.get("coverage") or {}
    states = {}
    for provider in contract.get("provider_states") or []:
        states[str(provider.get("state"))] = states.get(str(provider.get("state")), 0) + 1
    keys = ("providers_attempted", "products_discovered", "eligible_rate_rows", "failure_records")
    return dict({key: coverage.get(key) for key in keys},
                provider_states=states,
                unverified_providers=len(coverage.get("provider_population_unverified") or []))


def inventory(state, gate, day, pending_ids, load_contract, verify_event):
    """Every finalized generation for ``day`` with its coverage (read-only).

    Each event passes the ledger's own verification (stored-event identity and
    contract binding) before its contract is summarised.
    """
    rows = []
    for path in sorted((state / "ledger-v2" / "events" / day).glob("*.json")):
        event = {"generation_id": path.stem}
        try:
            raw = json.loads(path.read_bytes())
            if not isinstance(raw, dict):
                raise ValueError("ledger event is not an object")
            event = verify_event(state, raw)
            contract = load_contract((state.resolve() / event["contract_path"]).resolve())
            allowed, reason = gate.publication_allowed(contract)
            rows.append(dict(date=day, inventory=event.get("generation_id"),
                             event_type=event.get("event_type"),
                             observation_state=contract.get("observation_state"),
                             pending=event.get("generation_id") in pending_ids,
                             gate=reason, admitted=allowed, **coverage_summary(contract)))
        except (OSError, ValueError, KeyError) as error:
            rows.append(dict(date=day, inventory=event.get("generation_id"), error=str(error)[:200]))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--date", action="append", default=[])
    parser.add_argument("--pending-since", metavar="DATE",
                        help="also select every date on or after DATE that has a withheld pending pointer")
    parser.add_argument("--policy", choices=sorted(AUTHORITY), default="population")
    parser.add_argument("--allow-digest", action="append", default=[],
                        help="publish mode: date=contract_digest admitted by the gate report")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inventory", action="store_true")
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    dates = sorted(set(args.date))
    if not all(DATE.fullmatch(d) for d in dates + [args.pending_since or "0000-00-00"]):
        parser.error("dates must be YYYY-MM-DD")
    if not dates and not args.pending_since:
        parser.error("give --date and/or --pending-since")
    allowed_digests = {}
    for item in args.allow_digest:
        day, _, digest = item.partition("=")
        if not DATE.fullmatch(day) or not DIGEST.fullmatch(digest) or (
                day not in dates and not (args.pending_since and day >= args.pending_since)):
            parser.error("--allow-digest must be DATE=SHA256 for a requested date")
        allowed_digests[day] = digest
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo))

    import app_payload_observation_gate as gate
    import pi_daily_sync as daily
    import pi_payload_retry_policy as retry
    from ar_local_pi_runtime import data_state_root
    from cdr_atomic import atomic_write_json
    from cdr_observation_selection import load_pointer_observation

    state = data_state_root(repo)
    if args.pending_since:
        pending = daily.read_payload_publication_pending(repo)
        for candidate in retry.publication_retry_candidates(pending):
            pointer = candidate.get("pointer")
            day = pointer.get("observation_date") if isinstance(pointer, dict) else None
            if isinstance(day, str) and DATE.fullmatch(day) and day >= args.pending_since:
                dates.append(day)
        # A finalized capture whose pending pointer was lost must not be stranded:
        # every date up to yesterday without a usable dated release is selected
        # too, and served from its best verified ledger generation.
        from datetime import date, timedelta
        from zoneinfo import ZoneInfo
        day = date.fromisoformat(args.pending_since)
        yesterday = datetime.now(ZoneInfo("Australia/Hobart")).date() - timedelta(days=1)
        while day <= yesterday:
            if day.isoformat() not in dates and not dated_release_complete(day.isoformat()):
                dates.append(day.isoformat())
            day += timedelta(days=1)
        dates = sorted(set(dates))
        emit(selected=dates)
        if not dates:
            return 0
    if args.inventory:
        from cdr_export_contract import load_contract
        from cdr_ledger_v2 import verify_event
        found = candidates_by_date(daily, retry, repo, set(dates))
        for day in dates:
            pending_ids = {p.get("generation_id") for p in found.get(day) or []}
            for row in inventory(state, gate, day, pending_ids, load_contract, verify_event):
                emit(**row)
        return 0
    if (window := retry.payload_retry_window_reason()):
        emit(result="DEFERRED", reason=window)
        return 3
    lock = daily.DailyIngestLock(state / "daily-ingest.lock")
    failures = 0
    with lock:
        found = candidates_by_date(daily, retry, repo, set(dates))
        from cdr_export_contract import load_contract
        plan = []
        for day in dates:
            pending = []
            for pointer in found.get(day) or []:
                try:
                    pending.append((pointer, load_pointer_observation(state, pointer)["contract"]))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    emit(date=day, pending_pointer_invalid=pointer.get("generation_id"), error=str(error)[:200])
            source_kind, options = "pending", pending
            if not options and args.pending_since:
                source_kind = "ledger"
                options = ledger_candidates(state, day, load_contract, load_pointer_observation)
            if not options:
                emit(date=day, decision="refused", detail="no_verified_capture")
                failures += 1
                continue
            # Several captures for one date: publish the most complete one.
            pointer, contract = max(options, key=lambda item: completeness(item[1]))
            others = [p for p, _ in pending if p is not pointer]
            decision, detail = classify(gate, contract, args.policy)
            digest = str(contract.get("contract_digest") or "")
            emit(date=day, decision=decision, detail=detail, contract_digest=digest,
                 generation_id=contract.get("generation_id"), source=source_kind,
                 alternatives=len(options) - 1,
                 observation_state=contract.get("observation_state"),
                 unverified_providers=len((contract.get("coverage") or {}).get("provider_population_unverified") or []))
            if decision == "refused":
                failures += 1
            else:
                plan.append((day, pointer, digest, decision, detail, source_kind, others))
        if args.report:
            return 1 if failures else 0

        authorised = {day: digest for day, digest in allowed_digests.items()}
        original = gate.publication_allowed

        def scoped(contract):
            allowed, reason = original(contract)
            if allowed or not isinstance(contract, dict):
                return allowed, reason
            day = contract.get("observation_date")
            if authorised.get(day) != contract.get("contract_digest"):
                return allowed, reason
            if args.policy == "all":
                return True, "operator_waived_all:" + reason
            if reason != WAIVED:
                return allowed, reason
            inner_allowed, inner = policy_without_population(gate, contract)
            return (True, "operator_waived_population:" + inner) if inner_allowed else (allowed, reason)

        # pi_daily_sync re-checks a partial capture's raw failure statuses inside
        # verify_reconciled_source. Under ``--policy all`` that classification is
        # a policy verdict too, so it is waived for the pinned digests only. The
        # marker/contract binding in verify_reconciled_source still runs, and the
        # contract-bound ingest-status.json must still match its sealed digest.
        import app_payload_source_verification as source
        original_statuses = source.reconciled_failure_statuses

        def scoped_statuses(exports, contract):
            if original_statuses(exports, contract):
                return True
            if args.policy != "all" or not isinstance(contract, dict):
                return False
            if authorised.get(contract.get("observation_date")) != contract.get("contract_digest"):
                return False
            return sealed_status_intact(source, exports, contract)

        gate.publication_allowed = scoped
        source.reconciled_failure_statuses = scoped_statuses
        try:
            for day, pointer, digest, decision, detail, source_kind, others in plan:
                if decision == "waivable" and authorised.get(day) != digest:
                    emit(date=day, result="SKIPPED", reason="digest_not_authorised")
                    failures += 1
                    continue
                outcome = daily.maybe_publish_app_payload(repo, pointer)
                emit(date=day, result=outcome, contract_digest=digest, decision=decision)
                if outcome != daily.PUBLISH_PUBLISHED:
                    failures += 1
                    continue
                if not dated_release_complete(day):
                    emit(date=day, result="DATED_RELEASE_INCOMPLETE", detail="pointer kept pending")
                    failures += 1
                    continue
                if decision == "waivable":
                    # Receipt first: if the run stops before the pointer clears,
                    # the date is retried and the audit record already exists.
                    receipt = {
                        "schema_version": 1, "reason": "operator_waived_" + args.policy,
                        "authority": AUTHORITY[args.policy],
                        "observation_date": day, "contract_digest": digest,
                        "generation_id": pointer.get("generation_id"),
                        "waived_verdict": detail, "pointer": pointer, "source": source_kind,
                        "published_at": datetime.now(timezone.utc).isoformat(),
                    }
                    receipt_path = state / "population-waiver-publications-v1" / f"{digest}.json"
                    if not receipt_path.exists():
                        atomic_write_json(receipt_path, receipt, create_once=True)
                # The published capture and any less complete alternatives for the
                # same date leave the queue; a ledger-recovered capture was never in it.
                for queued in ([pointer] if source_kind == "pending" else []) + others:
                    daily.clear_payload_publication_pending(repo, queued)
        finally:
            gate.publication_allowed = original
            source.reconciled_failure_statuses = original_statuses
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
