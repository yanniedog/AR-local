"""Offline acceptance harness for the dormant historical candidate corpus."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import sys
from typing import Any, Iterator, Mapping, Sequence

from cdr_historical_candidate import additions_audit, build_history
from cdr_historical_contract import (
    HistoricalContractError,
    canonical_json_bytes,
    load_strict_json,
    sha256_bytes,
    validate_contract_tree,
    validate_schema,
)
from cdr_historical_parity import (
    compare_row_multisets,
    raw_semantic_collisions,
    sqlite_rows,
    td_fallback_strata,
    text_fields_for,
    xlsx_rows,
)
from cdr_historical_source import VerifiedSnapshot, date_artifacts, open_verified_snapshot


ROOT = Path(__file__).resolve().parent
LOCK_PATH = ROOT / "contracts" / "historical" / "corpus-lock-v1.json"
COMMON_PRODUCT_FIELDS = (
    "dataset",
    "provider",
    "product_id",
    "product_key",
    "product_name",
    "category",
    "last_updated",
    "source_file",
    "details_json",
)
COMMON_RATE_FIELDS = (
    "dataset",
    "provider",
    "product_id",
    "product_key",
    "product_name",
    "rate_family",
    "rate",
    "comparison_rate",
    "rate_type",
    "application_type",
    "application_frequency",
    "repayment_type",
    "loan_purpose",
    "term",
    "ribbon_normalized",
    "security_purpose",
    "ribbon_repayment_type",
    "lvr_tier",
    "lvr_source",
    "ribbon_rate_structure",
    "ribbon_fixed_term",
    "account_type",
    "ribbon_deposit_kind",
    "balance_min",
    "balance_max",
    "term_months",
    "interest_payment",
    "feature_set",
    "taxonomy_path",
    "account_class",
    "details_json",
)


@contextmanager
def offline_network_guard() -> Iterator[None]:
    original_socket = socket.socket
    original_connection = socket.create_connection

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise HistoricalContractError("network access is forbidden by historical acceptance")

    socket.socket = blocked  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = original_socket  # type: ignore[assignment]
        socket.create_connection = original_connection  # type: ignore[assignment]


def _require_equal(result: Any, label: str, date: str) -> None:
    if not result.equal:
        raise HistoricalContractError(
            f"{date} {label} multiset mismatch: missing={result.missing}, extra={result.extra}"
        )


def _date_paths(date: str) -> dict[str, str]:
    base = f"pi/data/runs/{date}/_exports"
    return {
        "banks": f"{base}/banks-{date}.json",
        "xlsx": f"{base}/banks-{date}.xlsx",
        "sqlite": f"{base}/local-cdr.sqlite",
        "dashboard": f"{base}/dashboard-cache/{date}/banks.json",
        "done": f"pi/data/state/{date}.done.json",
    }


def _population(value: Mapping[str, Any]) -> dict[str, int]:
    declared = value.get("banks_counts") or value.get("counts")
    if isinstance(declared, Mapping) and all(
        isinstance(declared.get(key), int) for key in ("products", "rates", "failures")
    ):
        return {key: int(declared[key]) for key in ("products", "rates", "failures")}
    return {key: len(value.get(key, [])) for key in ("products", "rates", "failures")}


def _exact_done_population(snapshot: VerifiedSnapshot, date: str) -> dict[str, int]:
    marker = snapshot.read_json(_date_paths(date)["done"])
    counts = marker.get("banks") if isinstance(marker, Mapping) else None
    if not isinstance(counts, Mapping):
        raise HistoricalContractError(f"{date} completion marker lacks bank counts")
    result = {key: counts.get(key) for key in ("products", "rates", "failures")}
    if not all(isinstance(value, int) and value >= 0 for value in result.values()):
        raise HistoricalContractError(f"{date} completion marker counts are not exact")
    return result  # type: ignore[return-value]


def _sqlite_parity(snapshot: VerifiedSnapshot, date: str, banks: Mapping[str, Any]) -> None:
    connection = snapshot.connect_sqlite(_date_paths(date)["sqlite"])
    try:
        products = list(sqlite_rows(connection, "bank_products"))
        rates = list(sqlite_rows(connection, "bank_rates"))
    finally:
        connection.close()
    _require_equal(
        compare_row_multisets(
            banks["products"],
            products,
            fields=COMMON_PRODUCT_FIELDS,
            text_fields=text_fields_for(banks["products"], COMMON_PRODUCT_FIELDS),
        ),
        "banks/SQLite products",
        date,
    )
    _require_equal(
        compare_row_multisets(
            banks["rates"],
            rates,
            fields=COMMON_RATE_FIELDS,
            text_fields=text_fields_for(banks["rates"], COMMON_RATE_FIELDS),
        ),
        "banks/SQLite rates",
        date,
    )


def _xlsx_parity(snapshot: VerifiedSnapshot, date: str, banks: Mapping[str, Any]) -> None:
    path = snapshot.path(_date_paths(date)["xlsx"])
    product_fields = tuple(banks["products"][0]) if banks["products"] else ()
    rate_fields = tuple(banks["rates"][0]) if banks["rates"] else ()
    _require_equal(
        compare_row_multisets(
            banks["products"],
            xlsx_rows(path, "products"),
            text_fields=text_fields_for(banks["products"], product_fields),
        ),
        "banks/XLSX products",
        date,
    )
    _require_equal(
        compare_row_multisets(
            banks["rates"],
            xlsx_rows(path, "rates"),
            text_fields=text_fields_for(banks["rates"], rate_fields),
        ),
        "banks/XLSX rates",
        date,
    )


def _dashboard_parity(
    snapshot: VerifiedSnapshot, date: str, banks: Mapping[str, Any]
) -> tuple[Mapping[str, Any], dict[str, int], bool]:
    dashboard = snapshot.read_json(_date_paths(date)["dashboard"])
    counts = _population(dashboard)
    product_result = compare_row_multisets(banks["products"], dashboard["products"])
    rate_result = compare_row_multisets(banks["rates"], dashboard["rates"])
    equal = product_result.equal and rate_result.equal
    if date != "2026-05-19" and not equal:
        raise HistoricalContractError(f"unexpected semantic projection variant: {date}")
    if date == "2026-05-19" and equal:
        raise HistoricalContractError("2026-05-19 parallel projection disappeared")
    return dashboard, counts, equal


def _backup_variants(snapshot: VerifiedSnapshot, date: str) -> tuple[str, ...]:
    prefix = f"pi/data/runs/{date}/_exports/banks-{date}.json.bak-"
    return tuple(sorted(path for path in snapshot.inventory if path.startswith(prefix)))


def _assert_variant_inventory(
    snapshot: VerifiedSnapshot,
    date: str,
    banks: Mapping[str, Any],
) -> None:
    backups = _backup_variants(snapshot, date)
    expected = 1 if date in {"2026-05-20", "2026-05-26"} else 0
    if len(backups) != expected:
        raise HistoricalContractError(f"unexpected backup variant population on {date}")
    for path in backups:
        backup = snapshot.read_json(path)
        same = all(
            compare_row_multisets(banks[key], backup[key]).equal for key in ("products", "rates")
        )
        if same:
            raise HistoricalContractError(f"recorded correction is not a semantic variant: {date}")


def check_date(snapshot: VerifiedSnapshot, date: str, *, deep: bool) -> dict[str, Any]:
    paths = _date_paths(date)
    banks = snapshot.read_json(paths["banks"])
    if not isinstance(banks, Mapping):
        raise HistoricalContractError(f"{date} banks export is not an object")
    population = _population(banks)
    if population != _exact_done_population(snapshot, date):
        raise HistoricalContractError(f"{date} banks/done population mismatch")
    dashboard, dashboard_counts, dashboard_equal = _dashboard_parity(snapshot, date, banks)
    _assert_variant_inventory(snapshot, date, banks)
    if deep:
        _xlsx_parity(snapshot, date, banks)
        _sqlite_parity(snapshot, date, dashboard if date == "2026-05-19" else banks)
    collisions = raw_semantic_collisions(banks["products"], banks["rates"])
    terms = td_fallback_strata(banks["rates"])
    return {
        "date": date,
        "source_manifest_checkpoint": sha256_bytes(
            canonical_json_bytes(
                [
                    {"path": item.path, "bytes": item.bytes, "sha256": item.sha256}
                    for item in sorted(
                        (
                            entry
                            for entry in snapshot.inventory.values()
                            if entry.kind == "file" and f"/{date}/" in entry.path
                        ),
                        key=lambda item: item.path,
                    )
                ]
            )
        ),
        "population": population,
        "dashboard_population": dashboard_counts,
        "dashboard_equal": dashboard_equal,
        "semantic_collision_groups": collisions.conflicting_groups,
        "semantic_collision_rows": collisions.conflicting_rows,
        "semantic_duplicate_same_value_groups": collisions.duplicate_same_value_groups,
        "semantic_duplicate_same_value_rows": collisions.duplicate_same_value_rows,
        "semantic_nonunique_rows": collisions.nonunique_rows,
        "semantic_collision_records": collisions.records,
        "td_terms": dict(terms),
    }


def _sum(results: Sequence[Mapping[str, Any]], key: str) -> int:
    return sum(int(result["population"][key]) for result in results)


def _semantic_totals(results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "semantic_collision_groups": sum(int(item["semantic_collision_groups"]) for item in results),
        "semantic_collision_rows": sum(int(item["semantic_collision_rows"]) for item in results),
        "semantic_duplicate_same_value_groups": sum(
            int(item["semantic_duplicate_same_value_groups"]) for item in results
        ),
        "semantic_duplicate_same_value_rows": sum(
            int(item["semantic_duplicate_same_value_rows"]) for item in results
        ),
        "semantic_nonunique_rows": sum(int(item["semantic_nonunique_rows"]) for item in results),
        "td_exact_iso": sum(int(item["td_terms"].get("exact_iso", 0)) for item in results),
        "td_structured_range": sum(int(item["td_terms"].get("structured_range", 0)) for item in results),
        "td_text_derived": sum(int(item["td_terms"].get("text_derived", 0)) for item in results),
        "td_no_evidence_terms": sum(int(item["td_terms"].get("no_evidence", 0)) for item in results),
    }


def _source_verification(
    snapshot: VerifiedSnapshot,
    lock: Mapping[str, Any],
    audit: Any | None,
) -> dict[str, Any]:
    def finding_records(value: Any | None) -> list[dict[str, Any]]:
        if value is None:
            return []
        return [
            {
                "path": item.path,
                "expected_bytes": item.expected_bytes,
                "actual_bytes": item.actual_bytes,
                "expected_sha256": item.expected_sha256,
                "actual_sha256": item.actual_sha256,
                "source_role": item.source_role,
            }
            for item in value.findings
        ]

    findings = finding_records(audit)
    candidate_inputs_verified = audit is not None and not any(
        item["source_role"] == "immutable_candidate_input" for item in findings
    )
    return {
        "manifests_verified_before_source_reads": True,
        "preservation_inventory_population": {
            "files": len(snapshot.critical),
            "bytes": sum(item.bytes for item in snapshot.critical.values()),
        },
        "candidate_input_population": dict(lock["candidate_input_population"]),
        "transient_evidence_population": {
            key: value
            for key, value in lock["transient_evidence_population"].items()
            if key not in {"candidate_input", "reason"}
        },
        "full_rehash": audit is not None,
        "rehash": {
            "state": (
                "not_run"
                if audit is None
                else "drift_detected" if findings else "verified"
            ),
            "checked_files": 0 if audit is None else audit.checked_files,
            "checked_bytes": 0 if audit is None else audit.checked_bytes,
            "verified_files": 0 if audit is None else audit.verified_files,
            "verified_bytes": 0 if audit is None else audit.verified_bytes,
            "candidate_inputs_verified": candidate_inputs_verified,
        },
        "preservation_drift": findings,
    }


def _candidate_input_paths(
    snapshot: VerifiedSnapshot, lock: Mapping[str, Any]
) -> tuple[str, ...]:
    artifacts = {
        item.path: item
        for date in snapshot.dates
        for item in date_artifacts(snapshot, date)
    }
    population = {
        "files": len(artifacts),
        "bytes": sum(item.bytes for item in artifacts.values()),
    }
    if population != lock["candidate_input_population"]:
        raise HistoricalContractError(
            f"candidate input population differs from corpus lock: {population!r}"
        )
    return tuple(sorted(artifacts))


def _blocked_drift_report(
    snapshot: VerifiedSnapshot,
    source: Mapping[str, Any],
    *,
    candidate_build_started: bool,
) -> dict[str, Any]:
    return validate_schema(
        "acceptance_report",
        {
            "schema_version": 1,
            "contract": "legacy-historical-acceptance-v1",
            "status": "BLOCKED_PRESERVATION_DRIFT",
            "snapshot_id": snapshot.snapshot_id,
            "source": dict(source),
            "history": {
                "state": (
                    "discarded_due_to_final_preservation_drift"
                    if candidate_build_started
                    else "not_run_due_to_preservation_drift"
                )
            },
            "parity": {
                "state": (
                    "discarded_due_to_final_preservation_drift"
                    if candidate_build_started
                    else "not_run_due_to_preservation_drift"
                )
            },
            "safety": {
                "network_blocked": True,
                "candidate_build_started": candidate_build_started,
                "candidate_output_written": False,
            },
            "promotion_eligible": False,
            "blockers": [
                "the preservation snapshot differs from its locked byte inventory",
                "candidate acceptance and publication remain forbidden",
            ],
        },
    )


def run_acceptance(
    snapshot_root: Path,
    *,
    tool_commit: str,
    deep: bool = False,
    full_rehash: bool = False,
    reverse_discovery: bool = False,
) -> dict[str, Any]:
    lock = validate_contract_tree()
    with offline_network_guard():
        snapshot = open_verified_snapshot(snapshot_root)
        candidate_inputs = _candidate_input_paths(snapshot, lock)
        rehash_audit = None
        if full_rehash:
            rehash_paths = set(snapshot.critical) | set(candidate_inputs)
            rehash_audit = snapshot.audit_rehash(
                rehash_paths,
                candidate_inputs=candidate_inputs,
            )
        source = _source_verification(snapshot, lock, rehash_audit)
        if source["preservation_drift"]:
            return _blocked_drift_report(
                snapshot,
                source,
                candidate_build_started=False,
            )
        discovered = reversed(snapshot.dates) if reverse_discovery else snapshot.dates
        by_date = {date: check_date(snapshot, date, deep=deep) for date in discovered}
        results = [by_date[date] for date in sorted(by_date)]
        history = build_history(snapshot, tool_commit=tool_commit)
    populations = {key: _sum(results, key) for key in ("products", "rates", "failures")}
    if populations != {
        key: lock["critical_population"][key] for key in ("products", "rates", "failures")
    }:
        raise HistoricalContractError("full retained row population differs from corpus lock")
    semantics = _semantic_totals(results)
    expected_semantics = {
        "semantic_collision_groups": lock["quarantine"]["semantic_collision_groups"],
        "semantic_collision_rows": lock["quarantine"]["semantic_collision_rows"],
        "semantic_duplicate_same_value_groups": lock["quarantine"]["semantic_duplicate_same_value_groups"],
        "semantic_duplicate_same_value_rows": lock["quarantine"]["semantic_duplicate_same_value_rows"],
        "semantic_nonunique_rows": lock["quarantine"]["semantic_nonunique_rows"],
        "td_exact_iso": 552,
        "td_structured_range": 1564,
        "td_text_derived": 5796,
        "td_no_evidence_terms": lock["quarantine"]["td_no_evidence_terms"],
    }
    if semantics != expected_semantics:
        raise HistoricalContractError(
            f"semantic quarantine totals differ from corpus lock: {semantics!r}"
        )
    audit = additions_audit(snapshot)
    expected_audit = lock["additive_ledger_audit"]
    if audit["changed_dates"] != expected_audit["changed_dates"] or audit[
        "original_population"
    ] != {"files": expected_audit["original_files"], "bytes": expected_audit["original_bytes"]} or audit[
        "addition_population"
    ] != {"files": expected_audit["addition_files"], "bytes": expected_audit["addition_bytes"]}:
        raise HistoricalContractError("additive-ledger populations differ from corpus lock")
    index = json.loads(history.index)
    if full_rehash:
        final_audit = snapshot.audit_rehash(
            rehash_paths,
            candidate_inputs=candidate_inputs,
        )
        source = _source_verification(snapshot, lock, final_audit)
        if source["preservation_drift"]:
            return _blocked_drift_report(
                snapshot,
                source,
                candidate_build_started=True,
            )
    report = {
        "schema_version": 1,
        "contract": "legacy-historical-acceptance-v1",
        "status": (
            "accepted_partial_non_promotable"
            if full_rehash
            else "unverified_partial_non_promotable"
        ),
        "snapshot_id": snapshot.snapshot_id,
        "source": source,
        "history": {
            "retained_dates": len(results),
            "gap_entries": len(index["gaps"]),
            "candidate_count": index["candidate_count"],
            "legacy_ledger_records": 93,
            "legacy_ledger_role_difference_recorded": True,
        },
        "parity": {
            **populations,
            **semantics,
            "may_19_variants": [
                result
                for result in results
                if result["date"] == "2026-05-19"
            ][0]["dashboard_population"],
            "additions": audit,
            "deep_cross_format": deep,
        },
        "safety": {
            "network_blocked": True,
            "max_workers": 1,
            "streamed_one_date_at_a_time": True,
            "source_manifest_checkpoints": len(results),
            "deterministic_discovery_order": True,
        },
        "promotion_eligible": False,
        "blockers": [
            "every retained observation is partial",
            "register, provider, and attempt populations are unavailable",
            "ambiguous semantic rows remain quarantined",
            "two observation gaps are irreparable",
            "this dormant contract has no publisher or operational latest update",
        ],
    }
    return validate_schema("acceptance_report", report)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verify", choices=("verify",))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--tool-commit", required=True)
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--full-rehash", action="store_true")
    args = parser.parse_args(argv)
    report = run_acceptance(
        args.snapshot,
        tool_commit=args.tool_commit,
        deep=args.deep,
        full_rehash=args.full_rehash,
    )
    sys.stdout.buffer.write(canonical_json_bytes(report))
    return 0 if report["status"] == "accepted_partial_non_promotable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
