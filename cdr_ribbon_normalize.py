"""AustralianRates-aligned ribbon facets for flattened CDR rate rows.

Imports cdr_taxonomy at call-time (not module-load) to avoid a circular
dependency — cdr_taxonomy is a leaf module with no upward imports.

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
_FIXED_TERM_YEARS = re.compile(r"fixed[^0-9]*(\d+)", re.IGNORECASE)
_FIXED_TERM_ISO = re.compile(r"\bp(\d+)y\b", re.IGNORECASE)
_BUNDLE_VARIABLE = re.compile(r"^bundle[_-]?discount[_-]?variable\b", re.IGNORECASE)


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


def extract_fixed_rate_term_years(text: str) -> str:
    """Years for ribbon fixed_rate_term tier (matches site ar-ribbon-format.js)."""
    value = _lower(text)
    if not value or value == "variable":
        return ""
    m = re.match(r"^fixed_(\d+)yr$", value)
    if m:
        return str(int(m.group(1)))
    m = _FIXED_TERM_YEARS.search(value)
    if m:
        return str(int(m.group(1)))
    m = _FIXED_TERM_ISO.search(value)
    if m:
        return str(int(m.group(1)))
    return ""


def normalize_rate_structure_group(text: str) -> str:
    """Collapse CDR rate text to ribbon tree keys: variable | fixed."""
    value = _lower(text)
    if not value:
        return ""
    if value == "variable" or re.match(r"^variable\b", value) or _BUNDLE_VARIABLE.match(value):
        return "variable"
    if value == "fixed" or re.match(r"^fixed\b", value):
        return "fixed"
    if extract_fixed_rate_term_years(value):
        return "fixed"
    head = value.split(None, 1)[0] if value.split() else value
    if head in ("variable", "var"):
        return "variable"
    if head == "fixed":
        return "fixed"
    if re.search(r"\bvariable\b", value[:96]) and not re.match(r"^fixed\b", value):
        return "variable"
    return ""


def normalize_td_rate_structure_group(text: str, deposit_kind: str) -> str:
    """Deposit ribbon rate_structure tier keys (short slugs for the tree)."""
    kind = _lower(deposit_kind)
    if kind in ("base", "bonus", "introductory", "bundle", "total"):
        return kind
    value = _lower(text)
    if not value:
        return "base"
    if "intro" in value:
        return "introductory"
    if "bonus" in value:
        return "bonus"
    if "bundle" in value:
        return "bundle"
    if "total" in value:
        return "total"
    grouped = normalize_rate_structure_group(value)
    if grouped:
        return grouped
    return kind or "base"


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


# LVR/LTV encoded in free text with a BARE number (no % sign) and plain </>/<=/>=
# operators — the %-anchored regexes above miss these. Real examples from the feed:
# Cairns Bank "CLASSIC HOME LOAN VARIABLE <60 LVR IO", "... >90 LVR PI".
_LVR_SIGNAL_RE = re.compile(r"\b(?:lvr|ltv|loan[\s_-]*to[\s_-]*value)\b", re.IGNORECASE)
_LVR_NAME_RANGE = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d+)?)\s*%?\s*(?:lvr|ltv)"
    r"|(?:lvr|ltv)\s*:?\s*(\d{1,3}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d+)?)",
    re.IGNORECASE,
)
# Operator alternation: symbols, natural-language comparators, and bound words.
# Operator is OPTIONAL in both forms below so a bare "80 LVR" / "LVR 80" parses.
_LVR_OP = (
    r"<=|>=|<|>|less[\s_-]*than[\s_-]*or[\s_-]*equal[\s_-]*to|greater[\s_-]*than[\s_-]*or[\s_-]*equal[\s_-]*to"
    r"|less[\s_-]*than|greater[\s_-]*than|more[\s_-]*than|no[\s_-]*more[\s_-]*than"
    r"|at[\s_-]*least|at[\s_-]*most|under|below|over|above|from"
    r"|max(?:imum)?|min(?:imum)?|up[\s_-]*to"
)
_LVR_NAME_OP = re.compile(
    rf"(?:({_LVR_OP})\s*)?(\d{{1,3}}(?:\.\d+)?)\s*%?\s*(?:lvr|ltv)"
    rf"|(?:lvr|ltv)\s*:?\s*(?:({_LVR_OP})\s*)?(\d{{1,3}}(?:\.\d+)?)",
    re.IGNORECASE,
)
_LVR_TIER_ORDER = ("lvr_=60%", "lvr_60-70%", "lvr_70-80%", "lvr_80-85%", "lvr_85-90%", "lvr_90-95%")
_LVR_LOWER_BOUND_OPS = frozenset(
    {">", ">=", "over", "above", "greater than", "greater than or equal to",
     "more than", "at least", "from", "min", "minimum"}
)


def _bump_tier_up(tier: str) -> str:
    try:
        i = _LVR_TIER_ORDER.index(tier)
    except ValueError:
        return tier
    return _LVR_TIER_ORDER[min(i + 1, len(_LVR_TIER_ORDER) - 1)]


def _is_lower_bound_op(op: Optional[str]) -> bool:
    # Normalize whitespace/underscore/hyphen joins so "greater_than" == "greater than".
    o = re.sub(r"[\s_-]+", " ", (op or "").strip().lower())
    return o in _LVR_LOWER_BOUND_OPS


def named_lvr_tier(text: str) -> str:
    """Tier from LVR/LTV stated with a bare number, e.g. '<60 LVR', '>90 LVR',
    '70-80 LVR', '80 LVR', 'LVR less than 70', 'greater than 90 LVR'. Returns ''
    when there is no LVR signal or no parseable number.

    A range, a bare number, or an upper-bound operator (``<``/``<=``/under/max/
    'less than') maps on its upper value; a lower-bound operator (``>``/``>=``/
    over/min/'greater than'/'more than') bumps one tier up so '>90 LVR' lands in
    lvr_90-95% rather than lvr_85-90%.
    """
    txt = _lower(text)
    if not txt or not _LVR_SIGNAL_RE.search(txt):
        return ""
    m = _LVR_NAME_RANGE.search(txt)
    if m:
        hi = m.group(2) or m.group(4)
        if hi is not None:
            return tier_for_boundary(float(hi))
    m = _LVR_NAME_OP.search(txt)
    if m:
        op = m.group(1) or m.group(3)
        num = m.group(2) or m.group(4)
        if num is not None:
            base = tier_for_boundary(float(num))
            return _bump_tier_up(base) if _is_lower_bound_op(op) else base
    return ""


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


def _text_has_lvr_signal(text: str) -> bool:
    t = _lower(text)
    return "lvr" in t or "loan to value" in t or "ltv" in t


def parse_lvr_bounds_from_text_blob(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Parse LVR-ish percent bounds from free text that already mentions LVR/LTV."""
    txt = _lower(text)
    if not txt.strip() or not _text_has_lvr_signal(txt):
        return (None, None)

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


def extract_product_lvr_constraints(product_rec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """CDR product-level constraints that mention LVR/LTV."""
    out: List[Dict[str, Any]] = []
    raw = product_rec.get("constraints")
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        blob = _lower_join(
            item.get("constraintType"),
            item.get("additionalInfo"),
            item.get("additionalValue"),
            item.get("name"),
        )
        if "lvr" in blob or "loan to value" in blob or "ltv" in blob:
            out.append(dict(item))
    return out


def resolve_lvr_tier(
    context_text: str,
    rate_item: Mapping[str, Any],
    product_constraints: Optional[List[Mapping[str, Any]]] = None,
) -> Tuple[str, str]:
    """Return (lvr_tier slug, lvr_source) for a mortgage lending rate."""
    product_constraints = product_constraints or []
    l_min, l_max = parse_lvr_bounds_from_rate_item(rate_item)
    source = "none"

    if l_min is not None or l_max is not None:
        source = "rate_structured"
    elif product_constraints:
        parsed = parse_lvr_bounds_from_constraints(
            [x for x in product_constraints if isinstance(x, Mapping)]
        )
        if parsed is not None:
            l_min, l_max = parsed
            if l_min is not None or l_max is not None:
                source = "product_constraints"

    # Structured bounds (from the rate item or product constraints) are
    # authoritative — resolve directly from them.
    if l_min is not None or l_max is not None:
        tier = normalize_lvr_tier(context_text, l_min, l_max)
        if tier != "lvr_unspecified":
            return tier, source

    if context_text.strip() and _text_has_lvr_signal(context_text):
        # Operator-aware name parser FIRST: it handles lower-bound forms
        # ("over 80 LVR", ">90 LVR", "from 80 LVR") that the %-bounds heuristics
        # below would otherwise mis-read as an upper bound (Codex PR #146).
        named = named_lvr_tier(context_text)
        if named:
            return named, "context_text"
        tier = normalize_lvr_tier(context_text, None, None)
        if tier != "lvr_unspecified":
            return tier, "context_text"
        ctx_min, ctx_max = parse_lvr_bounds_from_text_blob(context_text)
        if ctx_min is not None or ctx_max is not None:
            tier2 = normalize_lvr_tier("", ctx_min, ctx_max)
            if tier2 != "lvr_unspecified":
                return tier2, "context_text"

    if product_constraints:
        return "lvr_unspecified", "product_unparsed"
    return "lvr_unspecified", source


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
        info = _lower(c.get("additionalInfo") or "")
        if "lvr" not in ctype and "loan to value" not in ctype and "ltv" not in ctype:
            if "lvr" not in info and "loan to value" not in info and "ltv" not in info:
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
    # abs_tol only — rel_tol allows O(magnitude) slack and mis-formats large non-integers.
    if math.isclose(val, nearest, rel_tol=0.0, abs_tol=1e-9):
        return str(int(nearest))
    text = f"{val:.12g}"
    if "e" not in text.lower():
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def ribbon_columns_for_bank_rate_row(
    dataset: str,
    rate_family: str,
    flat_base: Mapping[str, Any],
    cleaned_item: Mapping[str, Any],
    *,
    product_lvr_constraints: Optional[List[Mapping[str, Any]]] = None,
    product_eligibility: Optional[List[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return discrete ribbon-aligned columns merged into export bank rate rows."""
    from cdr_taxonomy import (
        classify_account_standardness as _classify_standardness,
        classify_bank_rate_row as _classify,
    )

    defaults: Dict[str, Any] = {
        "ribbon_normalized": False,
        "security_purpose": "",
        "ribbon_repayment_type": "",
        "lvr_tier": "",
        "lvr_source": "",
        "ribbon_rate_structure": "",
        "ribbon_fixed_term": "",
        "account_type": "",
        "ribbon_deposit_kind": "",
        "balance_min": "",
        "balance_max": "",
        "term_months": "",
        "interest_payment": "",
        "feature_set": "",
        "taxonomy_path": "",
        "account_class": "",
    }
    # Standard vs non-standard applies to every section/dataset (loans included).
    # Set on defaults so it rides through each branch's `dict(defaults)` copy and
    # the fallthrough return without per-branch wiring.
    defaults["account_class"] = _classify_standardness(
        flat_base.get("product_name"),
        flat_base.get("category"),
        dataset,
        eligibility=product_eligibility,
    )

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
        full_context = " ".join(p for p in (context_text, flat_base.get("product_name") or "") if p)
        lvr_tier, lvr_source = resolve_lvr_tier(
            full_context,
            cleaned_item,
            product_lvr_constraints,
        )
        feature_set = normalize_feature_set(full_context, None)
        rate_structure_group = normalize_rate_structure_group(rate_structure_text)
        fixed_term = (
            extract_fixed_rate_term_years(rate_structure_text) if rate_structure_group == "fixed" else ""
        )
        out = dict(defaults)
        out.update(
            {
                "ribbon_normalized": True,
                "security_purpose": security_purpose,
                "ribbon_repayment_type": ribbon_repayment,
                "lvr_tier": lvr_tier,
                "lvr_source": lvr_source,
                "ribbon_rate_structure": rate_structure_group,
                "ribbon_fixed_term": fixed_term,
                "feature_set": feature_set,
            }
        )
        out["taxonomy_path"] = _classify(dataset, flat_base, out)
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
        # All at-call savings accounts are non-standard, keyed on the authoritative
        # normalized account_type (not just the name marker) so none slip through.
        if account_type == "at_call":
            out["account_class"] = "non_standard"
        out["taxonomy_path"] = _classify(dataset, flat_base, out)
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

        rate_structure_group = normalize_td_rate_structure_group(rate_structure_text, ribbon_kind)
        out = dict(defaults)
        out.update(
            {
                "ribbon_normalized": True,
                "ribbon_deposit_kind": ribbon_kind,
                "term_months": _num_or_empty(term_m),
                "interest_payment": interest_payment,
                "ribbon_rate_structure": rate_structure_group,
                "feature_set": feature_set,
                "balance_min": _num_or_empty(b_min),
                "balance_max": _num_or_empty(b_max),
            }
        )
        out["taxonomy_path"] = _classify(dataset, flat_base, out)
        return out

    defaults["taxonomy_path"] = _classify(dataset, flat_base, defaults)
    return defaults
