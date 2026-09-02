"""Clean real CDR run JSON into compact sector datasets for local analysis."""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlsplit

from cdr_contracts import parse_rate_string, product_uid, provider_uid
from cdr_ribbon_normalize import extract_product_lvr_constraints, ribbon_columns_for_bank_rate_row
from cdr_product_facts import clean_fact_rows
from cdr_rate_normalize import normalized_rate_value, rate_divisor
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
SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|password|secret|signature|token|api[_-]?key|"
    r"request[_-]?headers?|response[_-]?body|exception|traceback)", re.I
)
SPACE_RE = re.compile(r"\s+")
OFFICIAL_PRODUCT_LINK_FIELDS = (
    "overviewUri",
    "eligibilityUri",
    "feesAndPricingUri",
    "termsUri",
    "bundleUri",
)


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
            if (
                lowered in NOISE_KEYS
                or URL_KEY_RE.search(str(key))
                or SENSITIVE_KEY_RE.search(str(key))
            ):
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
    del divisor
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    return parse_rate_string(value)


def normalized_rate_text(value: Any, divisor: float, family: str) -> str:
    del divisor, family
    return rate_text(value)


def _official_https_url(value: Any) -> str:
    """Return a source-supplied public HTTPS URL, excluding credentials/fragments."""
    raw = str(value or "").strip()
    if not raw or len(raw) > 2048:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return raw.split("#", 1)[0]


def official_product_links(record: Mapping[str, Any]) -> Dict[str, str]:
    """Allowlisted lender links from CDR ``additionalInformation`` metadata."""
    info = record.get("additionalInformation")
    if not isinstance(info, Mapping):
        return {}
    return {
        field: url
        for field in OFFICIAL_PRODUCT_LINK_FIELDS
        if (url := _official_https_url(info.get(field)))
    }


def detail_json(record: Mapping[str, Any]) -> str:
    cleaned = clean_value(dict(record))
    links = official_product_links(record)
    if links:
        # Generic cleaning intentionally removes arbitrary URLs. Restore only the
        # CDR-defined lender metadata fields that the app can identify and label.
        cleaned["additionalInformation"] = links
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)


def _failure_rollup(failures: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str, str], int] = {}
    for item in failures:
        provider = text(item.get("bank")) or "Unknown"
        phase = text(item.get("phase")) or "unknown"
        status = text(item.get("status")) or "unknown"
        key = (provider, phase, status)
        grouped[key] = grouped.get(key, 0) + 1
    return [
        {"provider": provider, "phase": phase, "status": status, "count": count}
        for (provider, phase, status), count in sorted(grouped.items())
    ]


def app_coverage_aliases(coverage: Mapping[str, Any]) -> Dict[str, Any]:
    """Add the legacy app-facing names without replacing the canonical contract."""
    result = dict(coverage)
    observed_on = text(result.get("observed_on"))
    counts = result.get("counts") if isinstance(result.get("counts"), Mapping) else {}
    provider_failures = (
        result.get("provider_failures")
        if isinstance(result.get("provider_failures"), list)
        else []
    )
    succeeded = int(counts.get("providers_succeeded") or counts.get("brands_observed") or 0)
    attempted = int(
        counts.get("providers_attempted")
        or (succeeded + int(counts.get("providers_failed") or 0))
    )
    observed_at = ""
    if observed_on:
        observed_at = (
            datetime.strptime(observed_on, "%Y-%m-%d")
            .replace(tzinfo=timezone(timedelta(hours=10)))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    result.setdefault("observed_at", observed_at)
    result.setdefault("providers_succeeded", succeeded)
    result.setdefault("providers_attempted", attempted)
    result.setdefault("failures", list(provider_failures))
    return result


def coverage_summary(banks: Mapping[str, Any], run_date: str) -> Dict[str, Any]:
    """Privacy-safe measured coverage and failure provenance for app clients."""
    rates = [row for row in banks.get("rates", []) if isinstance(row, Mapping)]
    products = [row for row in banks.get("products", []) if isinstance(row, Mapping)]
    failures = [row for row in banks.get("failures", []) if isinstance(row, Mapping)]
    observed = {text(row.get("provider")) for row in [*rates, *products]} - {""}
    failed = {text(row.get("bank")) for row in failures} - {""}
    attempted = {
        text(provider) for provider in banks.get("holder_attempts", []) if text(provider)
    } | observed | failed
    succeeded = attempted - (failed - observed)
    sections: Dict[str, Any] = {}
    for section in ("Mortgage", "Savings", "TD"):
        section_rates = [row for row in rates if row.get("dataset") == section]
        sections[section] = {
            "rates": len(section_rates),
            "products": len({text(row.get("product_key")) for row in section_rates} - {""}),
            "providers": len({text(row.get("provider")) for row in section_rates} - {""}),
            "standard_rates": sum(row.get("account_class") == "standard" for row in section_rates),
            "non_standard_rates": sum(
                row.get("account_class") == "non_standard" for row in section_rates
            ),
            "unclassified_rates": sum(
                row.get("account_class") not in ("standard", "non_standard")
                for row in section_rates
            ),
        }
    return app_coverage_aliases({
        "schema_version": 1,
        "observed_on": run_date,
        "source": "consumer_data_right_export",
        "failure_provenance_complete": True,
        "counts": {
            "brands_observed": len(observed),
            "products": len(products),
            "rates": len(rates),
            "failure_records": len(failures),
            "providers_failed": len(failed - observed),
            "providers_partial": len(failed & observed),
            "providers_attempted": len(attempted),
            "providers_succeeded": len(succeeded),
        },
        "sections": sections,
        # Deliberately excludes endpoint URLs and response snippets.
        "provider_failures": _failure_rollup(failures),
    })


def bank_product_key(row: Mapping[str, str]) -> str:
    parts = [
        row.get("provider", ""),
        row.get("product_id", ""),
        row.get("category", ""),
        row.get("product_name", ""),
    ]
    return "|".join(parts)


def bank_base_row(
    path: Path,
    banks_root: Path,
    rec: Mapping[str, Any],
    provider_record: Mapping[str, Any],
) -> Dict[str, Any]:
    rel = path.relative_to(banks_root)
    parts = rel.parts
    dataset = parts[0] if len(parts) > 0 else ""
    provider = parts[1] if len(parts) > 1 else text(rec.get("brandName") or rec.get("brand"))
    name = text(rec.get("name") or rec.get("productName") or (parts[2] if len(parts) > 2 else ""))
    cdr_product_id = text(rec.get("productId") or rec.get("id"))
    stable_provider_uid = str(provider_record.get("provider_uid") or "")
    if not stable_provider_uid or not cdr_product_id:
        raise ValueError("product identity evidence is incomplete")
    row = {
        "sector": "banks",
        "dataset": dataset,
        "provider": provider,
        "brand": text(rec.get("brand")),
        "brand_name": text(rec.get("brandName")),
        "provider_uid": stable_provider_uid,
        "provider_identity_status": str(provider_record.get("provider_identity_status") or ""),
        "product_id": cdr_product_id,
        "product_name": name,
        "category": text(rec.get("productCategory") or rec.get("category")),
        "last_updated": text(rec.get("lastUpdated")),
        "effective_from": text(rec.get("effectiveFrom")),
        "effective_to": text(rec.get("effectiveTo")),
        "is_tailored": text(rec.get("isTailored")),
        "description": text(rec.get("description")),
        "source_file": rel.as_posix(),
        "evidence_id": hashlib.sha256(path.read_bytes()).hexdigest(),
        "details_complete": True,
    }
    row["product_key"] = bank_product_key(row)
    row["legacy_product_key"] = row["product_key"]
    row["product_uid"] = product_uid(stable_provider_uid, dataset, cdr_product_id)
    return row


def _provider_records(holders_root: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    if not holders_root.is_dir():
        return records
    for holder in sorted(path for path in holders_root.iterdir() if path.is_dir()):
        try:
            record = load_json(holder / "_register-brand.json")
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, Mapping):
            continue
        normalized = dict(record)
        if not normalized.get("provider_uid"):
            try:
                uid, status = provider_uid(
                    data_holder_id=normalized.get("data_holder_id"),
                    data_holder_brand_id=normalized.get("data_holder_brand_id"),
                    interim_id=normalized.get("interim_id"),
                    endpoint_urls=(str(normalized.get("endpoint_url") or ""),),
                    display_name=str(
                        normalized.get("brand_name")
                        or normalized.get("legal_entity_name")
                        or holder.name
                    ),
                )
            except ValueError:
                continue
            normalized["provider_uid"] = uid
            normalized["provider_identity_status"] = status
        summary_path = holder / "_products-index" / "index-summary.json"
        try:
            summary = load_json(summary_path)
        except (OSError, json.JSONDecodeError):
            summary = None
        if isinstance(summary, Mapping):
            normalized["population"] = dict(summary)
        records[holder.name] = normalized
    return records


def _validate_core_rates(record: Mapping[str, Any], dataset: str) -> None:
    wanted = {"Mortgage": ("lendingRates",), "Savings": ("depositRates",), "TD": ("depositRates",)}.get(
        dataset,
        (),
    )
    for key in wanted:
        raw = record.get(key)
        if raw is None:
            continue
        if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
            raise ValueError(f"{key} must be an array of objects")
        for item in raw:
            parse_rate_string(item.get("rate"))
            comparison = item.get("comparisonRate")
            if comparison not in (None, ""):
                parse_rate_string(comparison)


def _invalid_detail_arrays(record: Mapping[str, Any]) -> list[str]:
    invalid = []
    for key in ("fees", "features", "eligibility", "constraints"):
        if key not in record:
            continue
        raw = record[key]
        if not isinstance(raw, list) or any(
            not isinstance(item, Mapping) for item in raw
        ):
            invalid.append(key)
    return invalid


def _validate_rate_facts(rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        if row.get("value_type") != "rate":
            continue
        number = row.get("value_number")
        if number is None:
            continue
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not 0 <= number <= 1
        ):
            raise ValueError("rate fact must contain a decimal fraction from 0 to 1")


def bank_detail_item_value(sheet: str, item: Mapping[str, Any]) -> Any:
    """Choose a useful flat-export value while details_json stays lossless."""
    def present(raw: Any) -> bool:
        return raw is not None and not (
            isinstance(raw, str) and raw.strip().lower() in {"", "null"}
        )

    value = item.get("additionalValue")
    if present(value) or sheet != "fees":
        return value
    method = text(item.get("feeMethodUType")).lower()
    fee_type = text(item.get("feeType")).upper()
    variable = item.get("variable")
    if method == "variable" or fee_type == "VARIABLE":
        if isinstance(variable, Mapping):
            minimum = variable.get("feeMinimum")
            maximum = variable.get("feeMaximum")
            low = text(minimum) if present(minimum) else ""
            high = text(maximum) if present(maximum) else ""
            if low or high:
                return f"{low}..{high}"
        return "VARIABLE"
    amount = item.get("amount")
    if present(amount):
        return amount
    fixed_amount = item.get("fixedAmount")
    if isinstance(fixed_amount, Mapping) and present(fixed_amount.get("amount")):
        return fixed_amount.get("amount")
    rate_based = item.get("rateBased")
    if isinstance(rate_based, Mapping) and present(rate_based.get("rate")):
        return rate_based.get("rate")
    for key in ("balanceRate", "transactionRate", "accruedRate"):
        if present(item.get(key)):
            return item.get(key)
    return None


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
                product_eligibility=as_items(rec.get("eligibility")),
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
            item_value = bank_detail_item_value(sheet, item)
            dataset[sheet].append(
                {
                    **base,
                    "item_index": idx,
                    "item_type": text(item.get(label_key)),
                    "name": text(item.get("name") or item.get("additionalValue")),
                    "value": text(item_value),
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
        "product_facts": [],
        "failures": read_failures(banks_root),
        "quarantines": [],
        "holder_attempts": [],
        "provider_observations": [],
    }
    if not banks_root.exists():
        return dataset
    holders_root = banks_root / "_holders"
    providers = _provider_records(holders_root)
    if holders_root.is_dir():
        dataset["holder_attempts"] = sorted(
            path.name for path in holders_root.iterdir() if path.is_dir()
        )
    for path in sorted(banks_root.rglob("product-detail.json")):
        relative = path.relative_to(banks_root)
        provider_dir = relative.parts[1] if len(relative.parts) > 1 else ""
        evidence_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rec: Dict[str, Any] = {}
        code = "detail_invalid_json"
        try:
            rec = inner_record(load_json(path))
            code = "identity_mismatch"
            if provider_dir not in providers:
                digest = hashlib.sha256(
                    f"legacy-provider-v1\0{provider_dir}".encode("utf-8")
                ).hexdigest()
                providers[provider_dir] = {
                    "provider_uid": f"legacy-prd:{digest}",
                    "provider_identity_status": "legacy_unverified",
                    "brand_name": provider_dir,
                }
            base = bank_base_row(path, banks_root, rec, providers[provider_dir])
            invalid_details = _invalid_detail_arrays(rec)
            filtered = {
                key: value for key, value in rec.items() if key not in invalid_details
            }
            safe_record = json.loads(detail_json(filtered))
            base = bank_base_row(path, banks_root, safe_record, providers[provider_dir])
            code = "rate_invalid"
            _validate_core_rates(safe_record, str(base["dataset"]))
            code = "rate_invalid"
            facts = clean_fact_rows(safe_record, base)
            _validate_rate_facts(facts)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            product_id = text(rec.get("productId") or rec.get("id"))
            if not product_id:
                try:
                    product_id = (path.parent / "product-id.txt").read_text(
                        encoding="utf-8"
                    ).strip()
                except (OSError, UnicodeError):
                    product_id = ""
            issue = {
                "phase": "normalization",
                "bank": provider_dir or "unknown",
                "product_id": product_id,
                "status": code,
                "evidence_digest": evidence_digest,
                "source_file": relative.as_posix(),
            }
            dataset["failures"].append(issue)
            dataset["quarantines"].append(issue)
            continue
        base["details_complete"] = not invalid_details
        dataset["products"].append(
            {
                **base,
                "details_json": json.dumps(
                    safe_record, ensure_ascii=False, sort_keys=True
                ),
            }
        )
        for group in invalid_details:
            dataset["quarantines"].append(
                {
                    "phase": "normalization",
                    "bank": provider_dir,
                    "product_id": base["product_id"],
                    "status": "field_omitted_invalid",
                    "affected_sections": [group],
                    "evidence_digest": evidence_digest,
                    "source_file": relative.as_posix(),
                }
            )
        append_bank_details(dataset, base, safe_record)
        dataset["product_facts"].extend(facts)
    dataset["provider_observations"] = [
        {
            "provider_dir": provider_dir,
            "provider_uid": record.get("provider_uid"),
            "provider_identity_status": record.get("provider_identity_status"),
            "brand_name": record.get("brand_name") or record.get("legal_entity_name") or provider_dir,
            "legal_entity_name": record.get("legal_entity_name") or "",
            "endpoint_url": record.get("endpoint_url") or "",
            "data_holder_id": record.get("data_holder_id") or "",
            "data_holder_brand_id": record.get("data_holder_brand_id") or "",
            "interim_id": record.get("interim_id") or "",
            "identity_authority": record.get("identity_authority") or "",
            "provider_identity_held": record.get("provider_identity_held") is True,
            "population": record.get("population"),
        }
        for provider_dir, record in sorted(providers.items())
    ]
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
