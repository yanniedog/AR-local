"""AustralianRates-aligned ribbon facets for flattened CDR rate rows.

Logic mirrors dashboard/cdr-ribbon-map.js so export JSON/SQLite can stay slim without
embedding full cleaned rate payloads in ``details_json``.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

_ISO_DURATION = re.compile(r"^P(\d+)([DMYW])$", re.IGNORECASE)
_MONTH_RE = re.compile(r"(\d+)\s*(?:MONTH|MTH|MO)", re.IGNORECASE)
_DAY_RE = re.compile(r"(\d+)\s*DAY", re.IGNORECASE)
_YEAR_RE = re.compile(r"(\d+)\s*YEAR", re.IGNORECASE)
_LVR_RANGE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,2}(?:\.\d+)?)\s*%")
_LVR_LE = re.compile(r"(?:<=|under|up to|maximum|max)\s*(\d{1,2}(?:\.\d+)?)\s*%")
_ANY_PCT_FOR_LVR = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")
_BOUNDS_PAIR = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d+)?)\s*%?",
)
_BOUND_LE = re.compile(r"(?:<=|under|up to|maximum|max|below)\s*(\d{1,3}(?:\.\d+)?)\s*%?")
_BOUND_GE = re.compile(r"(?:>=|over|above|from)\s*(\d{1,3}(?:\.\d+)?)\s*%?")
_BOUND_SINGLE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def _lower_join(*parts: Any) -> str:
    """Lowercase phrase from joined non-empty trimmed string parts.

    None is skipped; booleans are skipped (ribbon hints should be strings — use
    literal "true"/"false" if needed). Numeric 0 becomes "0"; we do not apply
    Python truthiness on non-bools so emptiness is only from str(p).strip().
    """

    bits: List[str] = []
    for p in parts:
        if p is None or isinstance(p, bool):
            continue
        s = str(p).strip()
        if s:
            bits.append(s)
    return " ".join(bits).lower()


def _lower(text: Any) -> str:
    return str(text or "").strip().lower()


def parse_term_months(duration: Any) -> Optional[float]:
    t = str(duration or "").strip().upper()
    m = _ISO_DURATION.match(t)
    if m:
        n = float(m.group(1))
        unit = m.group(2).upper()
        if unit == "M":
            return n
        if unit == "D":
            return round(n / 30)
        if unit == "Y":
            return n * 12
        if unit == "W":
            return round((n * 7) / 30)

    tm = _MONTH_RE.search(t)
    if tm:
        return float(tm.group(1))

    dm = _DAY_RE.search(t)
    if dm:
        return round(float(dm.group(1)) / 30)

    ym = _YEAR_RE.search(t)
    if ym:
        return float(ym.group(1)) * 12

    try:
        num = float(t)
    except ValueError:
        return None
    if math.isfinite(num) and 0 < num <= 1200:
        return num

    return None


def normalize_repayment_type(hints: str) -> str:
    t = _lower(hints)
    if (
        "interest only" in t
        or "interest_only" in t
        or "interestonly" in t
        or re.search(r"\binterest[_\s]*only[_\s]*(?:fixed|variable)?\b", t)
    ):
        return "interest_only"
    return "principal_and_interest"


def tier_for_boundary(percent: Any) -> str:
    try:
        p = float(percent)
    except (TypeError, ValueError):
        return "lvr_unspecified"

    if 0 < p <= 1:
        p = round(p * 100, 4)
    if p <= 60:
        return "lvr_=60%"
    if p <= 70:
        return "lvr_60-70%"
    if p <= 80:
        return "lvr_70-80%"
    if p <= 85:
        return "lvr_80-85%"
    if p <= 90:
        return "lvr_85-90%"
    return "lvr_90-95%"


def normalize_lvr_tier(context_text: str, min_lvr: Any, max_lvr: Any) -> str:
    hi_finite = isinstance(max_lvr, (int, float)) and math.isfinite(float(max_lvr))
    lo_finite = isinstance(min_lvr, (int, float)) and math.isfinite(float(min_lvr))

    if hi_finite or lo_finite:
        hi_raw = float(max_lvr if hi_finite else min_lvr)
        hi = hi_raw
        if 0 < hi <= 1:
            hi = round(hi * 100, 4)
        return tier_for_boundary(hi)

    txt = _lower(context_text)

    rg = _LVR_RANGE.search(txt)
    if rg:
        hi2 = float(rg.group(2))
        if math.isfinite(hi2):
            return tier_for_boundary(hi2)

    le = _LVR_LE.search(txt)
    if le:
        hi3 = float(le.group(1))
        if math.isfinite(hi3):
            return tier_for_boundary(hi3)

    ap = _ANY_PCT_FOR_LVR.search(txt)
    if ap and ("lvr" in txt or "loan to value" in txt or "ltv" in txt):
        hi4 = float(ap.group(1))
        if math.isfinite(hi4):
            return tier_for_boundary(hi4)

    return "lvr_unspecified"


def parse_numeric(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def parse_lvr_bounds_from_constraints(constraints: List[Mapping[str, Any]]) -> Optional[Tuple[Optional[float], Optional[float]]]:
    min_lo: Optional[float] = None
    max_hi: Optional[float] = None
    for c in constraints:
        ctype = _lower(c.get("constraintType") or "")
        if "lvr" not in ctype:
            continue
        additional = parse_numeric(c.get("additionalValue"))
        min_value = parse_numeric(c.get("minValue"))
        max_value = parse_numeric(c.get("maxValue"))
        if "min" in ctype:
            min_lo = additional if additional is not None else (min_value if min_value is not None else min_lo)
        elif "max" in ctype:
            max_hi = additional if additional is not None else (max_value if max_value is not None else max_hi)
        else:
            if min_value is not None:
                min_lo = min_value
            if max_value is not None:
                max_hi = max_value
            elif additional is not None:
                max_hi = additional
    return (min_lo, max_hi) if (min_lo is not None or max_hi is not None) else None


def parse_lvr_bounds_from_rate_item(item: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    conc = item.get("constraints")
    if isinstance(conc, list):
        parsed = parse_lvr_bounds_from_constraints([x for x in conc if isinstance(x, Mapping)])
        if parsed is not None:
            return parsed

    tiers = item.get("tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, Mapping):
                continue
            tier_name = _lower_join(
                str(tier.get("name") or ""),
                str(tier.get("unitOfMeasure") or ""),
                str(tier.get("rateApplicationMethod") or ""),
            )
            if "lvr" not in tier_name and "loan to value" not in tier_name:
                continue
            t_min = parse_numeric(tier.get("minimumValue"))
            t_max = parse_numeric(tier.get("maximumValue"))
            if t_min is not None or t_max is not None:
                return (t_min, t_max)

    extra = "|".join(
        str(item.get(part) or "")
        for part in ("additionalValue", "additionalInfo", "name")
    )
    if not extra.strip("|"):
        return (None, None)

    txt = _lower(extra)
    bp = _BOUNDS_PAIR.search(txt)
    if bp:
        lo, hi = float(bp.group(1)), float(bp.group(2))
        if math.isfinite(lo) and math.isfinite(hi):
            return (lo, hi)

    le2 = _BOUND_LE.search(txt)
    if le2:
        return (None, float(le2.group(1)))

    ge = _BOUND_GE.search(txt)
    if ge:
        return (float(ge.group(1)), None)

    sg = _BOUND_SINGLE.search(txt)
    if sg:
        return (None, float(sg.group(1)))

    return (None, None)


def normalize_feature_set(text: str, annual_fee: Optional[float]) -> str:
    t = _lower(text)
    if (
        "package" in t
        or "advantage" in t
        or "premium" in t
        or "offset" in t
        or (annual_fee is not None and annual_fee > 0)
    ):
        return "premium"
    return "basic"


def parse_tier_bounds(rate_rec: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    tiers = rate_rec.get("tiers")
    if not isinstance(tiers, list):
        return (None, None)
    for tier in tiers:
        if not isinstance(tier, Mapping):
            continue
        unit = str(tier.get("unitOfMeasure") or "").upper()
        if unit and unit not in ("DOLLAR", "AMOUNT"):
            continue
        t_min = parse_numeric(tier.get("minimumValue"))
        t_max = parse_numeric(tier.get("maximumValue"))
        if t_min is not None or t_max is not None:
            return (t_min, t_max)
    return (None, None)


def normalize_account_type(product_hint: str) -> str:
    t = _lower(product_hint)
    if "at call" in t or "at_call" in t:
        return "at_call"
    if "savings" in t or "saver" in t or "save account" in t:
        return "savings"
    if "transaction" in t or "everyday" in t or "spending" in t:
        return "transaction"
    return "savings"


def normalize_deposit_rate_kind(raw: Any) -> str:
    t = _lower(raw)
    if "bonus" in t:
        return "bonus"
    if "introductory" in t or "intro" in t:
        return "introductory"
    if "bundle" in t or "bundled" in t:
        return "bundle"
    if "total" in t:
        return "total"
    return "base"


def normalize_interest_payment(
    payment_text: str,
    application_type: str,
    application_frequency: str,
    term_months: float,
) -> str:
    t = _lower_join(payment_text, application_type, application_frequency)
    app_type = _lower(application_type)

    fq = parse_term_months(application_frequency or "")

    if "maturity" in app_type:
        return "at_maturity"
    if fq is not None and math.isfinite(fq) and math.isfinite(term_months) and fq >= term_months:
        return "at_maturity"
    if "quarterly" in t or "quarter" in t:
        return "quarterly"
    if "annual" in t or "yearly" in t:
        return "annually"
    if fq is not None and fq >= 12:
        return "annually"
    # Parity with dashboard/cdr-ribbon-map.js normalizeInterestPayment: fq==6 (P6M) → monthly here.
    # Canonical rules live in this module; mirror changes in JS when adjusting cadence buckets.
    if "monthly" in t or (fq is not None and (fq == 1 or fq == 6)):
        return "monthly"
    if "at maturity" in t:
        return "at_maturity"
    return "at_maturity"


def _num_or_empty(val: Optional[float]) -> str:
    if val is None or not math.isfinite(val):
        return ""
    nearest = round(val)
    # Never rstrip("0") on integer-form strings: "100".rstrip("0") → "10".
    if math.isclose(val, nearest, rel_tol=1e-9, abs_tol=1e-12):
        return str(int(nearest))
    text = f"{val:.12g}".rstrip("0").rstrip(".")
    return text or "0"


def ribbon_columns_for_bank_rate_row(
    dataset: str,
    rate_family: str,
    flat_base: Mapping[str, Any],
    cleaned_item: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return discrete ribbon-aligned columns merged into export bank rate rows."""
    defaults: Dict[str, Any] = {
        "ribbon_normalized": False,
        "security_purpose": "",
        "ribbon_repayment_type": "",
        "lvr_tier": "",
        "ribbon_rate_structure": "",
        "account_type": "",
        "ribbon_deposit_kind": "",
        "balance_min": "",
        "balance_max": "",
        "term_months": "",
        "interest_payment": "",
        "feature_set": "",
    }

    if dataset == "Mortgage" and rate_family == "lending":
        structured = _lower_join(flat_base.get("loan_purpose") or "", str(cleaned_item.get("loanPurpose") or ""))
        security_purpose = "investment" if "invest" in structured else "owner_occupied"
        repayment_hints = " ".join(
            str(x or "")
            for x in (flat_base.get("repayment_type"), cleaned_item.get("repaymentType"))
        )
        ribbon_repayment = normalize_repayment_type(repayment_hints)
        lending_rate_type = str(cleaned_item.get("lendingRateType") or flat_base.get("rate_type") or "").strip()
        context_parts = [
            str(cleaned_item.get("additionalInfo") or ""),
            str(cleaned_item.get("additionalValue") or ""),
            str(cleaned_item.get("name") or ""),
        ]
        context_text = " | ".join(p for p in context_parts if p)
        rate_structure_text = " ".join(
            str(p).strip()
            for p in (
                lending_rate_type,
                str(cleaned_item.get("name") or ""),
                flat_base.get("term") or "",
                context_text,
            )
            if p
        ).strip()
        l_min, l_max = parse_lvr_bounds_from_rate_item(cleaned_item)
        full_context = " ".join(p for p in (context_text, flat_base.get("product_name") or "") if p)
        lvr_tier = normalize_lvr_tier(full_context, l_min, l_max)
        feature_set = normalize_feature_set(full_context, None)
        out = dict(defaults)
        out.update(
            {
                "ribbon_normalized": True,
                "security_purpose": security_purpose,
                "ribbon_repayment_type": ribbon_repayment,
                "lvr_tier": lvr_tier,
                "ribbon_rate_structure": rate_structure_text,
                "feature_set": feature_set,
            }
        )
        return out

    if dataset == "Savings" and rate_family == "deposit":
        product_hint = " ".join(
            str(x or "")
            for x in (flat_base.get("product_name"), flat_base.get("category"))
        )
        account_type = normalize_account_type(product_hint)
        rate_kind = normalize_deposit_rate_kind(
            cleaned_item.get("depositRateType")
            or cleaned_item.get("rateType")
            or cleaned_item.get("type")
            or flat_base.get("rate_type")
        )
        b_min, b_max = parse_tier_bounds(cleaned_item)
        feature_set = normalize_feature_set(
            product_hint + " " + str(cleaned_item.get("additionalInfo") or ""),
            None,
        )
        out = dict(defaults)
        out.update(
            {
                "ribbon_normalized": True,
                "account_type": account_type,
                "ribbon_deposit_kind": rate_kind,
                "balance_min": _num_or_empty(b_min),
                "balance_max": _num_or_empty(b_max),
                "feature_set": feature_set,
            }
        )
        return out

    if dataset == "TD" and rate_family == "deposit":
        term_m = parse_term_months(cleaned_item.get("additionalValue") or "") or parse_term_months(
            flat_base.get("term") or ""
        ) or parse_term_months(cleaned_item.get("name") or "") or parse_term_months(
            flat_base.get("product_name") or ""
        )
        if term_m is None or not math.isfinite(term_m) or term_m < 1:
            term_m = 12.0

        b_min, b_max = parse_tier_bounds(cleaned_item)
        payment_parts = (
            cleaned_item.get("applicationFrequency"),
            cleaned_item.get("additionalInfo"),
            cleaned_item.get("applicationType"),
        )
        payment_text = " ".join(str(p or "") for p in payment_parts)
        interest_payment = normalize_interest_payment(
            payment_text,
            str(cleaned_item.get("applicationType") or ""),
            str(cleaned_item.get("applicationFrequency") or ""),
            term_m,
        )
        deposit_rate_display = str(
            cleaned_item.get("depositRateType")
            or cleaned_item.get("rateType")
            or flat_base.get("rate_type")
            or ""
        ).strip()
        ribbon_kind = normalize_deposit_rate_kind(deposit_rate_display)
        rate_structure_text = " ".join(
            str(p).strip() for p in (deposit_rate_display, str(cleaned_item.get("name") or "")) if p
        ).strip()
        feature_set = normalize_feature_set(
            " ".join(p for p in (flat_base.get("product_name") or "", payment_text) if p),
            None,
        )

        out = dict(defaults)
        out.update(
            {
                "ribbon_normalized": True,
                "ribbon_deposit_kind": ribbon_kind,
                "term_months": _num_or_empty(term_m),
                "interest_payment": interest_payment,
                "ribbon_rate_structure": rate_structure_text,
                "feature_set": feature_set,
                "balance_min": _num_or_empty(b_min),
                "balance_max": _num_or_empty(b_max),
            }
        )
        return out

    return defaults
