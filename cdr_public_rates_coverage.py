"""Public provider/category baseline independent of the availability of prices."""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit

from cdr_public_rates_sources import source_inventory

SECTIONS = ("Mortgage", "Savings", "TD")


def _register_identity(brand: dict) -> str:
    if brand.get("dataHolderBrandId"):
        return "public-register-brand:" + brand["dataHolderBrandId"]
    if brand.get("interimId"):
        return "public-register-interim:" + brand["interimId"]
    raise ValueError("public_register_brand_identity_missing")


def coverage_baseline(register: dict, core: dict, *, register_sha256: str, core_sha256: str) -> dict:
    """Report current public register coverage without endorsing legacy rates.

    Exact public register brand names bind inventory here. A legacy payload's
    provider-name mismatch stays explicit until the official brand identity is
    reconciled; ownership, ABN and similarly named brands do not imply pricing.
    """
    brands = register.get("data")
    if not isinstance(brands, list):
        raise ValueError("public_register_summary_array_required")
    banking = [brand for brand in brands if "banking" in brand.get("industries", [])]
    inventory, seen = [], set()
    failures = core.get("coverage", {}).get("provider_failures", [])
    for brand in banking:
        identity = _register_identity(brand)
        if identity in seen:
            raise ValueError("duplicate_public_register_brand")
        seen.add(identity)
        name = brand["brandName"]
        host = urlsplit(brand["publicBaseUri"]).hostname
        if not host:
            raise ValueError("public_register_brand_origin_missing")
        for section in SECTIONS:
            rows = [row for row in core.get("sections", {}).get(section, {}).get("rates", [])
                    if row["provider"].casefold() == name.casefold()]
            count = len({row.get("product_key") or row.get("product_id") for row in rows})
            issues = [failure for failure in failures if failure["provider"].casefold() == name.casefold()]
            inventory.append({"providerId": identity, "providerName": name, "section": section,
                "sourceStatus": "partial" if issues else "legacy_payload_observed" if rows else "unavailable",
                "resolutionStatus": "unvalidated_legacy_pricing", "structuredCDR": "not_recompiled_in_baseline",
                "products": count, "programmesWithFormula": 0,
                "reasonCodes": ["legacy_payload_is_not_public_rate_validation"] + ([] if rows else ["no_matching_legacy_rate_rows"])})
    value = source_inventory(inventory)
    registered = {_register_identity(brand): brand for brand in banking}
    for entry in value["coverage"]:
        brand = registered[entry["providerId"]]
        entry.update(publicCDRBaseUrl=brand["publicBaseUri"], publicABN=brand.get("abn"),
                     legalLenderStatus="public_register_identifier_only", freshness="not_a_live_source_check",
                     providerIdentityStatus="interim" if brand.get("interimId") and not brand.get("dataHolderBrandId") else "registered")
    published_names = {row["provider"] for section in core.get("sections", {}).values() for row in section.get("rates", [])}
    register_names = {brand["brandName"].casefold() for brand in banking}
    return {**value, "baselineRunDate": core["run_date"],
        "evidence": [{"role": "official_public_register", "sha256": register_sha256,
                      "url": register.get("links", {}).get("self")},
                     {"role": "selected_public_core", "sha256": core_sha256}],
        "counts": {"providersInPublicBankingRegister": len(banking), "providerCategories": len(value["coverage"]),
            "registeredReferenceDocuments": len({source["url"] for source in value["sources"]}),
            "selectedIngest": core.get("coverage", {}).get("counts", {}),
            "coverageStates": dict(Counter(entry["sourceStatus"] for entry in value["coverage"]))},
        "legacyProviderNamesRequiringIdentityReconciliation": sorted(name for name in published_names if name.casefold() not in register_names),
        "publication": "disabled", "activation": "not_performed"}
