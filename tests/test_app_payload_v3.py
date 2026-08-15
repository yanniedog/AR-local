import json
import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cdr_domain import (
    contract_sha256,
    generation_manifest_digest,
    validate_asset_descriptor,
    validate_contract,
    validate_coverage_v2,
    validate_generation_manifest,
    validate_generation_pointer,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "v3"
SHA = "a" * 64

CAPS = {
    "core": (2 * 1024**2, 16 * 1024**2),
    "facets": (4 * 1024**2, 32 * 1024**2),
    "search": (8 * 1024**2, 64 * 1024**2),
    "v1_details_compatibility": (8 * 1024**2, 96 * 1024**2),
    "detail_index": (2 * 1024**2, 16 * 1024**2),
    "detail_shard": (4 * 1024**2, 32 * 1024**2),
    "history_summary": (8 * 1024**2, 64 * 1024**2),
    "bank_response": (16 * 1024**2, 128 * 1024**2),
    "spread": (8 * 1024**2, 64 * 1024**2),
    "rba": (1 * 1024**2, 4 * 1024**2),
    "exact_product_history": (32 * 1024**2, 256 * 1024**2),
    "economy": (2 * 1024**2, 16 * 1024**2),
}


def coverage():
    return {
        "products_discovered": 10,
        "products_priced": 8,
        "products_consumer_eligible": 6,
        "rate_tiers_eligible": 12,
        "providers_registered": 5,
        "providers_attempted": 5,
        "providers_responded": 5,
        "providers_complete": 4,
        "providers_empty": 1,
        "providers_partial": 0,
        "providers_failed": 0,
        "providers_not_attempted": 0,
        "register_sources_attempted": 1,
        "register_sources_complete": 1,
        "register_provenance_complete": True,
        "failure_records": 0,
        "corrupt_failure_records": 0,
        "exclusions_by_reason": {"transaction_account": 2, "mortgage_linked_offset": 2},
        "failure_provenance_complete": True,
        "reconciliation_status": "reconciled",
    }


def asset(capability="core", compressed=1024, uncompressed=4096):
    suffix = ".json.gz" if compressed != uncompressed else ".json"
    schema_id = (
        "https://australianrates.app/contracts/v3/canonical-core-v3.schema.json"
        if capability == "core"
        else f"https://australianrates.app/contracts/v3/{capability.replace('_', '-')}.schema.json"
    )
    return {
        "schema_id": schema_id,
        "media_type": "application/json",
        "encoding": "gzip" if compressed != uncompressed else "identity",
        "compressed_bytes": compressed,
        "uncompressed_bytes": uncompressed,
        "sha256": SHA,
        "url": f"https://github.com/yanniedog/AR-local/releases/download/app-payload-gen/{SHA}{suffix}",
        "cohort": "confirmed-consumer-products",
        "capability": capability,
    }


def manifest_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def head(value):
    encoded = manifest_bytes(value)
    manifest_sha = hashlib.sha256(encoded).hexdigest()
    return {
        "generation_id": value["generation_id"],
        "generation_revision": value["generation_revision"],
        "generation_digest": value["generation_digest"],
        "manifest_sha256": manifest_sha,
        "observation_date": value["observation_date"],
        "observation_state": value["observation_state"],
        "manifest_url": f"https://github.com/yanniedog/AR-local/releases/download/app-payload-gen/{manifest_sha}.json",
    }


def bind_manifest(value):
    digest = generation_manifest_digest(value)
    value["generation_digest"] = digest
    value["generation_id"] = (
        f"gen-{value['observation_date']}-r{value['generation_revision']:04d}-{digest[:12]}"
    )
    return value


def manifest(date="2026-08-14", state="complete", revision=1):
    return bind_manifest({
        "schema_version": 3,
        "generation_id": "",
        "generation_revision": revision,
        "generation_digest": "",
        "observation_date": date,
        "observed_at": f"{date}T09:30:00+10:00",
        "observation_state": state,
        "ledger_state": "finalized",
        "normalization_version": "canonical-v3-domain-v1",
        "producer_commit": "c" * 40,
        "coverage": coverage(),
        "prior_ledger_digest": None,
        "ledger_event_digest": "d" * 64,
        "capabilities": {"core": asset()},
    })


def pointer_bundle(observation_manifest=None, complete_manifest=None):
    complete_manifest = complete_manifest or manifest()
    observation_manifest = observation_manifest or complete_manifest
    pointer = {
        "schema_version": 3,
        "generated_at": "2026-08-14T10:00:00+10:00",
        "contract_sha256": contract_sha256(),
        "latest_observation": head(observation_manifest),
        "latest_complete": head(complete_manifest),
    }
    documents = {
        observation_manifest["generation_id"]: manifest_bytes(observation_manifest),
        complete_manifest["generation_id"]: manifest_bytes(complete_manifest),
    }
    return pointer, documents


def test_every_contract_is_valid_draft_2020_12_schema():
    for path in sorted(CONTRACTS.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_checked_in_contract_lock_matches_exact_schema_bytes_semantically():
    lock = json.loads((CONTRACTS / "contract-lock.json").read_text(encoding="utf-8"))
    assert lock["schemas"] == sorted(path.name for path in CONTRACTS.glob("*.schema.json"))
    assert lock["schema_set_sha256"] == contract_sha256()


def test_checked_in_golden_generation_documents_pass_runtime_validation():
    fixture_root = CONTRACTS / "fixtures"
    golden_manifest = json.loads(
        (fixture_root / "valid-generation-manifest-v3.json").read_text(encoding="utf-8")
    )
    golden_pointer = json.loads(
        (fixture_root / "valid-generation-pointer-v3.json").read_text(encoding="utf-8")
    )
    validate_generation_manifest(golden_manifest)
    golden_bytes = manifest_bytes(golden_manifest)
    validate_generation_pointer(
        golden_pointer, {golden_manifest["generation_id"]: golden_bytes}
    )


@pytest.mark.parametrize(("capability", "limits"), CAPS.items())
def test_asset_caps_accept_exact_boundaries(capability, limits):
    validate_contract("asset-descriptor-v3.schema.json", asset(capability, *limits))


@pytest.mark.parametrize(("capability", "limits"), CAPS.items())
@pytest.mark.parametrize("field_index", [0, 1])
def test_asset_caps_reject_one_byte_over(capability, limits, field_index):
    values = list(limits)
    values[field_index] += 1
    with pytest.raises(ValueError, match="validation failed"):
        validate_contract("asset-descriptor-v3.schema.json", asset(capability, *values))


def test_identity_encoding_requires_equal_byte_counts():
    descriptor = asset("core", 100, 100)
    descriptor["uncompressed_bytes"] = 101
    with pytest.raises(ValueError, match="byte counts must match"):
        validate_asset_descriptor(descriptor)


def test_asset_must_be_content_addressed_and_credential_free():
    descriptor = asset()
    descriptor["url"] = "https://example.invalid/core.json.gz"
    with pytest.raises(ValueError, match="canonical AR-local|validation failed"):
        validate_asset_descriptor(descriptor)
    descriptor = asset()
    descriptor["url"] = "https://github.com/yanniedog/AR-local/releases/download/app-payload-gen/not-the-digest.json.gz"
    with pytest.raises(ValueError, match="content-addressed"):
        validate_asset_descriptor(descriptor)
    descriptor["url"] = f"https://user:secret@github.com/yanniedog/AR-local/releases/download/app-payload-gen/{SHA}.json.gz"
    with pytest.raises(ValueError, match="credentials|validation failed"):
        validate_asset_descriptor(descriptor)


def test_runtime_asset_negotiation_rejects_unknown_capabilities_and_schema_ids():
    with pytest.raises(ValueError, match="unsupported v3 capability"):
        validate_asset_descriptor(asset("search"))
    descriptor = asset()
    descriptor["schema_id"] = "https://australianrates.app/contracts/v3/search.schema.json"
    with pytest.raises(ValueError, match="schema_id"):
        validate_asset_descriptor(descriptor)


def test_coverage_equations_reconcile_named_populations():
    validate_coverage_v2(coverage())

    broken = coverage()
    broken["providers_attempted"] += 1
    with pytest.raises(ValueError, match="providers_attempted"):
        validate_coverage_v2(broken)

    broken = coverage()
    broken["exclusions_by_reason"]["unknown"] = 1
    with pytest.raises(ValueError, match="eligible products plus exclusions"):
        validate_coverage_v2(broken)


def test_authoritative_coverage_requires_complete_failure_provenance():
    broken = coverage()
    broken["failure_provenance_complete"] = False
    with pytest.raises(ValueError, match="complete failure provenance"):
        validate_coverage_v2(broken)

    broken = coverage()
    broken["corrupt_failure_records"] = 1
    with pytest.raises(ValueError, match="corrupt failure records"):
        validate_coverage_v2(broken)

    broken = coverage()
    broken["register_provenance_complete"] = False
    with pytest.raises(ValueError, match="register provenance"):
        validate_generation_manifest(bind_manifest({**manifest(), "coverage": broken}))


def test_generation_manifest_requires_core_and_matching_capability_name():
    valid = manifest()
    validate_generation_manifest(valid)

    missing = manifest()
    missing["capabilities"] = {"search": asset("search")}
    with pytest.raises(ValueError, match="core"):
        validate_generation_manifest(missing)

    mismatch = manifest()
    mismatch["capabilities"]["core"] = asset("search")
    with pytest.raises(ValueError, match="core"):
        validate_generation_manifest(mismatch)


def test_complete_generation_rejects_incomplete_provider_states():
    invalid = manifest()
    invalid["coverage"].update(
        {
            "providers_complete": 3,
            "providers_partial": 1,
        }
    )
    with pytest.raises(ValueError, match="incomplete provider states"):
        validate_generation_manifest(invalid)

    partial = deepcopy(invalid)
    partial["observation_state"] = "partial"
    validate_generation_manifest(bind_manifest(partial))


def test_generation_identity_is_bound_to_date_revision_and_canonical_digest():
    invalid = manifest()
    invalid["generation_id"] = invalid["generation_id"].replace("2026-08-14", "2026-08-13")
    with pytest.raises(ValueError, match="date does not match"):
        validate_generation_manifest(invalid)

    invalid = manifest()
    invalid["generation_id"] = invalid["generation_id"].replace("r0001", "r0002")
    with pytest.raises(ValueError, match="revision does not match"):
        validate_generation_manifest(invalid)

    invalid = manifest()
    invalid["producer_commit"] = "f" * 40
    with pytest.raises(ValueError, match="canonical manifest content"):
        validate_generation_manifest(invalid)


def test_pointer_has_independent_observation_and_complete_heads():
    valid, documents = pointer_bundle(manifest("2026-08-15", "partial"))
    validate_generation_pointer(valid, documents)

    invalid, documents = pointer_bundle()
    invalid["latest_complete"]["observation_state"] = "partial"
    with pytest.raises(ValueError, match="complete"):
        validate_generation_pointer(invalid, documents)

    invalid, documents = pointer_bundle(manifest("2026-08-13", "partial"))
    with pytest.raises(ValueError, match="cannot predate"):
        validate_generation_pointer(invalid, documents)

    invalid, documents = pointer_bundle(
        manifest("2026-08-14", "partial", 1),
        manifest("2026-08-14", "complete", 2),
    )
    with pytest.raises(ValueError, match="same-date revision"):
        validate_generation_pointer(invalid, documents)


def test_pointer_manifest_url_is_bound_to_manifest_byte_hash():
    invalid, documents = pointer_bundle()
    invalid["latest_observation"]["manifest_url"] = (
        "https://github.com/yanniedog/AR-local/releases/download/app-payload-gen/"
        + "0" * 64
        + ".json"
    )
    with pytest.raises(ValueError, match="content-addressed"):
        validate_generation_pointer(invalid, documents)

    invalid, documents = pointer_bundle()
    invalid["latest_observation"]["manifest_sha256"] = "0" * 64
    invalid["latest_observation"]["manifest_url"] = (
        "https://github.com/yanniedog/AR-local/releases/download/app-payload-gen/"
        + "0" * 64
        + ".json"
    )
    with pytest.raises(ValueError, match="manifest byte SHA-256"):
        validate_generation_pointer(invalid, documents)


def test_pointer_transition_binds_prior_bytes_and_rejects_revision_regression():
    previous, _ = pointer_bundle(
        manifest("2026-08-14", "complete", 2),
        manifest("2026-08-14", "complete", 2),
    )
    previous_bytes = json.dumps(
        previous, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    previous_sha = hashlib.sha256(previous_bytes).hexdigest()
    candidate, documents = pointer_bundle()
    with pytest.raises(ValueError, match="regresses latest_observation"):
        validate_generation_pointer(
            candidate,
            documents,
            previous_pointer_bytes=previous_bytes,
            expected_previous_pointer_sha256=previous_sha,
        )
    with pytest.raises(ValueError, match="CAS hash"):
        validate_generation_pointer(
            candidate,
            documents,
            previous_pointer_bytes=previous_bytes,
            expected_previous_pointer_sha256="0" * 64,
        )

    replacement_manifest = manifest()
    replacement_manifest["producer_commit"] = "f" * 40
    bind_manifest(replacement_manifest)
    replacement, replacement_documents = pointer_bundle(replacement_manifest, replacement_manifest)
    original, _ = pointer_bundle()
    original_bytes = json.dumps(
        original, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    with pytest.raises(ValueError, match="equal coordinate"):
        validate_generation_pointer(
            replacement,
            replacement_documents,
            previous_pointer_bytes=original_bytes,
            expected_previous_pointer_sha256=original_sha,
        )


@pytest.mark.parametrize(
    "timestamp",
    ("2026-08-14T10:00+10:00", "2026-08-14T10:00:00+10:00:30"),
)
def test_contract_datetime_format_is_strict_rfc3339(timestamp):
    invalid = manifest()
    invalid["observed_at"] = timestamp
    bind_manifest(invalid)
    with pytest.raises(ValueError, match="observed_at"):
        validate_generation_manifest(invalid)


def test_pointer_contract_sha_is_a_fail_closed_lock():
    invalid, documents = pointer_bundle()
    invalid["contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="contract SHA"):
        validate_generation_pointer(invalid, documents)


def test_unknown_contract_name_fails_closed():
    with pytest.raises(ValueError, match="unknown v3 schema"):
        validate_contract("manifest-v2.schema.json", {})
