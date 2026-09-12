"""Source-backed, rate-local restrictions for savings competition prizes.

These are rate conditions, never product-wide eligibility. Do not infer them
from a provider, product name, headline magnitude or a mention of a competition.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_WINNERS_ONLY = re.compile(
    r"(?:^|[.!?]\s+)(?:(?:this|the) (?:promotional |fixed )?rate is )?"
    r"(?:available only|offered only|only available|only offered) to "
    r"(?:eligible )?winners?\b", re.IGNORECASE,
)
_MONTH_WORDS = dict(zip(
    "one two three four five six seven eight nine ten eleven twelve".split(), range(1, 13)
))
_PROMO_MONTHS = re.compile(
    r"\bpromotional rate applies for (\d+|" + "|".join(_MONTH_WORDS) + r") months?\b",
    re.IGNORECASE,
)


def savings_rate_conditions(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Retain rate and tier condition records with their original scope."""
    out: list[dict[str, Any]] = []
    scopes = [("Rate", item)]
    tiers = item.get("tiers")
    if isinstance(tiers, list):
        scopes.extend((f"Tier {i}", tier) for i, tier in enumerate(tiers, 1)
                      if isinstance(tier, Mapping))
    for scope, record in scopes:
        info = record.get("additionalInfo")
        if isinstance(info, str) and info.strip():
            out.append({"label": f"{scope} information", "info": info})
        conditions = record.get("applicabilityConditions")
        if not isinstance(conditions, list):
            continue
        for condition in conditions:
            if not isinstance(condition, Mapping):
                continue
            out.append({
                "label": f"{scope}: {condition.get('rateApplicabilityType') or 'Condition'}",
                **{key: condition[source] for key, source in (
                    ("info", "additionalInfo"), ("value", "additionalValue")
                ) if source in condition},
            })
    return out


def winner_rate_evidence(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = savings_rate_conditions(item)
    return evidence if any(_WINNERS_ONLY.search(str(row.get("info") or ""))
                           for row in evidence) else []


def winner_rate_ribbons(item: Mapping[str, Any]) -> dict[str, str]:
    evidence = winner_rate_evidence(item)
    if not evidence:
        return {}
    out = {"account_class": "non_standard"}
    durations = set()
    for row in evidence:
        for match in _PROMO_MONTHS.finditer(str(row.get("info") or "")):
            token = match[1].lower()
            durations.add(int(token) if token.isdigit() else _MONTH_WORDS[token])
    # A finite explicitly promotional window supports the existing intro facet.
    # Conflicting/absent terms remain disclosed as text, without a made-up term.
    if len(durations) == 1 and next(iter(durations)) > 0:
        out.update(term_months=str(next(iter(durations))), ribbon_deposit_kind="introductory")
    return out


def winner_rate_disclosures(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use informational features, not shared eligibility that taints siblings."""
    rates = record.get("depositRates")
    if not isinstance(rates, list):
        return []
    out = []
    for index, item in enumerate(rates, 1):
        if not isinstance(item, Mapping):
            continue
        for condition in winner_rate_evidence(item):
            out.append({**condition, "name": f"Deposit rate {index} ({item.get('depositRateType', '')})"})
    return out
