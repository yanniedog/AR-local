"""Build the optional variable-mortgage versus at-call-savings history asset."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional


_ROUND = 6
_CONDITIONAL = ("bonus", "intro", "honeymoon", "conditional", "promotional")
_TERM_DEPOSIT = ("term deposit", "fixed term deposit")


def _text(row: Mapping[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip().lower()


def _is_standard(row: Mapping[str, Any]) -> bool:
    return _text(row, "account_class") == "standard"


def _mortgage_member(row: Mapping[str, Any]) -> bool:
    return (
        row.get("dataset") == "Mortgage"
        and _text(row, "rate_family") == "lending"
        and _is_standard(row)
        and _text(row, "security_purpose") == "owner_occupied"
        and _text(row, "ribbon_repayment_type") == "principal_and_interest"
        and _text(row, "ribbon_rate_structure") == "variable"
    )


def _savings_member(row: Mapping[str, Any]) -> bool:
    if row.get("dataset") != "Savings" or _text(row, "rate_family") != "deposit":
        return False
    if not _is_standard(row):
        return False
    product_name = _text(row, "product_name")
    if product_name.startswith(_TERM_DEPOSIT) or "term_deposit" in _text(row, "taxonomy_path"):
        return False
    kind = " ".join(
        _text(row, field)
        for field in ("ribbon_deposit_kind", "rate_type", "ribbon_rate_structure")
    )
    if any(token in kind for token in _CONDITIONAL):
        return False
    return _text(row, "ribbon_deposit_kind") in ("base", "ongoing")


def _rate(row: Mapping[str, Any]) -> Optional[float]:
    try:
        value = float(row.get("rate"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value / 100 if value >= 1 else value


def _membership_hash(keys: Iterable[str]) -> str:
    material = "\n".join(sorted(set(keys))).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16] if material else ""


def _provider_cohort(rows: Iterable[Mapping[str, Any]], predicate: Callable[[Mapping[str, Any]], bool]):
    by_provider: Dict[str, Dict[str, list[float]]] = {}
    for row in rows:
        if not predicate(row):
            continue
        value = _rate(row)
        provider = str(row.get("provider") or "").strip()
        product_key = str(row.get("product_key") or row.get("product_id") or "").strip()
        if value is None or not provider or not product_key:
            continue
        by_provider.setdefault(provider, {}).setdefault(product_key, []).append(value)
    result = {}
    for provider, products in by_provider.items():
        product_means = [sum(values) / len(values) for values in products.values() if values]
        if product_means:
            result[provider] = {
                "mean": round(sum(product_means) / len(product_means), _ROUND),
                "count": len(product_means),
                "hash": _membership_hash(products),
            }
    return result


def build_bank_spread_history(
    exports_dir: Path,
    *,
    run_date: str,
    history_dates: Callable[[Path, str], list[str]],
    banks_path: Callable[[Path, str], Optional[Path]],
    load_json: Callable[[Path], Any],
    schema_version: int = 1,
) -> Dict[str, Any]:
    """Create daily, provider-weighted cohort means from retained real snapshots."""
    dates = history_dates(exports_dir, run_date)
    day_values: list[Dict[str, Dict[str, Dict[str, Any]]]] = []
    providers: set[str] = set()
    for day in dates:
        path = banks_path(exports_dir, day)
        rates = [] if path is None else [
            row for row in (load_json(path).get("rates") or []) if isinstance(row, dict)
        ]
        cohorts = {
            "mortgage": _provider_cohort(rates, _mortgage_member),
            "savings": _provider_cohort(rates, _savings_member),
        }
        providers.update(cohorts["mortgage"])
        providers.update(cohorts["savings"])
        day_values.append(cohorts)

    banks: Dict[str, Dict[str, list[Any]]] = {}
    for provider in sorted(providers):
        series = {
            "mortgage_mean": [], "savings_mean": [], "gap": [],
            "mortgage_count": [], "savings_count": [],
            "mortgage_hash": [], "savings_hash": [], "quality": [],
        }
        for cohorts in day_values:
            mortgage = cohorts["mortgage"].get(provider)
            savings = cohorts["savings"].get(provider)
            series["mortgage_mean"].append(mortgage["mean"] if mortgage else None)
            series["savings_mean"].append(savings["mean"] if savings else None)
            series["gap"].append(
                round(mortgage["mean"] - savings["mean"], _ROUND)
                if mortgage and savings else None
            )
            series["mortgage_count"].append(mortgage["count"] if mortgage else 0)
            series["savings_count"].append(savings["count"] if savings else 0)
            series["mortgage_hash"].append(mortgage["hash"] if mortgage else "")
            series["savings_hash"].append(savings["hash"] if savings else "")
            series["quality"].append(
                "complete" if mortgage and savings else
                "missing_savings" if mortgage else
                "missing_mortgage" if savings else "missing_both"
            )
        banks[provider] = series

    return {
        "schema_version": schema_version,
        "run_date": run_date,
        "run_dates": dates,
        "method": "mean_rate_rows_per_product_then_mean_products_per_provider",
        "cohorts": {
            "mortgage": "standard variable owner-occupied principal-and-interest, including offset products",
            "savings": "standard base or ongoing at-call savings; bonus, introductory, conditional and term deposits excluded",
        },
        "banks": banks,
    }
