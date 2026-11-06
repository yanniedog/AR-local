#!/usr/bin/env python3
"""Publish withheld daily payloads over an operator-waived population gate.

Operator decision (2026-11-06, repository owner): observations withheld *only*
by ``unverified_provider_population`` may be published. Everything else stays
in force. This runner reuses the production checkout's own daily publication
path (``pi_daily_sync.maybe_publish_app_payload``), so payload format, revision
coordination, encryption, the dates index and the pending-marker queue behave
exactly as on a natural daily retry. The one change is a scoped wrapper around
``app_payload_observation_gate.publication_allowed``: a contract whose sole
blocker is the population flag, and which passes every other policy check with
that flag removed, is admitted as ``operator_waived_population:<policy>``. The
wrapper applies only to the authorised dates and the exact contract digests
reported by the preceding gate report.

Run inside a bounded systemd unit (the workflow does this) as the daily service
user, with the daily service environment. ``--report`` writes nothing.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WAIVED = "unverified_provider_population"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DIGEST = re.compile(r"[0-9a-f]{64}")


def emit(**row):
    print("WAIVER " + json.dumps(row, sort_keys=True), flush=True)


def without_population(contract):
    waived = copy.deepcopy(dict(contract))
    coverage = dict(waived.get("coverage") or {})
    coverage.pop("provider_population_unverified", None)
    waived["coverage"] = coverage
    return waived


def classify(gate, contract):
    """(decision, detail) for one contract under the operator waiver."""
    allowed, reason = gate.publication_allowed(contract)
    if allowed:
        return "admitted", reason
    if reason != WAIVED:
        return "refused", reason
    inner_allowed, inner = gate.publication_allowed(without_population(contract))
    return ("waivable", inner) if inner_allowed else ("refused", WAIVED + "+" + inner)


def candidates_by_date(daily, retry, repo, dates):
    pending = daily.read_payload_publication_pending(repo)
    found = {}
    for candidate in retry.publication_retry_candidates(pending):
        pointer = candidate.get("pointer")
        if isinstance(pointer, dict) and pointer.get("observation_date") in dates:
            found.setdefault(pointer["observation_date"], []).append(pointer)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--date", action="append", required=True)
    parser.add_argument("--allow-digest", action="append", default=[],
                        help="publish mode: date=contract_digest admitted by the gate report")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    dates = sorted(set(args.date))
    if not all(DATE.fullmatch(d) for d in dates):
        parser.error("dates must be YYYY-MM-DD")
    allowed_digests = {}
    for item in args.allow_digest:
        day, _, digest = item.partition("=")
        if not DATE.fullmatch(day) or not DIGEST.fullmatch(digest) or day not in dates:
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
    if (window := retry.payload_retry_window_reason()):
        emit(result="DEFERRED", reason=window)
        return 3
    lock = daily.DailyIngestLock(state / "daily-ingest.lock")
    failures = 0
    with lock:
        found = candidates_by_date(daily, retry, repo, set(dates))
        plan = []
        for day in dates:
            pointers = found.get(day) or []
            if len(pointers) != 1:
                emit(date=day, decision="refused",
                     detail="no_pending_pointer" if not pointers else "ambiguous_pending_pointers")
                failures += 1
                continue
            pointer = pointers[0]
            contract = load_pointer_observation(state, pointer)["contract"]
            decision, detail = classify(gate, contract)
            digest = str(contract.get("contract_digest") or "")
            emit(date=day, decision=decision, detail=detail, contract_digest=digest,
                 generation_id=contract.get("generation_id"),
                 observation_state=contract.get("observation_state"),
                 unverified_providers=len((contract.get("coverage") or {}).get("provider_population_unverified") or []))
            if decision == "refused":
                failures += 1
            else:
                plan.append((day, pointer, digest, decision, detail))
        if args.report:
            return 1 if failures else 0

        authorised = {day: digest for day, digest in allowed_digests.items()}
        original = gate.publication_allowed

        def scoped(contract):
            allowed, reason = original(contract)
            if allowed or reason != WAIVED or not isinstance(contract, dict):
                return allowed, reason
            day = contract.get("observation_date")
            if authorised.get(day) != contract.get("contract_digest"):
                return allowed, reason
            inner_allowed, inner = original(without_population(contract))
            return (True, "operator_waived_population:" + inner) if inner_allowed else (allowed, reason)

        gate.publication_allowed = scoped
        try:
            for day, pointer, digest, decision, detail in plan:
                if decision == "waivable" and authorised.get(day) != digest:
                    emit(date=day, result="SKIPPED", reason="digest_not_authorised")
                    failures += 1
                    continue
                outcome = daily.maybe_publish_app_payload(repo, pointer)
                emit(date=day, result=outcome, contract_digest=digest, decision=decision)
                if outcome != daily.PUBLISH_PUBLISHED:
                    failures += 1
                    continue
                daily.clear_payload_publication_pending(repo, pointer)
                if decision == "waivable":
                    receipt = {
                        "schema_version": 1, "reason": "operator_waived_population",
                        "authority": "repository owner, 2026-11-06",
                        "observation_date": day, "contract_digest": digest,
                        "generation_id": pointer.get("generation_id"),
                        "policy_without_population": detail, "pointer": pointer,
                        "published_at": datetime.now(timezone.utc).isoformat(),
                    }
                    atomic_write_json(state / "population-waiver-publications-v1" / f"{digest}.json",
                                      receipt, create_once=True)
        finally:
            gate.publication_allowed = original
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
