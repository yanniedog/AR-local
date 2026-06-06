"""Single-path taxonomy classifiers for CDR banking rate rows.

Each row maps to exactly one dot-separated banking path.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

_ISO_YEAR = re.compile(r"^P(\d+)Y$", re.IGNORECASE)
_ISO_MONTH = re.compile(r"^P(\d+)M$", re.IGNORECASE)


def _parse_term_months(ribbon: Mapping[str, Any], flat_base: Mapping[str, Any]) -> Optional[int]:
    """Whole-month term from pre-computed ribbon column or raw ISO duration."""
    tm = ribbon.get("term_months") or flat_base.get("term_months")
    if tm not in (None, "", 0, 0.0, "0"):
        try:
            n = int(float(tm))
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
    raw = str(flat_base.get("term") or "").strip().upper()
    m = _ISO_YEAR.match(raw)
    if m:
        return int(m.group(1)) * 12
    m = _ISO_MONTH.match(raw)
    if m:
        return int(m.group(1))
    try:
        n = int(float(raw))
        if 0 < n <= 1200:
            return n
    except (TypeError, ValueError):
        pass
    return None


def _is_set(val: Any) -> bool:
    """True for any non-None, non-empty value — 0 and '0' count (valid tier bounds)."""
    return val is not None and val != ""


# ──────────────────────────────────────────────────────────────────────────────
# Banking taxonomy
# ──────────────────────────────────────────────────────────────────────────────

_CATEGORY_TO_PC: dict[str, str] = {
    "RESIDENTIAL_MORTGAGES": "HOME_LOAN",
    "RESIDENTIAL_MORTGAGE": "HOME_LOAN",
    "MORTGAGES": "HOME_LOAN",
    "MORTGAGE": "HOME_LOAN",
    "HOME_LOANS": "HOME_LOAN",
    "HOME_LOAN": "HOME_LOAN",
    "BUSINESS_LOANS": "BUSINESS_LOAN",
    "BUSINESS_LOAN": "BUSINESS_LOAN",
    "PERS_LOANS": "PERSONAL_LOAN",
    "PERSONAL_LOANS": "PERSONAL_LOAN",
    "PERSONAL_LOAN": "PERSONAL_LOAN",
    "OVERDRAFTS": "OVERDRAFT",
    "OVERDRAFT": "OVERDRAFT",
    "CRED_AND_CHRG_CARDS": "CREDIT_CARD",
    "CREDIT_CARDS": "CREDIT_CARD",
    "TRANS_AND_SAVINGS_ACCOUNTS": "SAVINGS",
    "TRANS_AND_SAVINGS_ACCOUNT": "SAVINGS",
    "TRANS_AND_SAVINGS": "SAVINGS",
    "SAVINGS_ACCOUNTS": "SAVINGS",
    "SAVINGS_ACCOUNT": "SAVINGS",
    "SAVINGS": "SAVINGS",
    "TRANSACTION_AND_SAVINGS_ACCOUNTS": "SAVINGS",
    "TERM_DEPOSITS": "TERM_DEPOSIT",
    "TERM_DEPOSIT": "TERM_DEPOSIT",
    "FIXED_TERM_DEPOSITS": "TERM_DEPOSIT",
    "FIXED_TERM_DEPOSIT": "TERM_DEPOSIT",
    "FIXED_DEPOSITS": "TERM_DEPOSIT",
    "FIXED_DEPOSIT": "TERM_DEPOSIT",
}

_DATASET_FALLBACK: dict[str, str] = {
    "Mortgage": "HOME_LOAN",
    "Savings": "SAVINGS",
    "TD": "TERM_DEPOSIT",
}

_RATE_TYPE_MAP: dict[str, str] = {
    "VARIABLE": "VARIABLE",
    "FIXED": "FIXED",
    "INTRODUCTORY": "INTRO",
    "DISCOUNT": "DISCOUNT",
    "BUNDLE": "BUNDLE",
    "FLOATING": "FLOATING",
    "PURCHASE": "PURCHASE",
    "CASH_ADVANCE": "CASH_ADVANCE",
    "BALANCE_TRANSFER": "BAL_TRANSFER",
    "INTEREST_FREE": "INTEREST_FREE",
}

_TERM_STANDARD = frozenset({12, 24, 36, 48, 60})

_LVR_MAP: dict[str, str] = {
    "lvr_=60%": "LVR_LE60",
    "lvr_60-70%": "LVR_60_70",
    "lvr_70-80%": "LVR_70_80",
    "lvr_80-85%": "LVR_80_85",
    "lvr_85-90%": "LVR_85_90",
    "lvr_90-95%": "LVR_90_95",
    "lvr_unspecified": "LVR_UNSP",
}

_SECURITY_MAP: dict[str, str] = {
    "owner_occupied": "OO",
    "investment": "INV",
}

_REPAYMENT_MAP: dict[str, str] = {
    "principal_and_interest": "PI",
    "interest_only": "IO",
}

_ACCOUNT_MAP: dict[str, str] = {
    "savings": "SAVINGS_ACCT",
    "transaction": "TRANSACTION",
    "at_call": "AT_CALL",
}

_DEPOSIT_KIND_MAP: dict[str, str] = {
    "base": "BASE",
    "bonus": "BONUS",
    "introductory": "INTRO",
    "bundle": "BUNDLE",
    "total": "TOTAL",
}

_INTEREST_PAYMENT_MAP: dict[str, str] = {
    "at_maturity": "AT_MATURITY",
    "monthly": "MONTHLY",
    "quarterly": "QUARTERLY",
    "annually": "ANNUALLY",
}


def classify_bank_rate_row(
    dataset: str,
    flat_base: Mapping[str, Any],
    ribbon: Mapping[str, Any],
) -> str:
    """Return a dot-separated taxonomy path for a bank rate row.

    ``dataset``  — pipeline folder name: Mortgage | Savings | TD | …
    ``flat_base`` — the bank_base_row dict (category, rate_type, term, …)
    ``ribbon``   — already-computed ribbon columns for this row
    """
    category = str(flat_base.get("category") or "").strip().upper()
    pc = _CATEGORY_TO_PC.get(category) or _DATASET_FALLBACK.get(dataset, "UNKNOWN")

    rate_raw = str(flat_base.get("rate_type") or "").strip().upper()
    rate_token = _RATE_TYPE_MAP.get(rate_raw, "OTHER")

    parts = [pc]

    if pc in ("HOME_LOAN", "BUSINESS_LOAN"):
        if pc == "HOME_LOAN":
            sec = str(ribbon.get("security_purpose") or "").strip()
            parts.append(_SECURITY_MAP.get(sec, "OTHER"))

        rep = str(ribbon.get("ribbon_repayment_type") or "").strip()
        parts.append(_REPAYMENT_MAP.get(rep, "OTHER"))
        parts.append(rate_token)

        if rate_token == "FIXED":
            tm = _parse_term_months(ribbon, flat_base)
            parts.append(f"{tm}M" if tm in _TERM_STANDARD else "OTHER_TERM")

        lvr = str(ribbon.get("lvr_tier") or "lvr_unspecified").strip()
        parts.append(_LVR_MAP.get(lvr, "LVR_UNSP"))

    elif pc == "SAVINGS":
        acct = str(ribbon.get("account_type") or "").strip()
        parts.append(_ACCOUNT_MAP.get(acct, "OTHER"))
        kind = str(ribbon.get("ribbon_deposit_kind") or "").strip()
        parts.append(_DEPOSIT_KIND_MAP.get(kind, "OTHER"))
        has_tier = _is_set(ribbon.get("balance_min")) or _is_set(ribbon.get("balance_max"))
        parts.append("TIERED" if has_tier else "FLAT")

    elif pc == "TERM_DEPOSIT":
        tm = _parse_term_months(ribbon, flat_base)
        parts.append(f"{tm}M" if tm else "OTHER_TERM")
        ip = str(ribbon.get("interest_payment") or "").strip()
        parts.append(_INTEREST_PAYMENT_MAP.get(ip, "OTHER"))
        has_tier = _is_set(ribbon.get("balance_min")) or _is_set(ribbon.get("balance_max"))
        parts.append("TIERED" if has_tier else "FLAT")

    elif pc == "CREDIT_CARD":
        parts.append(rate_token)

    elif pc == "PERSONAL_LOAN":
        rep = str(ribbon.get("ribbon_repayment_type") or "").strip()
        parts.append(_REPAYMENT_MAP.get(rep, "OTHER"))
        parts.append(rate_token)
        if rate_token == "FIXED":
            tm = _parse_term_months(ribbon, flat_base)
            parts.append(f"{tm}M" if tm in _TERM_STANDARD else "OTHER_TERM")

    elif pc == "OVERDRAFT":
        parts.append(rate_token)
        if rate_token == "FIXED":
            tm = _parse_term_months(ribbon, flat_base)
            parts.append(f"{tm}M" if tm in _TERM_STANDARD else "OTHER_TERM")

    return ".".join(parts)


# Summary helper (used by xlsx builder)
# ──────────────────────────────────────────────────────────────────────────────

def build_taxonomy_summary(
    rows: list[dict[str, Any]],
    path_col: str = "taxonomy_path",
) -> list[dict[str, Any]]:
    """Aggregate rows by taxonomy_path; return sorted list of {path, count}."""
    counts: dict[str, int] = {}
    for row in rows:
        path = str(row.get(path_col) or "UNKNOWN")
        counts[path] = counts.get(path, 0) + 1
    return [{"taxonomy_path": p, "count": c} for p, c in sorted(counts.items())]


# ──────────────────────────────────────────────────────────────────────────────
# Standard vs non-standard account classification
# ──────────────────────────────────────────────────────────────────────────────
#
# Goal: keep the dashboard's default view to mainstream retail products (plain
# savings / transaction / at-call accounts, vanilla personal term deposits, home
# loans, etc.) while letting the user opt in to everything else — foreign-currency
# accounts, farm/agribusiness accounts, business/commercial accounts, trust & SMSF
# accounts, and so on.
#
# Two complementary signals make this FUTURE-PROOF rather than a fixed blocklist —
# a product is "non_standard" if EITHER fires:
#
#   1. Its name matches a non-standard marker below. This catches products the
#      bank mis-files under a standard category (e.g. CommBank's "Foreign Currency
#      Account" is published under TRANS_AND_SAVINGS_ACCOUNTS).
#   2. Its CDR productCategory is not one of the standard retail categories we
#      model. This auto-flags both today's other categories (FOREIGN_CURRENCY,
#      BUSINESS_LOANS, MARGIN_LOANS, LEASES, TRADE_FINANCE, REGULATED_TRUST_ACCOUNTS,
#      …) AND any new category enum value the CDR adds in future — i.e. account
#      types that are not yet in our data.
#
# TO EXTEND: add a phrase to ``_NON_STANDARD_NAME_TERMS`` (the single source of
# truth for name markers). Standard categories are reused from ``_CATEGORY_TO_PC``.

ACCOUNT_CLASS_STANDARD = "standard"
ACCOUNT_CLASS_NON_STANDARD = "non_standard"

# The retail CDR product categories we treat as standard. Reuses the canonical
# alias keys maintained in _CATEGORY_TO_PC (so the two never drift) but EXCLUDES
# the business-lending keys — a business loan with a neutral name (e.g. "Equipment
# Finance") must fall through to non_standard via the category catch-all rather
# than passing as standard.
STANDARD_CATEGORIES: frozenset[str] = frozenset(
    key for key in _CATEGORY_TO_PC if "BUSINESS" not in key
)

# Name markers that flag an account as non-standard. Generic words are anchored
# with \b so they never match inside an unrelated word ("farm" in "Platform",
# "agri" in a brand name). Multi-word phrases tolerate space/underscore/hyphen
# joins. Deliberately NOT included: "community" / "society" — they collide with
# Australian mutual-ADI brand names (building societies, community credit unions)
# whose ordinary retail savers must stay standard. Add new phrases here.
_NON_STANDARD_NAME_TERMS: tuple[str, ...] = (
    # Foreign exchange / multi-currency
    r"foreign[\s_-]*currenc(?:y|ies)", r"foreign[\s_-]*exchange", r"\bfx\b", r"\bforex\b",
    r"multi[\s_-]*currency", r"non[\s_-]*resident", r"\bmigrant\b", r"\bexpat\b",
    r"\boverseas\b", r"\boffshore\b",
    # Farm / agribusiness / rural
    r"\bfarm\b", r"\bagri\b", r"\bagribusiness\b", r"\brural\b", r"primary[\s_-]*producer",
    # Business / commercial / corporate
    r"\bbusiness\b", r"\bcommercial\b", r"\bcorporate\b", r"\bcompany\b", r"\bsme\b",
    r"\bmerchant\b", r"\bwholesale\b", r"\binstitutional\b",
    # Trust / SMSF / super / statutory
    r"\btrust\b", r"\btrustee\b", r"\bsmsf\b", r"self[\s_-]*managed", r"super[\s_-]*fund",
    r"\bstatutory\b", r"regulated[\s_-]*trust", r"\bescrow\b", r"\bsettlement\b",
    # Club / association / charity (organisation accounts)
    r"\bclub\b", r"\bassociation\b", r"\bcharit", r"not[\s_-]*for[\s_-]*profit",
    # At-call savings — depositors can withdraw on demand; treated as non-standard.
    # (Only ever appears in deposit product names, so it is safe to keep universal.)
    r"at[\s_-]*call",
)

_NON_STANDARD_NAME_RE = re.compile(
    r"(?:" + r"|".join(_NON_STANDARD_NAME_TERMS) + r")",
    re.IGNORECASE,
)

# Lending-only markers — these are applied ONLY to home-lending products
# (dataset "Mortgage" or a HOME_LOAN category). They flag products that banks
# file under RESIDENTIAL_MORTGAGES but are not standard owner-occupier/investor
# home loans: line-of-credit / equity release (e.g. Bank of Sydney "Home Equity
# Maximiser"), bridging finance, green / clean-energy purchase loans (e.g. RACQ
# "Green Home Loan"), and construction / land loans. Scoping them to lending
# avoids false hits on deposit products such as a "Green Saver" (Codex PR #146).
_NON_STANDARD_LENDING_TERMS: tuple[str, ...] = (
    r"home[\s_-]*equity", r"equity[\s_-]*(?:maximiser|maximizer|release|access|line|loan)",
    r"line[\s_-]*of[\s_-]*credit", r"\bheloc\b",
    r"\bbridging\b", r"bridge[\s_-]*loan",
    r"\bgreen\b", r"\bsolar\b", r"clean[\s_-]*energy",
    r"\bconstruction\b", r"\bland[\s_-]*loan", r"vacant[\s_-]*land",
)

_NON_STANDARD_LENDING_RE = re.compile(
    r"(?:" + r"|".join(_NON_STANDARD_LENDING_TERMS) + r")",
    re.IGNORECASE,
)

# Categories that resolve to a home loan — used to scope the lending-only markers
# when the caller does not pass dataset="Mortgage".
_HOME_LOAN_CATEGORIES: frozenset[str] = frozenset(
    key for key, pc in _CATEGORY_TO_PC.items() if pc == "HOME_LOAN"
)

# Eligibility-restricted cohorts → non-standard, matched on the genuine RESTRICTION
# (in the product name OR the CDR eligibility free-text), NOT the bank name. This
# is deliberate: "Defence Bank", "Australian Military Bank", "Police Bank",
# "Teachers Mutual" are ordinary ADIs whose standard products must stay standard,
# so we never flag on a brand — only on a real restriction like "served in the
# Defence Force", a veterans'-affairs requirement, or an SMSF/self-managed-super
# trust. High precision (validated against the live feed: veterans / DHOAS / SMSF
# specials only, no credit-union "members only" or company-borrower false hits).
_RESTRICTED_COHORT_RE = re.compile(
    r"\bveterans?\b|served\s+in\s+the\s+defence|defence[\s_-]*force"
    r"|armed[\s_-]*forces|military[\s_-]*service|\bdhoas\b"
    r"|\bsmsf\b|self[\s_-]*managed[\s_-]*super|ato[\s_-]*regulated\s+(?:trust|fund|self)",
    re.IGNORECASE,
)

# CDR eligibility can state who is excluded as well as who qualifies. A cohort token
# after exclusion/negation wording (e.g. "not available to SMSF borrowers") must not
# flip an otherwise standard product to non_standard.
_COHORT_EXCLUSION_PREFIX_RE = re.compile(
    r"(?:"
    r"not\s+(?:available|eligible|open|offered|applicable|accessible)(?:\s+to|\s+for)?\b"
    r"|not\s+for\s+"
    r"|unavailable\s+to\b"
    r"|excluding\b"
    r"|except\s+(?:for\s+)?"
    r"|does\s+not\s+(?:apply|extend)(?:\s+to|\s+for)?\b"
    r"|must\s+not\s+be\b"
    r")",
    re.IGNORECASE,
)

# Postfix exclusion within the same clause as the cohort token.
_COHORT_EXCLUSION_SUFFIX_RE = re.compile(
    r"(?:"
    r"\s+(?:are\s+)?not\s+(?:eligible|available|open|offered|permitted|allowed|accepted)\b"
    r"|\s+(?:are\s+)?excluded\b"
    r"|\s+must\s+not\s+be\b"
    r"|\s+(?:is|are)\s+unavailable\b"
    r")",
    re.IGNORECASE,
)

_CLAUSE_BOUNDARY_RE = re.compile(r"[.;!?]\s+")


def _clause_bounds(text: str, match_start: int, match_end: int) -> tuple[int, int]:
    """Return [start, end) slice bounds for the clause containing the cohort match."""
    clause_start = 0
    for m in _CLAUSE_BOUNDARY_RE.finditer(text[:match_start]):
        clause_start = m.end()
    tail = text[match_end:]
    m = _CLAUSE_BOUNDARY_RE.search(tail)
    clause_end = match_end + m.start() + 1 if m else len(text)
    return clause_start, clause_end


def _eligibility_text(eligibility: Any) -> str:
    """Join CDR eligibility free-text (additionalInfo/additionalValue) for scanning."""
    if not isinstance(eligibility, (list, tuple)):
        return ""
    parts: list[str] = []
    for item in eligibility:
        if isinstance(item, Mapping):
            info = item.get("additionalInfo")
            if info is not None and info != "":
                parts.append(str(info))
            val = item.get("additionalValue")
            if val is not None and val != "":
                parts.append(str(val))
    return " ".join(parts)


def _eligibility_item_text(item: Mapping[str, Any]) -> str:
    """Free-text from one CDR eligibility dict (info + value, same entry only)."""
    parts: list[str] = []
    for key in ("additionalInfo", "additionalValue"):
        val = item.get(key)
        if val is not None and val != "":
            parts.append(str(val))
    return " ".join(parts)


def _eligibility_restricted_cohort(text: str) -> bool:
    """True when eligibility text requires a restricted cohort (not merely excludes one)."""
    for match in _RESTRICTED_COHORT_RE.finditer(text):
        clause_start, clause_end = _clause_bounds(text, match.start(), match.end())
        clause = text[clause_start:clause_end]
        rel_start = match.start() - clause_start
        rel_end = match.end() - clause_start
        prefix = clause[:rel_start]
        suffix = clause[rel_end:]
        if _COHORT_EXCLUSION_PREFIX_RE.search(prefix):
            continue
        if _COHORT_EXCLUSION_SUFFIX_RE.search(suffix):
            continue
        return True
    return False


def _normalize_category_token(value: Any) -> str:
    """Upper-snake category token (e.g. 'Trans and Savings' -> 'TRANS_AND_SAVINGS').

    Kept local so cdr_taxonomy stays a no-upward-import leaf module; mirrors
    cdr_ingest_support.normalize_category_token.
    """
    text = str(value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def classify_account_standardness(
    product_name: Any,
    category: Any = "",
    dataset: Optional[str] = None,
    eligibility: Any = None,
) -> str:
    """Return 'standard' or 'non_standard' for a product/account.

    ``dataset`` scopes the lending-only markers: they are applied only to
    home-lending products (dataset "Mortgage" or a HOME_LOAN category), so a
    deposit product like "Green Saver" is not caught by the loan markers.
    ``eligibility`` is the CDR eligibility array; a restricted cohort there
    (veterans / defence service / SMSF) flags the product non-standard even when
    the name looks ordinary (e.g. Westpac "Flexi First … Veterans" at 3.25%, AMP
    Superedge SMSF, DHOAS, NAB Defence Force Home Loan).
    """
    name = str(product_name or "")
    token = _normalize_category_token(category)
    if name and _NON_STANDARD_NAME_RE.search(name):
        return ACCOUNT_CLASS_NON_STANDARD
    is_home_lending = dataset == "Mortgage" or token in _HOME_LOAN_CATEGORIES
    if is_home_lending and name and _NON_STANDARD_LENDING_RE.search(name):
        return ACCOUNT_CLASS_NON_STANDARD
    # Eligibility-restricted cohorts — by the restriction in the name OR the CDR
    # eligibility text, never the bank brand.
    if _RESTRICTED_COHORT_RE.search(name):
        return ACCOUNT_CLASS_NON_STANDARD
    if eligibility and isinstance(eligibility, (list, tuple)):
        for item in eligibility:
            if isinstance(item, Mapping):
                item_text = _eligibility_item_text(item)
                if item_text and _eligibility_restricted_cohort(item_text):
                    return ACCOUNT_CLASS_NON_STANDARD
    if token and token not in STANDARD_CATEGORIES:
        return ACCOUNT_CLASS_NON_STANDARD
    return ACCOUNT_CLASS_STANDARD
