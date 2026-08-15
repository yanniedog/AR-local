from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app_payload_v3_state import (
    CANONICAL_REPO,
    CandidateBundle,
    PromotionError,
    asset_filename,
    build_dates_index,
    build_pointer,
    complete_heads,
    load_candidate,
    ordered_census,
    strict_object,
)
from cdr_domain.contract_validation import validate_generation_pointer
from cdr_domain.generation import GenerationInputs, build_generation_candidate, write_generation_candidate
from cdr_domain.normalize import normalize_product


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "canonical_domain_real_observations.json"
PRODUCER_COMMIT = "6f696ecc3a61198b90ad58f8b90b086e866a26e4"


def _observation(name: str):
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    return normalize_product(
        item["record"], dataset=item["dataset"], provider_display_name=item["provider"],
        register_holder_id=None, authority=f"preserved-fixture:{name}",
        observed_at="2026-08-14T10:00:00+10:00", source_path=item["source_path"],
        source_locator=item["source_locator"], source_sha256=item["source_sha256"],
        source_kind="preserved_cdr_fixture_projection",
    )


def _candidate(
    tmp_path: Path,
    *,
    observation_date: str = "2026-08-14",
    revision: int = 1,
    state: str = "complete",
    producer_commit: str = PRODUCER_COMMIT,
    prior: CandidateBundle | None = None,
) -> CandidateBundle:
    product = _observation("bank_of_melbourne_before_rename")
    provider_states = {product.identity.provider_uid: "complete"}
    discovered = {product.identity.provider_uid: 1}
    failures: dict[str, int] = {}
    if state == "partial":
        failed = _observation("bank_of_china_td_without_structured_term")
        provider_states[failed.identity.provider_uid] = "failed"
        discovered[failed.identity.provider_uid] = 0
        failures[failed.identity.provider_uid] = 1
    ledger_digest = hashlib.sha256(
        f"{observation_date}:{revision}:{state}:{producer_commit}".encode()
    ).hexdigest()
    inputs = GenerationInputs.from_mapping(
        {
            "observation_date": observation_date,
            "observed_at": f"{observation_date}T10:00:00+10:00",
            "observation_state": state,
            "generation_revision": revision,
            "normalization_version": product.normalization_version,
            "producer_commit": producer_commit,
            "prior_ledger_digest": (
                prior.manifest["ledger_event_digest"] if prior is not None else None
            ),
            "ledger_event_digest": ledger_digest,
            "provider_states": provider_states,
            "products_discovered_by_provider": discovered,
            "register_source_states": {"preserved-register": "complete"},
            "failure_records_by_provider": failures,
            "corrupt_failure_records": 0,
        }
    )
    built = build_generation_candidate((product,), inputs)
    return load_candidate(write_generation_candidate(built, tmp_path / "candidates"))


def _pointer(census, *, previous_bytes=None, previous_pointer=None) -> bytes:
    return build_pointer(
        census,
        generated_at="2026-08-15T00:00:00Z",
        previous_bytes=previous_bytes,
        previous_pointer=previous_pointer,
        previous_manifests={},
        previous_capabilities={},
    )


def test_successful_but_incomplete_listing_cannot_drop_a_prior_date(tmp_path):
    first = _candidate(tmp_path / "first")
    second = _candidate(tmp_path / "second", observation_date="2026-08-15", prior=first)
    previous = build_dates_index(
        complete_heads((first, second), CANONICAL_REPO),
        generated_at="2026-08-15T00:00:00Z", previous_bytes=None,
    )
    with pytest.raises(PromotionError, match="cannot drop or regress"):
        build_dates_index(
            [second.head()], generated_at="2026-08-16T00:00:00Z", previous_bytes=previous
        )


def test_bootstrap_pointer_uses_maximum_verified_census_head(tmp_path):
    first = _candidate(tmp_path / "first")
    second = _candidate(tmp_path / "second", observation_date="2026-08-15", prior=first)
    pointer = strict_object(_pointer((first, second)), "pointer")
    assert pointer["latest_observation"]["generation_id"] == second.generation_id
    assert pointer["latest_complete"] == pointer["latest_observation"]


def test_partial_advances_observation_but_not_complete_or_dates(tmp_path):
    complete = _candidate(tmp_path / "complete")
    partial = _candidate(
        tmp_path / "partial", observation_date="2026-08-15", state="partial", prior=complete
    )
    pointer = strict_object(_pointer((complete, partial)), "pointer")
    heads = complete_heads((complete, partial), CANONICAL_REPO)
    assert pointer["latest_observation"]["generation_id"] == partial.generation_id
    assert pointer["latest_complete"]["generation_id"] == complete.generation_id
    assert [head["generation_id"] for head in heads] == [complete.generation_id]


def test_same_date_revision_replaces_index_head_but_coordinate_is_immutable(tmp_path):
    revision_one = _candidate(tmp_path / "r1")
    revision_two = _candidate(tmp_path / "r2", revision=2, prior=revision_one)
    index = strict_object(
        build_dates_index(
            complete_heads((revision_one, revision_two), CANONICAL_REPO),
            generated_at="2026-08-15T00:00:00Z", previous_bytes=None,
        ),
        "index",
    )
    assert index["count"] == 1
    assert index["dates"][0]["generation_id"] == revision_two.generation_id
    conflict = _candidate(tmp_path / "conflict", producer_commit="7" * 40)
    with pytest.raises(PromotionError, match="one date/revision coordinate"):
        ordered_census((revision_one, conflict))


def test_late_historical_revision_uses_ledger_order_and_coordinate_heads(tmp_path):
    first = _candidate(tmp_path / "first")
    newer = _candidate(
        tmp_path / "newer", observation_date="2026-08-15", prior=first
    )
    correction = _candidate(
        tmp_path / "correction", revision=2, prior=newer
    )

    census = ordered_census((newer, correction, first))
    assert [item.generation_id for item in census] == [
        first.generation_id, newer.generation_id, correction.generation_id,
    ]
    pointer = strict_object(_pointer(census), "pointer")
    assert pointer["latest_observation"]["generation_id"] == newer.generation_id
    assert pointer["latest_complete"]["generation_id"] == newer.generation_id
    heads = complete_heads(census, CANONICAL_REPO)
    assert [item["generation_id"] for item in heads] == [
        correction.generation_id, newer.generation_id,
    ]


def test_exact_retry_is_idempotent_and_creates_no_control_commit(tmp_path):
    candidate = _candidate(tmp_path)
    original = _pointer((candidate,))
    previous = strict_object(original, "pointer")
    assert _pointer(
        (candidate,), previous_bytes=original, previous_pointer=previous
    ) == original


def test_prepared_pointer_remains_contract_valid_before_control_cas(tmp_path):
    candidate = _candidate(tmp_path)
    pointer_bytes = _pointer((candidate,))
    pointer = strict_object(pointer_bytes, "pointer")
    validate_generation_pointer(
        pointer,
        {candidate.generation_id: candidate.manifest_bytes},
        {candidate.generation_id: candidate.capability_bytes},
    )


def test_ordered_census_rejects_repeated_ledger_event_digest():
    digest = "d" * 64
    first = CandidateBundle(
        Path("gen-2026-08-14-r0001-aaaaaaaaaaaa"),
        {"generation_id": "gen-2026-08-14-r0001-aaaaaaaaaaaa",
         "prior_ledger_digest": None, "ledger_event_digest": digest}, b"", {},
    )
    repeated = CandidateBundle(
        Path("gen-2026-08-15-r0001-bbbbbbbbbbbb"),
        {"generation_id": "gen-2026-08-15-r0001-bbbbbbbbbbbb",
         "prior_ledger_digest": digest, "ledger_event_digest": digest}, b"", {},
    )
    with pytest.raises(PromotionError, match="reuses a ledger event digest"):
        ordered_census((first, repeated))


def test_ordered_census_rejects_branches_and_cycles(tmp_path):
    root = _candidate(tmp_path / "root")
    child = _candidate(
        tmp_path / "child", observation_date="2026-08-15", prior=root
    )
    branch = _candidate(tmp_path / "branch", revision=2, prior=root)
    with pytest.raises(PromotionError, match="branches its ledger lineage"):
        ordered_census((root, child, branch))

    cycled_root = CandidateBundle(
        root.directory,
        {**root.manifest, "prior_ledger_digest": child.manifest["ledger_event_digest"]},
        root.manifest_bytes,
        root.capability_bytes,
    )
    with pytest.raises(PromotionError, match="disconnected ledger lineage"):
        ordered_census((cycled_root, child))


def test_asset_filename_accepts_canonical_identity_descriptor():
    manifest = json.loads(
        (ROOT / "contracts/v3/fixtures/valid-generation-manifest-v3.json").read_text(
            encoding="utf-8"
        )
    )
    descriptor = manifest["capabilities"]["core"]
    assert descriptor["encoding"] == "identity"
    assert asset_filename(descriptor) == f"{descriptor['sha256']}.json"


@pytest.mark.parametrize("mutation", ["prefix", "gzip-suffix"])
def test_asset_filename_rejects_noncanonical_identity_location(mutation):
    manifest = json.loads(
        (ROOT / "contracts/v3/fixtures/valid-generation-manifest-v3.json").read_text(
            encoding="utf-8"
        )
    )
    descriptor = dict(manifest["capabilities"]["core"])
    digest = descriptor["sha256"]
    replacement = (
        f"prefix-{digest}.json" if mutation == "prefix" else f"{digest}.json.gz"
    )
    descriptor["url"] = descriptor["url"].replace(f"{digest}.json", replacement)
    with pytest.raises(PromotionError, match="filename is not its exact SHA-256"):
        asset_filename(descriptor)
