"""Clean real CDR run JSON into compact sector datasets for local analysis."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from cdr_ribbon_normalize import extract_product_lvr_constraints, ribbon_columns_for_bank_rate_row
NOISE_KEYS = {
    "links",
    "meta",
    "additionalinfouri",
    "applicationuri",
    "eligibilityuri",
    "feesuri",
    "overviewuri",
    "termsuri",
    "websiteuri",
}

URL_KEY_RE = re.compile(r"(uri|url|href|link)$", re.I)
URL_TEXT_RE = re.compile(r"https?://\S+", re.I)
SPACE_RE = re.compile(r"\s+")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def inner_record(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def text(value: Any) -> str:
    if value is None:
        return ""
    without_urls = URL_TEXT_RE.sub("", str(value))
    return SPACE_RE.sub(" ", without_urls).strip()


def clean_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, raw in value.items():
            lowered = str(key).lower()
            if lowered in NOISE_KEYS or URL_KEY_RE.search(str(key)):
                continue
            cleaned = clean_value(raw)
            if cleaned not in ("", None, [], {}):
                out[str(key)] = cleaned
        return out
    if isinstance(value, list):
        return [x for x in (clean_value(v) for v in value) if x not in ("", None, [], {})]
    if isinstance(value, str):
        return text(value)
    return value


def as_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, dict)]


def number_text(value: Any) -> str:
    raw = text(value)
    if not raw:
        return ""
    try:
        return f"{float(raw):.6g}"
    except ValueError:
        return raw


def rate_text(value: Any, divisor: float = 1.0) -> str:
    raw = number_text(value)
    if not raw:
        return ""
    try:
        number = float(raw)
    except ValueError:
        return raw
    if divisor != 1:
        number = number / divisor
    elif number > 1:
        number = number / 100
    return f"{number:.6g}"


def rate_divisor(items: List[Dict[str, Any]], family: str) -> float:
    values: List[float] = []
    for item in items:
        try:
            values.append(float(number_text(item.get("rate"))))
        except ValueError:
            pass
    if any(value > 1 for value in values):
        return 100
    if family == "lending" and any(0.3 < value <= 1 for value in values):
        return 10
    return 1


def normalized_rate_text(value: Any, divisor: float, family: str) -> str:
    raw = rate_text(value, divisor)
    try:
        number = float(raw)
    except ValueError:
        return raw
    if family == "lending" and 0 < number < 0.02:
        number *= 10
    return f"{number:.6g}"


def detail_json(record: Mapping[str, Any]) -> str:
    return json.dumps(clean_value(dict(record)), ensure_ascii=False, sort_keys=True)


def bank_product_key(row: Mapping[str, str]) -> str:
    parts = [
        row.get("provider", ""),
        row.get("product_id", ""),
        row.get("category", ""),
        row.get("product_name", ""),
    ]
    return "|".join(parts)


def bank_base_row(path: Path, banks_root: Path, rec: Mapping[str, Any]) -> Dict[str, str]:
    rel = path.relative_to(banks_root)
    parts = rel.parts
    dataset = parts[0] if len(parts) > 0 else ""
    provider = parts[1] if len(parts) > 1 else text(rec.get("brandName") or rec.get("brand"))
    name = text(rec.get("name") or rec.get("productName") or (parts[2] if len(parts) > 2 else ""))
    row = {
        "sector": "banks",
        "dataset": dataset,
        "provider": provider,
        "brand": text(rec.get("brand")),
        "brand_name": text(rec.get("brandName")),
        "product_id": text(rec.get("productId") or rec.get("id")),
        "product_name": name,
        "category": text(rec.get("productCategory") or rec.get("category")),
        "last_updated": text(rec.get("lastUpdated")),
        "effective_from": text(rec.get("effectiveFrom")),
        "effective_to": text(rec.get("effectiveTo")),
        "is_tailored": text(rec.get("isTailored")),
        "description": text(rec.get("description")),
        "source_file": str(path),
    }
    row["product_key"] = bank_product_key(row)
    return row


def append_bank_details(
    dataset: Dict[str, List[Dict[str, Any]]],
    base: Mapping[str, str],
    rec: Mapping[str, Any],
) -> None:
    wanted = {"Mortgage": {"lending"}, "Savings": {"deposit"}, "TD": {"deposit"}}.get(base.get("dataset", ""), {"deposit", "lending"})
    product_lvr_constraints: List[Dict[str, Any]] = []
    if base.get("dataset") == "Mortgage":
        product_lvr_constraints = [clean_value(x) for x in extract_product_lvr_constraints(rec)]
    for family, key in (("deposit", "depositRates"), ("lending", "lendingRates")):
        if family not in wanted:
            continue
        items = as_items(rec.get(key))
        divisor = rate_divisor(items, family)
        for idx, item in enumerate(items, 1):
            cleaned = clean_value(item)
            rate_row = {
                **base,
                "rate_family": family,
                "rate_index": idx,
                "rate": normalized_rate_text(item.get("rate"), divisor, family),
                "comparison_rate": normalized_rate_text(item.get("comparisonRate"), divisor, family),
                "rate_type": text(item.get("depositRateType") or item.get("lendingRateType")),
                "application_type": text(item.get("applicationType")),
                "application_frequency": text(item.get("applicationFrequency")),
                "calculation_frequency": text(item.get("calculationFrequency")),
                "repayment_type": text(item.get("repaymentType")),
                "loan_purpose": text(item.get("loanPurpose")),
                "term": text(item.get("additionalValue")),
                "details_json": "{}",
            }
            ribbons = ribbon_columns_for_bank_rate_row(
                base.get("dataset") or "",
                family,
                rate_row,
                cleaned,
                product_lvr_constraints=product_lvr_constraints if family == "lending" else None,
            )
            rate_row.update(ribbons)
            dataset["rates"].append(rate_row)

    for sheet, key, label_key in (
        ("fees", "fees", "feeType"),
        ("features", "features", "featureType"),
        ("eligibility", "eligibility", "eligibilityType"),
        ("constraints", "constraints", "constraintType"),
    ):
        for idx, item in enumerate(as_items(rec.get(key)), 1):
            cleaned = clean_value(item)
            dataset[sheet].append(
                {
                    **base,
                    "item_index": idx,
                    "item_type": text(item.get(label_key)),
                    "name": text(item.get("name") or item.get("additionalValue")),
                    "value": text(item.get("additionalValue")),
                    "details_json": json.dumps(cleaned, ensure_ascii=False, sort_keys=True),
                }
            )


def parse_banks_run(run_root: Path) -> Dict[str, Any]:
    banks_root = run_root / "banks"
    dataset: Dict[str, Any] = {
        "generated_at": utc_now(),
        "run_date": run_root.name,
        "sector": "banks",
        "products": [],
        "rates": [],
        "fees": [],
        "features": [],
        "eligibility": [],
        "constraints": [],
        "failures": read_failures(banks_root),
    }
    if not banks_root.exists():
        return dataset
    for path in sorted(banks_root.rglob("product-detail.json")):
        rec = inner_record(load_json(path))
        base = bank_base_row(path, banks_root, rec)
        dataset["products"].append({**base, "details_json": detail_json(rec)})
        append_bank_details(dataset, base, rec)
    return dataset


def read_failures(root: Path) -> List[Dict[str, Any]]:
    path = root / "failures.jsonl"
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            row = {"raw": line}
        out.append(clean_value(row))
    return out


def summary_counts(dataset: Mapping[str, Any]) -> Dict[str, int]:
    return {
        key: len(value)
        for key, value in dataset.items()
        if isinstance(value, list)
    }
