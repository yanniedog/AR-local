"""Conservative feature evidence for the existing optional mobile facts field."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from cdr_product_facts import compact_facts
from cdr_terms.discovery import document_url, reference_source_url

_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_NARRATIVE_NAMES = {
    "OFFSET": r"\boffsets?\b", "REDRAW": r"\bredraws?\b",
    "EXTRA_REPAYMENTS": r"\bextra[\s_-]+repayments?\b",
    "NPP_PAYID": r"\b(?:pay[\s_-]?ids?|npp|osko)\b",
    "CASHBACK_OFFER": r"\bcash[\s_-]?back\b",
    "UNLIMITED_TXNS": r"\bunlimited[\s_-]+(?:transactions?|txns?)\b",
    "FREE_TXNS": r"\bfree[\s_-]+(?:transactions?|txns?)\b",
    "CARD_ACCESS": r"\b(?:cards?|atms?)\b",
    "BILL_PAYMENT": r"\b(?:bpay|bill[\s_-]+payments?)\b",
    "DIGITAL_BANKING": r"\b(?:(?:digital|online|internet|mobile)[\s_-]+banking|banking[\s_-]+app)\b",
    "NOTIFICATIONS": r"\b(?:notifications?|alerts?)\b",
    "GUARANTOR": r"\bguarantors?\b",
    "OVERDRAFT": r"\boverdrafts?\b",
}


def source_documents(record: Mapping[str, Any]) -> list[dict] | None:
    """Reject malformed generated references before they reach mobile renderers."""
    references = record.get("sourceDocuments")
    if references is None:
        return None
    if not isinstance(references, list):
        raise ValueError("invalid_source_documents")
    for reference in references:
        if (not isinstance(reference, dict)
                or any(not isinstance(reference.get(key), str) or not reference[key].strip()
                       for key in ("url", "sourcePath", "relation"))
                or any(key in reference and not isinstance(reference[key], str)
                       for key in ("sourceUrl", "label", "sourceNormalization"))
                or ("sourceNormalization" in reference and "sourceUrl" not in reference)
                or document_url(reference["url"]) != reference["url"]
                or ("sourceUrl" in reference
                    and reference_source_url(reference["sourceUrl"],
                        reference.get("sourceNormalization")) != reference["url"])):
            raise ValueError("invalid_source_document_reference")
    return references


def feature_facts(record: Mapping[str, Any], product_key: str,
                  summary_description: Any = None) -> list[dict]:
    """Publish presence only for unqualified structured feature declarations.

    Free-text conditions, extra values and effective-date boundaries need an
    applicability assessment. Preserve those facts with an absent value, which
    existing clients treat as unknown. Text inference never grants eligibility.
    Negative/conflicting text remains a veto. Raw display fields remain intact.
    """
    source = record.get("features")
    features = [item for item in source if isinstance(item, dict)
                and isinstance(item.get("featureType"), str)
                and _CODE.fullmatch(item["featureType"])] if isinstance(source, list) else []
    restricted = {
        item["featureType"] for item in features
        if any(value not in (None, "") for key, value in item.items()
               if key != "featureType")
    }
    # Retain all source text for conservative contradiction detection, without
    # generating numeric rate/fee facts or interpreting their applicability.
    text = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in ("description", "additionalInfo") and isinstance(child, str):
                    text.append(child)
                elif isinstance(child, (Mapping, list)):
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(record)
    if isinstance(summary_description, str) and summary_description not in text:
        text.append(summary_description)
    narrative = "\n".join(text).lower()
    for item in features:
        words = item["featureType"].lower().split("_")
        pattern = _NARRATIVE_NAMES.get(item["featureType"],
                                      r"\b" + r"[\s_-]+".join(map(re.escape, words)) + r"\b")
        if re.search(pattern, narrative):
            restricted.add(item["featureType"])
    # Discovery retains raw pointers, but cleaning compacts empty list entries.
    # No original-to-cleaned index mapping is available in this frozen record.
    # Never guess which declaration a feature-scoped reference qualifies.
    references = record.get("sourceDocuments")
    for ref in references if isinstance(references, list) else []:
        pointer = str(ref.get("sourcePath", "")) if isinstance(ref, Mapping) else ""
        if not re.search(r"/features(?:/|$)", pointer):
            continue
        restricted.update(item["featureType"] for item in features)
    # A delimiter prevents words in different source fields forming one clause.
    evidence = {"features": features, "description": "; ".join(text)}
    dated = any(record.get(key) not in (None, "") for key in ("effectiveFrom", "effectiveTo"))
    result = []
    for fact in compact_facts(evidence, product_key):
        if fact["kind"] != "feature":
            continue
        if fact.get("value") is True and (dated or fact.get("sourceType") in restricted
                                         or fact.get("sourceType") == "canonical_text"):
            fact.pop("value")
        # The mobile identity includes this conservative projection, not the
        # stronger intermediate interpretation returned by compact_facts.
        identity = json.dumps([product_key, fact], sort_keys=True, ensure_ascii=False)
        fact["id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        result.append(fact)
    return result
