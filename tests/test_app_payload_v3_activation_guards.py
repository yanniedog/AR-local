from __future__ import annotations

import json
from pathlib import Path

import pytest

import app_payload_v3_github
import app_payload_v3_promotion
import app_payload_v3_state
from app_payload_v3_promotion import PromotionError, promote_candidate
from cdr_domain.contract_validation import contract_sha256
from cdr_domain.generation import (
    GenerationInputs,
    build_generation_candidate,
    write_generation_candidate,
)
from cdr_domain.normalize import normalize_product


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "canonical_domain_real_observations.json"
PRODUCER_COMMIT = "6f696ecc3a61198b90ad58f8b90b086e866a26e4"
TRUSTED_RUN_ID = "12345"


def _candidate_directory(tmp_path: Path) -> Path:
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][
        "bank_of_melbourne_before_rename"
    ]
    product = normalize_product(
        item["record"], dataset=item["dataset"], provider_display_name=item["provider"],
        register_holder_id=None, authority="preserved-fixture:activation-guards",
        observed_at="2026-08-14T10:00:00+10:00", source_path=item["source_path"],
        source_locator=item["source_locator"], source_sha256=item["source_sha256"],
        source_kind="preserved_cdr_fixture_projection",
    )
    provider_uid = product.identity.provider_uid
    inputs = GenerationInputs.from_mapping(
        {
            "observation_date": "2026-08-14",
            "observed_at": "2026-08-14T10:00:00+10:00",
            "observation_state": "complete",
            "generation_revision": 1,
            "normalization_version": product.normalization_version,
            "producer_commit": PRODUCER_COMMIT,
            "prior_ledger_digest": None,
            "ledger_event_digest": "d" * 64,
            "provider_states": {provider_uid: "complete"},
            "products_discovered_by_provider": {provider_uid: 1},
            "register_source_states": {"preserved-register": "complete"},
            "failure_records_by_provider": {},
            "corrupt_failure_records": 0,
        }
    )
    candidate = build_generation_candidate((product,), inputs)
    return write_generation_candidate(candidate, tmp_path / "candidates")


class _UnusedBackend:
    def __init__(self) -> None:
        self.events: list[object] = []


@pytest.fixture(autouse=True)
def _reviewed_activation_prerequisites(monkeypatch):
    monkeypatch.setattr(
        app_payload_v3_promotion, "require_candidate_publication_store", lambda: None
    )
    monkeypatch.setattr(
        app_payload_v3_promotion, "require_candidate_artifact_binding", lambda: None
    )
    monkeypatch.setattr(
        app_payload_v3_github,
        "AR_APP_CONSUMER_PARITY_LOCK",
        (contract_sha256(), "f" * 64),
    )


def test_execute_requires_exact_trusted_producer_commit_before_backend_use(tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = _UnusedBackend()
    with pytest.raises(PromotionError, match="requires a trusted producer commit"):
        promote_candidate(directory, backend, execute=True)
    with pytest.raises(PromotionError, match="differs from its trusted Actions run"):
        promote_candidate(
            directory, backend, execute=True, expected_producer_commit="7" * 40
        )
    assert backend.events == []


def test_execute_core_requires_artifact_run_binding_before_backend_mutation(
    monkeypatch, tmp_path
):
    directory = _candidate_directory(tmp_path)
    backend = _UnusedBackend()
    with pytest.raises(PromotionError, match="requires a candidate run ID"):
        promote_candidate(
            directory, backend, execute=True, expected_producer_commit=PRODUCER_COMMIT
        )
    monkeypatch.setattr(
        app_payload_v3_promotion,
        "require_candidate_artifact_binding",
        app_payload_v3_state.require_candidate_artifact_binding,
    )
    with pytest.raises(PromotionError, match="artifact-byte provenance"):
        promote_candidate(
            directory, backend, execute=True, expected_producer_commit=PRODUCER_COMMIT,
            candidate_run_id=TRUSTED_RUN_ID,
        )
    assert backend.events == []


def test_publication_store_assignment_cannot_enable_generic_backend(monkeypatch, tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = _UnusedBackend()
    monkeypatch.setattr(
        app_payload_v3_promotion,
        "require_candidate_publication_store",
        app_payload_v3_state.require_candidate_publication_store,
    )
    kwargs = dict(
        backend=backend, execute=True, expected_producer_commit=PRODUCER_COMMIT,
        candidate_run_id=TRUSTED_RUN_ID,
    )
    with pytest.raises(PromotionError, match="publication store is not locked"):
        promote_candidate(directory, **kwargs)
    monkeypatch.setattr(
        app_payload_v3_state,
        "CANDIDATE_PUBLICATION_STORE_CONTRACT",
        app_payload_v3_state.CandidatePublicationStoreContract(
            repository="yanniedog/AR-v3-store",
            strategy="github-immutable-releases-v1",
            verification_contract_sha256="f" * 64,
        ),
    )
    with pytest.raises(PromotionError, match="store verification is not implemented"):
        promote_candidate(directory, **kwargs)
    assert backend.events == []


def test_unset_consumer_contract_parity_blocks_before_backend_use(monkeypatch, tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = _UnusedBackend()
    monkeypatch.setattr(app_payload_v3_github, "AR_APP_CONSUMER_PARITY_LOCK", None)
    with pytest.raises(PromotionError, match="consumer contract parity"):
        promote_candidate(
            directory, backend, execute=True, expected_producer_commit=PRODUCER_COMMIT,
            candidate_run_id=TRUSTED_RUN_ID,
        )
    assert backend.events == []
