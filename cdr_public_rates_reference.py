"""Reviewed reference adapters with material-shape approval bound to fixtures."""
from __future__ import annotations

import json
from pathlib import Path

from cdr_terms.identity import digest
from cdr_public_rates_reference_common import AdapterUnresolved
from cdr_public_rates_reference_pdf import nab, cba
from cdr_public_rates_reference_dynamic import anz, ing, westpac, dynamic_page


ADAPTERS = {"nab_indicator": nab, "cba_reference": cba, "westpac_reference": westpac,
            "anz_index_data": anz, "ing_reference_data": ing,
            "anz_index_page": dynamic_page, "ing_reference_page": dynamic_page}
PROFILES = Path(__file__).parent / "contracts" / "public_rates" / "reviewed-source-shapes-v1.json"


def extract_reference(body: bytes, context: dict) -> dict:
    """No baseline learned from live data, no model call, no override switch."""
    adapter = ADAPTERS.get(context.get("adapterId"))
    if adapter is None or context.get("adapterVersion") != "1":
        return {"status": "unresolved", "reasonCode": "unsupported_reference_adapter",
                "referenceRates": [], "evidence": [], "semanticSha256": digest(["unsupported", context.get("adapterId")])}
    try:
        result = adapter(body, context)
    except AdapterUnresolved as error:
        return {"status": "unresolved", "reasonCode": str(error), "referenceRates": [], "evidence": [],
                "semanticSha256": digest(["unresolved", str(error)])}
    except (KeyError, TypeError, IndexError, AttributeError, UnicodeError):
        return {"status": "unresolved", "reasonCode": "malformed_public_reference_source",
                "referenceRates": [], "evidence": [], "semanticSha256": digest(["malformed"])}
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    profile = profiles["sources"].get(context["profileId"])
    if (not profile or profile["adapterVersion"] != context["adapterVersion"]
            or profile["semanticSha256"] != result["semanticSha256"]):
        return {**result, "status": "review_required", "reasonCode": "material_source_structure_changed"}
    return {**result, "status": "validated", "reasonCode": None}
