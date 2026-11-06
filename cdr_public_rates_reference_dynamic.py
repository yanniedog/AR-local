"""Public table and backing-data adapters; JSONP is parsed, never executed."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from cdr_terms.identity import digest
from cdr_public_rates_reference_common import (
    AdapterUnresolved, australian_date, html, reference, semantic_text,
)


def westpac(body: bytes, context: dict) -> dict:
    page = html(body)
    text = semantic_text(" ".join(page.fragments))
    if "reference rate is your variable interest rate before any discount or margin" not in text:
        raise AdapterUnresolved("reference_definition_changed")
    rates, evidence, normalized = [], [], []
    table = 0
    for row_number, row in enumerate(page.rows, 1):
        if row[:2] == ["Term", "Interest rate"]:
            table += 1
            normalized.append(row)
            continue
        if table not in (1, 2) or len(row) != 3 or not row[0]:
            normalized.append(row)
            continue
        found = re.fullmatch(r"(\d+\.\d+)% p\.a\.", row[1])
        comparison = re.fullmatch(r"(\d+\.\d+)% p\.a\.", row[2])
        if not found or not comparison:
            # Do not turn a blank dynamic value into zero.
            raise AdapterUnresolved("empty_dynamic_table")
        scope = {"purpose": "OWNER_OCCUPIED" if table == 1 else "INVESTMENT",
                 "repayment": "INTEREST_ONLY" if "Interest Only" in row[0] else "PRINCIPAL_AND_INTEREST"}
        if "SMSF" in row[0]:
            scope["customerCategory"] = "SMSF"
        rate, source = reference(context, row[0], row[0], found[1], {"table": table, "row": row_number, "column": "Interest rate", "text": row[0]}, scope=scope)
        rates.append(rate)
        evidence.append(source)
        normalized.append([row[0], "$RATE", "$COMPARISON"])
        text = text.replace(row[1], "$RATE").replace(row[2], "$COMPARISON")
    if len(rates) != 14:
        raise AdapterUnresolved("reference_table_inventory_changed")
    # This page states no effective date. Its check date never becomes one.
    return {"referenceRates": rates, "evidence": evidence,
            "semanticSha256": digest({"tables": normalized, "text": text})}


def dynamic_page(body: bytes, context: dict) -> dict:
    page = html(body)
    text = semantic_text(" ".join(page.fragments))
    lender = context["adapterId"]
    required = ["home loan reference rates"] if lender == "ing_reference_page" else ["home loan interest rates", "index"]
    if any(term not in text.casefold() for term in required):
        raise AdapterUnresolved("reference_heading_changed")
    # This is a reviewed shape and applicability check, not a numerical capture.
    return {"referenceRates": [], "evidence": [], "semanticSha256": digest({"text": text, "mappings": page.mappings})}


ING_FAMILIES = {
    "OA": "Orange Advantage", "MS": "Mortgage Simplifier", "CL": "Construction Loan",
    "SHL": "Smart Home Loan", "AEL": "Action Equity Loan",
}


def _net_date(value: str, *, missing=False) -> str | None:
    found = re.fullmatch(r"/Date\((-?\d+)([+-]\d{4})?\)/", str(value))
    if not found:
        raise AdapterUnresolved("effective_date_unresolved")
    number = int(found[1])
    if missing and number == -62135550000000:
        return None
    try:
        return datetime.fromtimestamp(number / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError) as error:
        raise AdapterUnresolved("effective_date_unresolved") from error


def ing(body: bytes, context: dict) -> dict:
    try:
        document = json.loads(body, parse_float=str)
        records = document["InterestRates"]
    except (ValueError, KeyError, TypeError) as error:
        raise AdapterUnresolved("invalid_public_backing_data") from error
    if not isinstance(records, list) or len(records) > 5000:
        raise AdapterUnresolved("invalid_public_backing_data")
    rates, evidence, structure, seen = [], [], [], set()
    for index, record in enumerate(records):
        code = record.get("RateCode", "") if isinstance(record, dict) else ""
        found = re.fullmatch(r"(OA|MS|CL|SHL|AEL)_(OO|INV)(_IO)?_REF", code)
        if not found:
            continue
        if code in seen:
            raise AdapterUnresolved("conflicting_reference_rows")
        seen.add(code)
        family, purpose, io = found.groups()
        if record.get("Product") != "OTHER":
            raise AdapterUnresolved("reference_product_scope_changed")
        scope = {"purpose": "OWNER_OCCUPIED" if purpose == "OO" else "INVESTMENT",
                 "repayment": "INTEREST_ONLY" if io else "PRINCIPAL_AND_INTEREST"}
        name = f"{ING_FAMILIES[family]} reference - {scope['purpose'].replace('_', ' ').lower()} - {scope['repayment'].replace('_',' ').lower()}"
        rate, source = reference(context, code, name, record.get("Rate"), {"pointer": f"/InterestRates/{index}", "rateCode": code},
            effective_from=_net_date(record.get("ValidFrom")), effective_to=_net_date(record.get("ValidTo"), missing=True), scope=scope)
        rates.append(rate)
        evidence.append(source)
        structure.append({"code": code, "product": record["Product"], "fields": sorted(record)})
    if len(rates) != 14:
        raise AdapterUnresolved("reference_code_inventory_changed")
    return {"referenceRates": rates, "evidence": evidence, "semanticSha256": digest(sorted(structure, key=lambda row: row["code"]))}


def _jsonp(body: bytes) -> dict:
    try:
        text = body.decode("utf-8-sig").strip()
        found = re.fullmatch(r"callbackFunction\((.*)\);?", text, re.S)
        if not found:
            raise AdapterUnresolved("unsupported_jsonp_wrapper")
        return json.loads(found[1], parse_float=str)
    except (ValueError, UnicodeError) as error:
        raise AdapterUnresolved("invalid_public_backing_data") from error


def anz(body: bytes, context: dict) -> dict:
    try:
        data = _jsonp(body)
        country = data["productdata"][0]["country"][0]
        sections = country["interestrates"][0]["section"]
        if country["code"] != "AU" or len(sections) != 1:
            raise AdapterUnresolved("country_section_scope_changed")
        section = sections[0]
        code = section["code"]
        if code not in {"PHL", "PRL"}:
            raise AdapterUnresolved("country_section_scope_changed")
        effective = australian_date(section["sectioneffectivedate"])
        groups = section["subsection"]
    except (KeyError, IndexError, TypeError) as error:
        raise AdapterUnresolved("invalid_public_backing_data") from error
    allowed = {"VR", "FR"} if code == "PHL" else {"IVR", "IFR", "IIAL"}
    rates, evidence, structure, seen = [], [], [], set()
    for group_index, group in enumerate(groups):
        if group.get("code") not in allowed:
            continue
        if group.get("isactive") != "1" or group.get("isfordisplay") != "1":
            raise AdapterUnresolved("reference_group_discontinued")
        shape = {key: value for key, value in group.items() if key != "baserate"}
        shape["baserate"] = []
        for rate_index, item in enumerate(group["baserate"]):
            if item["isactive"] != "1" or item["isfordisplay"] != "1":
                continue
            shape["baserate"].append({key: value for key, value in item.items() if key != "ratevalue"})
            if "Comparison" in item["ratetype"] or item.get("tiername2") == "Comparison Rate":
                continue
            if item["code"] in seen:
                raise AdapterUnresolved("reference_units_or_identity_changed")
            seen.add(item["code"])
            scope = {"purpose": "OWNER_OCCUPIED" if code == "PHL" else "INVESTMENT"}
            if group["code"] == "IIAL":
                scope["repayment"] = "INTEREST_ONLY"
                scope["custom"] = "interest_paid_in_advance"
            elif item["ratetype"] in {"Principal and Interest", "Interest Only"}:
                scope["repayment"] = "PRINCIPAL_AND_INTEREST" if item["ratetype"] == "Principal and Interest" else "INTEREST_ONLY"
            else:
                raise AdapterUnresolved("repayment_scope_unresolved")
            if item.get("tiername1"):
                term = re.fullmatch(r"([1-9]\d*) years?", item["tiername1"], re.I)
                if not term:
                    raise AdapterUnresolved("reference_term_unresolved")
                scope["termMonths"] = str(int(term[1]) * 12)
            name = f"{group['name']} - {item['ratetype']}" + (f" - {item['tiername1']}" if item.get('tiername1') else '')
            pointer = f"/productdata/0/country/0/interestrates/0/section/0/subsection/{group_index}/baserate/{rate_index}"
            value = item.get("ratevalue") if item["ratesuffix"] == "% p.a." else None
            rate, source = reference(context, item["code"], name, value, {"pointer": pointer, "rateCode": item["code"]}, effective_from=effective, scope=scope)
            rates.append(rate)
            evidence.append(source)
        structure.append(shape)
    if not rates or {item["code"] for item in structure} != allowed:
        raise AdapterUnresolved("reference_group_inventory_changed")
    return {"referenceRates": rates, "evidence": evidence,
            "semanticSha256": digest({"code": code, "disclaimer": section["sectiondisclaimer"], "groups": structure})}
