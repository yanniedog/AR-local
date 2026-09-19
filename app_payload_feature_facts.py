"""Conservative feature evidence for the existing optional mobile facts field."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from cdr_product_facts import compact_facts

_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def feature_facts(record: Mapping[str, Any], product_key: str) -> list[dict]:
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
    narrative = "\n".join(text).lower()
    for item in features:
        words = item["featureType"].lower().split("_")
        if re.search(r"\b" + r"[\s_-]+".join(map(re.escape, words)) + r"\b", narrative):
            restricted.add(item["featureType"])
    # The display cleaner removes URI fields. Discovery retains their original
    # pointers; any feature-scoped reference needs independent applicability.
    references = record.get("sourceDocuments")
    if isinstance(references, list) and any(
        isinstance(ref, Mapping) and "/features/" in str(ref.get("sourcePath", ""))
        for ref in references
    ):
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
