"""Independent acceptance against retained public lender responses."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cdr_domain.public_pricing_validation import validate_wire
from cdr_public_rates_reference import extract_reference
from cdr_public_rates_reference_dynamic import _jsonp
from cdr_public_rates_sources import reviewed_register

ROOT = Path(__file__).parent / "fixtures" / "public_rates"
PROFILES = json.loads((Path(__file__).parents[1] / "contracts/public_rates/reviewed-source-shapes-v1.json").read_bytes())


def capture(key):
    source = next(item for item in reviewed_register()["sources"] if item["sourceId"] == key)
    profile = PROFILES["sources"][key]
    body = (ROOT / profile["fixture"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == profile["sha256"]
    context = {**source, "providerId": source["legalLender"], "sourceUrl": source["url"],
               "sourceSha256": profile["sha256"], "checkedAt": "2026-10-14T11:50:00Z"}
    return body, context


@pytest.mark.parametrize("key", [source["sourceId"] for source in reviewed_register()["sources"]])
def test_retained_public_capture_and_evidence_binding(key):
    body, context = capture(key)
    result = extract_reference(body, context)
    assert result["status"] == "validated"
    assert len(result["referenceRates"]) == PROFILES["sources"][key]["referenceRows"]
    for evidence in result["evidence"]:
        validate_wire(evidence, "Evidence")
        assert evidence["sha256"] == hashlib.sha256(body).hexdigest()
        assert evidence["url"] == context["sourceUrl"]


def test_independent_nab_and_cba_reference_values_and_scope():
    result = extract_reference(*capture("nab-indicator"))
    rate = next(item for item in result["referenceRates"] if item["name"] == "Variable Rate for Home Loans (Standard Variable Rate)")
    assert rate["value"] == "9.02" and rate["unit"] == "percentage_points"
    assert rate["effectiveFrom"] == "2026-10-12T00:00:00+11:00"
    assert {item["field"]: item["value"] for item in rate["conditions"]} == {"purpose": "OWNER_OCCUPIED", "repayment": "PRINCIPAL_AND_INTEREST"}
    cba = extract_reference(*capture("cba-reference"))["referenceRates"]
    standard = next(rate for rate in cba if rate["name"] == "Standard Variable Rate (Complete) reference - owner occupied - principal and interest")
    fixed = next(rate for rate in cba if rate["name"] == "1 year fixed reference - owner occupied - principal and interest")
    assert standard["value"] == "9.05"
    assert fixed["value"] == "6.93"  # Reference column, not 6.78 package/net column.


def test_public_dynamic_feed_values_units_dates_and_blank_rows():
    ing = extract_reference(*capture("ing-reference-data"))["referenceRates"]
    owner = next(rate for rate in ing if rate["name"] == "Orange Advantage reference - owner occupied - principal and interest")
    assert owner["value"] == "8.65" and owner["effectiveFrom"] == "2026-10-08T13:00:00Z"
    anz = extract_reference(*capture("anz-owner-index"))["referenceRates"]
    standard = next(rate for rate in anz if rate["name"] == "ANZ Standard Variable Rate - Principal and Interest")
    assert standard["value"] == "8.89"
    absent = [rate for rate in anz if "value" not in rate]
    assert len(absent) == 2
    assert {rate["conditions"][-1]["value"] for rate in absent} == {"84", "120"}


def test_reference_identity_survives_json_array_reordering():
    body, context = capture("ing-reference-data")
    old = extract_reference(body, context)
    changed = json.loads(body)
    changed["InterestRates"].reverse()
    new = extract_reference(json.dumps(changed).encode(), context)
    assert new["status"] == "validated"
    assert {r["name"]: r["referenceId"] for r in old["referenceRates"]} == {r["name"]: r["referenceId"] for r in new["referenceRates"]}
    assert old["evidence"] != new["evidence"]  # Original occurrence pointers remain separate.


def test_price_change_publishes_but_material_unit_change_requires_review():
    body, context = capture("anz-owner-index")
    changed = _jsonp(body)
    section = changed["productdata"][0]["country"][0]["interestrates"][0]["section"][0]
    group = next(g for g in section["subsection"] if g["code"] == "VR")
    row = next(r for r in group["baserate"] if r["code"] == "VRI")
    row["ratevalue"] = "9.02"  # Metamorphic price-only update using a retained public rate.
    encode = lambda: ("callbackFunction(" + json.dumps(changed) + ")").encode()
    assert extract_reference(encode(), context)["status"] == "validated"
    row["ratesuffix"] = "basis points"
    assert extract_reference(encode(), context)["status"] == "review_required"


def test_blank_static_table_and_code_execution_are_never_rates():
    body, context = capture("westpac-reference")
    changed = body.replace(b"8.43% p.a.", b"")
    result = extract_reference(changed, context)
    assert result["status"] == "unresolved" and result["referenceRates"] == []
    body, context = capture("anz-owner-index")
    result = extract_reference(body + b"; executeSomething()", context)
    assert result["status"] == "unresolved" and result["referenceRates"] == []


def test_malformed_public_document_is_unresolved():
    _, context = capture("nab-indicator")
    assert extract_reference(b"%PDF-malformed", context)["status"] == "unresolved"
    _, context = capture("ing-reference-data")
    assert extract_reference(b'{"InterestRates":[{}]}', context)["status"] == "unresolved"
