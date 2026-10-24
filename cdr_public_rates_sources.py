"""Versioned public source register, extended by every observed provider/category."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from cdr_terms.identity import digest


REGISTER_PATH = Path(__file__).parent / "contracts" / "public_rates" / "public-source-register-v1.json"


def reviewed_register() -> dict:
    value = json.loads(REGISTER_PATH.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != 1 or value.get("publicOnly") is not True:
        raise ValueError("invalid_public_source_register")
    seen = set()
    for source in value["sources"]:
        url = urlsplit(source["url"])
        if (source["sourceId"] in seen or url.scheme != "https" or url.username or url.password
                or url.hostname not in source["allowedHosts"] or source["adapterVersion"] != "1"):
            raise ValueError("invalid_public_source_register")
        seen.add(source["sourceId"])
    return value


def source_inventory(inventory: list[dict]) -> dict:
    """Include unsupported and newly discovered providers, never guess references."""
    register = reviewed_register()
    sources, coverage = [], []
    seen = set()
    for item in inventory:
        identity = (item["providerId"], item["section"])
        if identity in seen:
            continue
        seen.add(identity)
        name = item["providerName"]
        matches = [source for source in register["sources"] if name.casefold() in {
            alias.casefold() for alias in source["providerAliases"]} and item["section"] in source["sections"]]
        for source in matches:
            sources.append({**source, "providerId": item["providerId"], "providerName": name,
                            "registeredSourceId": source["sourceId"],
                            "sourceId": source["sourceId"] + ":" + digest(item["providerId"])[:16]})
        coverage.append({"providerId": item["providerId"], "providerName": name, "section": item["section"],
            "sourceStatus": item.get("sourceStatus", "unknown"),
            "referenceSourceStatus": "registered" if matches else "no_registered_reference_source",
            "resolutionStatus": item.get("resolutionStatus", "unresolved"), "costCompleteness": "unknown", "publicationStatus": "disabled",
            "products": item.get("products", 0), "programmesWithFormula": item.get("programmesWithFormula", 0),
            "reasonCodes": sorted(set(item.get("reasonCodes", []) + ([] if matches else ["reference_source_coverage_gap"]))),
            "structuredCDR": item.get("structuredCDR", item.get("sourceStatus", "unknown"))})
    return {"schemaVersion": 1, "registerVersion": register["registerVersion"], "publicOnly": True,
            "sources": sorted(sources, key=lambda source: source["sourceId"]),
            "coverage": sorted(coverage, key=lambda item: (item["providerId"], item["section"]))}


def reference_ids_for_product(product: dict, references: list[dict]) -> list[str]:
    """Only reviewed exact product aliases grant reference-family discovery."""
    sources = reviewed_register()["sources"]
    name = product["name"].casefold()
    prefixes = {prefix for source in sources if product["providerName"].casefold() in {
        alias.casefold() for alias in source["providerAliases"]}
        for binding in source.get("productBindings", []) if name in {alias.casefold() for alias in binding["aliases"]}
        for prefix in binding["referenceNamePrefixes"]}
    return sorted({rate["referenceId"] for rate in references if rate["providerId"] == product["providerId"]
                   and any(rate["name"].casefold().startswith(prefix.casefold()) for prefix in prefixes)})
