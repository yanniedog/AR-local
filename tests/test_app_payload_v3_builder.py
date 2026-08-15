from __future__ import annotations

import gzip
import hashlib
import json
import socket
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

import app_payload_v3
from cdr_atomic import ImmutablePathError
from cdr_domain.capabilities import deterministic_gzip
from cdr_domain.contract_validation import validate_generation_manifest
from cdr_domain.generation import (
    FAILURE_STAGES,
    GenerationCandidate,
    GenerationInputs,
    build_generation_candidate,
    write_generation_candidate,
)
from cdr_domain.models import PricingStatus
from cdr_domain.normalize import normalize_product
from cdr_domain.serialize import canonical_json_bytes, to_primitive


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "canonical_domain_real_observations.json"
OBSERVED_AT = "2026-08-14T10:00:00+10:00"
PRODUCER_COMMIT = "6f696ecc3a61198b90ad58f8b90b086e866a26e4"


def _observations() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"]


def _normalized(name: str):
    item = _observations()[name]
    return normalize_product(
        item["record"],
        dataset=item["dataset"],
        provider_display_name=item["provider"],
        register_holder_id=None,
        authority=f"preserved-fixture:{name}",
        observed_at=OBSERVED_AT,
        source_path=item["source_path"],
        source_locator=item["source_locator"],
        source_sha256=item["source_sha256"],
        source_kind="preserved_cdr_fixture_projection",
    )


def _products():
    return tuple(
        _normalized(name)
        for name in (
            "bank_of_melbourne_before_rename",
            "afg_mortgage_offset",
            "move_bank_ambiguous_rates",
        )
    )


def _metadata(products=None, **changes) -> dict[str, object]:
    products = products or _products()
    value = {
        "observation_date": "2026-08-14",
        "observed_at": OBSERVED_AT,
        "observation_state": "complete",
        "generation_revision": 1,
        "normalization_version": products[0].normalization_version,
        "producer_commit": PRODUCER_COMMIT,
        "prior_ledger_digest": None,
        "ledger_event_digest": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "provider_states": {
            product.identity.provider_uid: "complete" for product in products
        },
        "products_discovered_by_provider": dict(
            Counter(product.identity.provider_uid for product in products)
        ),
        "register_source_states": {"preserved-register": "complete"},
        "failure_records_by_provider": {},
        "corrupt_failure_records": 0,
    }
    value.update(changes)
    return value


def _candidate(products=None, **metadata_changes):
    products = products or _products()
    inputs = GenerationInputs.from_mapping(_metadata(products, **metadata_changes))
    return build_generation_candidate(products, inputs)


def test_double_build_is_byte_identical_lean_and_contract_valid(monkeypatch):
    products = _products()

    def network_forbidden(*_args, **_kwargs):
        raise AssertionError("candidate generation attempted network access")

    monkeypatch.setattr(socket, "create_connection", network_forbidden)
    first = _candidate(products)
    second = _candidate(tuple(reversed(products)))

    assert first == second
    assert first.core.encoded_bytes == deterministic_gzip(first.core.decoded_bytes)
    assert gzip.decompress(first.core.encoded_bytes) == first.core.decoded_bytes
    assert first.core.encoded_bytes[:10] == (
        b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    )
    manifest = first.manifest()
    core = json.loads(first.core.decoded_bytes)
    assert [item["display_name"] for item in core["products"]] == [
        "Investment Cash Account"
    ]
    assert manifest["coverage"] == {
        "products_discovered": 3,
        "products_priced": 3,
        "products_consumer_eligible": 1,
        "rate_tiers_eligible": 1,
        "providers_registered": 3,
        "providers_attempted": 3,
        "providers_responded": 3,
        "providers_complete": 3,
        "providers_empty": 0,
        "providers_partial": 0,
        "providers_failed": 0,
        "providers_not_attempted": 0,
        "register_sources_attempted": 1,
        "register_sources_complete": 1,
        "register_provenance_complete": True,
        "failure_records": 0,
        "failure_records_by_provider": {},
        "corrupt_failure_records": 0,
        "exclusions_by_reason": {
            "availability_unknown": 1,
            "mortgage_linked_offset": 1,
        },
        "failure_provenance_complete": True,
        "reconciliation_status": "reconciled",
    }
    descriptor = manifest["capabilities"]["core"]
    assert descriptor["compressed_bytes"] == len(first.core.encoded_bytes)
    assert descriptor["uncompressed_bytes"] == len(first.core.decoded_bytes)
    assert descriptor["sha256"] == hashlib.sha256(first.core.encoded_bytes).hexdigest()
    assert descriptor["compressed_bytes"] <= 2 * 1024**2
    assert descriptor["uncompressed_bytes"] <= 16 * 1024**2
    validate_generation_manifest(manifest, {"core": first.core.encoded_bytes})


def test_generation_rejects_incoherent_provider_and_failure_evidence():
    products = _products()
    bank_of_china = _normalized("bank_of_china_td_without_structured_term")
    states = {product.identity.provider_uid: "complete" for product in products}
    states[bank_of_china.identity.provider_uid] = "failed"
    discovered = dict(_metadata(products)["products_discovered_by_provider"])
    discovered[bank_of_china.identity.provider_uid] = 0

    missing_failure = _metadata(
        products,
        observation_state="partial",
        provider_states=states,
        products_discovered_by_provider=discovered,
    )
    with pytest.raises(ValueError, match="every and only failed provider"):
        build_generation_candidate(
            products, GenerationInputs.from_mapping(missing_failure)
        )

    partial = _metadata(
        products,
        observation_state="partial",
        provider_states=states,
        products_discovered_by_provider=discovered,
        failure_records_by_provider={bank_of_china.identity.provider_uid: 2},
    )
    candidate = build_generation_candidate(
        products, GenerationInputs.from_mapping(partial)
    )
    assert candidate.manifest()["coverage"]["failure_records"] == 2

    complete = {**partial, "observation_state": "complete"}
    with pytest.raises(ValueError, match="incomplete provider states"):
        build_generation_candidate(products, GenerationInputs.from_mapping(complete))

    product_provider = products[0].identity.provider_uid
    invalid_states = dict(_metadata(products)["provider_states"])
    invalid_states[product_provider] = "empty"
    with pytest.raises(ValueError, match="empty providers cannot carry"):
        _candidate(products, provider_states=invalid_states)


def test_generation_inputs_are_strict_and_manifest_copy_is_not_authoritative():
    products = _products()
    metadata = _metadata(products)
    with pytest.raises(ValueError, match="unexpected=.*typo"):
        GenerationInputs.from_mapping({**metadata, "typo": True})
    with pytest.raises(ValueError, match="observed_at local date"):
        _candidate(products, observed_at="2026-08-15T00:00:00+10:00")
    with pytest.raises(ValueError, match="postdate"):
        _candidate(products, observed_at="2026-08-14T09:59:59+10:00")
    incomplete_counts = dict(metadata["products_discovered_by_provider"])
    incomplete_counts[products[0].identity.provider_uid] += 1
    with pytest.raises(ValueError, match="do not reconcile"):
        _candidate(products, products_discovered_by_provider=incomplete_counts)
    invalid_schema_product = replace(products[0], schema_version=2)
    invalid_schema_products = (invalid_schema_product, *products[1:])
    with pytest.raises(ValueError, match="canonical-core-v3.schema.json"):
        _candidate(invalid_schema_products)
    contradictory_product = replace(
        products[0],
        evidence=replace(
            products[0].evidence,
            pricing_status=PricingStatus.UNKNOWN,
        ),
    )
    assert contradictory_product.evidence.pricing_status.value == "unknown"
    with pytest.raises(ValueError, match="pricing status"):
        _candidate((contradictory_product, *products[1:]))
    with pytest.raises(TypeError, match="keys must be non-empty strings"):
        GenerationInputs.from_mapping(
            {**metadata, "register_source_states": {"": "complete"}}
        )

    candidate = _candidate(products)
    manifest = candidate.manifest()
    manifest["producer_commit"] = "f" * 40
    assert candidate.manifest()["producer_commit"] == PRODUCER_COMMIT


@pytest.mark.parametrize("failure_stage", FAILURE_STAGES)
def test_atomic_candidate_output_recovers_after_each_injected_failure(
    tmp_path, failure_stage
):
    candidate = _candidate()
    output_root = tmp_path / failure_stage

    def fail_at(stage):
        if stage == failure_stage:
            raise RuntimeError(f"injected failure: {stage}")

    with pytest.raises(RuntimeError, match=failure_stage):
        write_generation_candidate(candidate, output_root, failure_hook=fail_at)
    assert not (output_root / candidate.generation_id).exists()
    assert not list(output_root.glob(".*.tmp-*"))

    target = write_generation_candidate(candidate, output_root)
    assert target == output_root / candidate.generation_id
    assert {path.name for path in target.iterdir()} == {
        candidate.core.filename,
        candidate.manifest_filename,
    }
    assert (
        target / candidate.core.filename
    ).read_bytes() == candidate.core.encoded_bytes
    assert (
        target / candidate.manifest_filename
    ).read_bytes() == candidate.manifest_bytes
    assert write_generation_candidate(candidate, output_root) == target


def test_create_once_candidate_detects_existing_byte_corruption(tmp_path):
    candidate = _candidate()
    target = write_generation_candidate(candidate, tmp_path)
    (target / candidate.core.filename).write_bytes(b"corrupt")

    with pytest.raises(ImmutablePathError, match="differs from expected bytes"):
        write_generation_candidate(candidate, tmp_path)


def test_candidate_writer_revalidates_public_dataclass_and_staged_bytes(tmp_path):
    candidate = _candidate()
    forged = replace(candidate, generation_id="../outside")
    with pytest.raises(ValueError, match="generation_id disagrees"):
        write_generation_candidate(forged, tmp_path)
    assert not (tmp_path.parent / "outside").exists()

    forged = GenerationCandidate(
        generation_id=candidate.generation_id,
        generation_digest=candidate.generation_digest,
        manifest_sha256="0" * 64,
        manifest_bytes=candidate.manifest_bytes,
        core=candidate.core,
    )
    with pytest.raises(ValueError, match="manifest SHA-256"):
        write_generation_candidate(forged, tmp_path)

    def corrupt_staging(stage):
        if stage != "before_commit":
            return
        staging = next(tmp_path.glob(f".{candidate.generation_id}.tmp-*"))
        (staging / candidate.core.filename).write_bytes(b"corrupt")

    with pytest.raises(ImmutablePathError, match="differs from expected bytes"):
        write_generation_candidate(candidate, tmp_path, failure_hook=corrupt_staging)
    assert not (tmp_path / candidate.generation_id).exists()


def test_candidate_writer_rejects_output_and_target_symlinks(tmp_path):
    candidate = _candidate()
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked"
    try:
        linked_root.symlink_to(real_root, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symbolic links unavailable on this platform: {error}")

    with pytest.raises(ValueError, match="cannot be a symbolic link"):
        write_generation_candidate(candidate, linked_root)

    dangling_target = real_root / candidate.generation_id
    dangling_target.symlink_to(
        real_root / "missing-generation",
        target_is_directory=True,
    )
    with pytest.raises(ImmutablePathError, match="not a real directory"):
        write_generation_candidate(candidate, real_root)


def test_local_cli_builds_only_a_candidate_and_rejects_duplicate_input_keys(
    tmp_path, monkeypatch, capsys
):
    products = _products()
    entities = {
        "schema_version": 3,
        "normalization_version": products[0].normalization_version,
        "observation_date": "2026-08-14",
        "products": [to_primitive(product) for product in products],
    }
    entities_path = tmp_path / "entities.json"
    metadata_path = tmp_path / "metadata.json"
    entities_path.write_bytes(canonical_json_bytes(entities))
    metadata_path.write_text(
        json.dumps(_metadata(products), sort_keys=True),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("CLI attempted network access")
        ),
    )
    assert (
        app_payload_v3.main(
            [
                "--entities",
                str(entities_path),
                "--metadata",
                str(metadata_path),
                "--output-root",
                str(tmp_path / "candidate"),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    candidate_dir = Path(summary["candidate_directory"])
    assert candidate_dir.is_dir()
    assert len(list(candidate_dir.iterdir())) == 2
    assert not any("pointer" in path.name for path in candidate_dir.iterdir())

    metadata_path.write_text(
        '{"observation_date":"2026-08-14","observation_date":"2026-08-15"}',
        encoding="utf-8",
    )
    with pytest.raises(app_payload_v3.DuplicateInputKeyError):
        app_payload_v3.build_local_candidate(
            entities_path,
            metadata_path,
            tmp_path / "duplicate",
        )


def test_candidate_changes_when_hash_bound_generation_input_changes():
    first = _candidate()
    second = _candidate(generation_revision=2)
    third = _candidate(ledger_event_digest="f" * 64)

    assert len({first.generation_id, second.generation_id, third.generation_id}) == 3
    assert len({first.manifest_bytes, second.manifest_bytes, third.manifest_bytes}) == 3
    assert (
        first.core.encoded_bytes
        == second.core.encoded_bytes
        == third.core.encoded_bytes
    )
