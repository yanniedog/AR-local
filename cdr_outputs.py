"""Build one canonical observation, one safe database, and optional XLSX."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from cdr_clean_export import parse_banks_run
from cdr_observation import build_observation, build_projections, write_observation
from cdr_observation_db import build_observation_database
from cdr_product_accounting import validate_product_accounting
from cdr_product_change_runs import iter_run_fact_groups, previous_finalized_run
from cdr_product_changes import diff_normalized_product_fact_groups
from cdr_product_facts import NORMALIZATION_VERSION
from cdr_product_inventory import build_product_inventory
from cdr_taxonomy import build_taxonomy_summary
from cdr_xlsx import write_workbook


def product_change_rows(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for event in report.get("events") or []:
        if not isinstance(event, Mapping):
            continue
        rows.append(
            {
                "run_date": report.get("run_date") or report.get("current_run_date"),
                "previous_run_date": report.get("previous_run_date"),
                "event_id": event.get("event_id"),
                "dataset": event.get("dataset"),
                "provider": event.get("provider"),
                "product_id": event.get("product_id"),
                "product_name": event.get("product_name"),
                "event_type": event.get("event_type"),
                "canonical_key": event.get("canonical_key"),
                "kind": event.get("kind"),
                "materiality": event.get("materiality"),
                "equivalence": event.get("equivalence"),
                "review_required": int(bool(event.get("review_required"))),
                "cosmetic": int(bool(event.get("cosmetic"))),
                "material": int(bool(event.get("material"))),
                "slots_changed": int(bool(event.get("slots_changed"))),
                "reasons_json": json.dumps(event.get("reasons") or [], ensure_ascii=False, sort_keys=True),
                "before_json": json.dumps(event.get("before"), ensure_ascii=False, sort_keys=True),
                "after_json": json.dumps(event.get("after"), ensure_ascii=False, sort_keys=True),
                **{
                    key: event.get(key)
                    for key in (
                        "before_value_json", "after_value_json", "before_evidence_json",
                        "after_evidence_json", "before_signature_json", "after_signature_json",
                    )
                },
            }
        )
    return rows


def _exclude_failed_missing_product_groups(
    previous_groups: Iterable[Tuple[Tuple[str, str, str], List[Dict[str, Any]]]],
    current_facts: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> tuple[Iterable[Tuple[Tuple[str, str, str], List[Dict[str, Any]]]], Dict[str, int]]:
    """Do not turn a failed fetch into a false product-removal event."""

    current = {
        (str(row.get("provider") or "").casefold(), str(row.get("product_id") or ""), str(row.get("dataset") or ""))
        for row in current_facts
    }
    failed_providers = {
        str(row.get("bank") or "").casefold()
        for row in failures
        if str(row.get("phase") or "") in {"products_index", "holder"}
    }
    failed_products = {
        (str(row.get("bank") or "").casefold(), str(row.get("product_id") or ""))
        for row in failures
        if str(row.get("phase") or "") == "product_detail" and row.get("product_id")
    }
    result = {"suppressed": 0}

    def filtered() -> Iterable[Tuple[Tuple[str, str, str], List[Dict[str, Any]]]]:
        for key, facts in previous_groups:
            identity = (key[0].casefold(), key[1], key[2])
            failed = identity[0] in failed_providers or identity[:2] in failed_products
            if failed and identity not in current:
                result["suppressed"] += 1
                continue
            yield key, facts

    return filtered(), result


def _product_changes(
    run_root: Path,
    banks: Mapping[str, Any],
    previous_run_root: Optional[Path],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    previous = previous_run_root or previous_finalized_run(run_root)
    if previous is None:
        return [], {
            "schema_version": 1,
            "normalization_version": NORMALIZATION_VERSION,
            "previous_run_date": None,
            "run_date": run_root.name,
            "change_count": 0,
            "products": {"previous": 0, "current": len(banks["products"]), "joined": 0},
            "suppressed_incomplete_products": 0,
        }
    previous_groups, suppression = _exclude_failed_missing_product_groups(
        iter_run_fact_groups(previous), banks["product_facts"], banks["failures"]
    )
    report = diff_normalized_product_fact_groups(
        previous_groups,
        banks["product_facts"],
        previous_run_date=previous.name,
        current_run_date=run_root.name,
    )
    report["suppressed_incomplete_products"] = suppression["suppressed"]
    summary = {
        key: report.get(key)
        for key in (
            "schema_version", "normalization_version", "previous_run_date", "run_date",
            "change_count", "products", "suppressed_incomplete_products",
        )
    }
    return product_change_rows(report), summary


def _write_workbook(path: Path, observation: Mapping[str, Any], accounting: Mapping[str, Any]) -> None:
    products = [row["document"] for row in observation["products"]]
    rates = [row["document"] for row in observation["rates"]]
    items = list(observation["items"])
    write_workbook(
        path,
        {
            "taxonomy": build_taxonomy_summary(rates),
            "products": products,
            "rates": rates,
            **{
                group: [row["document"] for row in items if row["item_group"] == group]
                for group in ("fees", "features", "eligibility", "constraints")
            },
            "product_facts": [row["document"] for row in observation["product_facts"]],
            "product_changes": [row["document"] for row in observation["product_changes"]],
            "product_accounting": list(accounting["products"]),
            "issues": list(accounting["issues"]),
        },
    )


def build_outputs(
    run_root: Path,
    out_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    previous_run_root: Optional[Path] = None,
    *,
    write_xlsx: bool = False,
) -> Dict[str, Any]:
    run_root = run_root.expanduser().resolve()
    out_dir = (out_dir or (run_root / "_exports")).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    banks = parse_banks_run(run_root)
    changes, change_summary = _product_changes(run_root, banks, previous_run_root)
    banks["product_changes"] = changes
    banks["product_change_summary"] = change_summary
    accounting, observed_at, blockers = build_product_inventory(run_root, banks)
    validate_product_accounting(accounting)
    projections = build_projections(banks, accounting)
    observation = build_observation(
        accounting=accounting,
        projections=projections,
        observed_at=observed_at,
        normalization_version=NORMALIZATION_VERSION,
        blockers=blockers,
    )
    write_observation(out_dir, observation, accounting)
    database = db_path.expanduser().resolve() if db_path else out_dir / "local-cdr.sqlite"
    db_result = build_observation_database(
        database,
        accounting=accounting,
        projections=projections,
        generated_at=observed_at,
        normalization_version=NORMALIZATION_VERSION,
    )
    if write_xlsx:
        _write_workbook(out_dir / f"banks-{run_root.name}.xlsx", observation, accounting)
    return {
        "contract": "observation-v1",
        "run_date": run_root.name,
        "out_dir": str(out_dir),
        "observation_state": observation["state"],
        "banks": observation["row_counts"],
        "accounting": accounting["summary"],
        "database_sha256": db_result.verification.database_sha256,
        "xlsx": write_xlsx,
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--xlsx", action="store_true", help="also write the optional review workbook")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    print(
        json.dumps(
            build_outputs(args.run_root, args.out, args.db, write_xlsx=args.xlsx),
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
