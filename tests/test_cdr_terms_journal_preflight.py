import json

import pytest

from cdr_ledger_v2 import event_digest
from cdr_terms.journal_preflight import product_identity_index, verify_finalization
from cdr_terms.journal_sources import JournalSource


def documents():
    generation = "obs-2026-09-15-1234567890abcdef"
    contract = {"generation_id": generation, "contract_digest": "a" * 64,
                "observation_date": "2026-09-15", "observation_state": "partial",
                "observed_at": "2026-09-14T15:00:00Z", "prior_ledger_head": None,
                "coverage": {"products_discovered": 1, "providers_partial": 1,
                             "unavailable_populations": ["priced_products"]}}
    event = {"schema_version": 2, "event_type": "observation_finalized", "ledger_state": "finalized",
             "generation_id": generation, "contract_digest": "a" * 64,
             "contract_path": "contracts/source.json", "observation_date": "2026-09-15",
             "observation_state": "partial", "previous_event_digest": None,
             "parent_event_digest": None, "parent_generation_id": None}
    event["event_digest"] = event_digest(event)
    marker = {"finalization_schema_version": 2, "ledger_state": "finalized",
              "generation_id": generation, "export_contract_digest": "a" * 64,
              "export_contract_path": "contracts/source.json", "run_date": "2026-09-15",
              "observation_state": "partial", "ledger_event_digest": event["event_digest"],
              "banks": {"products": 1}}
    return contract, marker, event


def test_partial_coverage_is_not_capture_authority():
    result = verify_finalization(*documents(), detail_products=1)
    assert result["observation_state"] == "partial"
    assert result["unavailable_populations"] == ["priced_products"]
    assert result["capture_authorized"] is False
    assert result["product_accounting_reconciled"] is False


@pytest.mark.parametrize("field,value", [("generation_id", "wrong"), ("ledger_event_digest", "b" * 64),
                                        ("observation_state", "complete"), ("run_date", "2026-09-14")])
def test_marker_binding_rejected(field, value):
    contract, marker, event = documents(); marker[field] = value
    with pytest.raises(ValueError):
        verify_finalization(contract, marker, event, detail_products=1)


def test_tampered_event_rejected():
    contract, marker, event = documents(); event["contract_digest"] = "b" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_finalization(contract, marker, event, detail_products=1)


@pytest.mark.parametrize("count", [0, 2, True])
def test_count_mismatch_rejected(count):
    with pytest.raises(ValueError, match="product_count_mismatch"):
        verify_finalization(*documents(), detail_products=count)


def test_identity_index_binds_provider_and_export_key():
    contract = {"provider_states": [{"provider_dir": "bank", "provider_uid": "uid"}]}
    body = json.dumps({"data": {"name": "Account", "productCategory": "SAVINGS_ACCOUNTS"}}).encode()
    source = JournalSource("bank", "p", "body", "event", "a" * 64, "2026-09-15T00:00:00Z", body)
    row = product_identity_index(contract, (source,))[0]
    assert row["provider_uid"] == "uid"
    assert row["product_key"] == "bank|p|SAVINGS_ACCOUNTS|Account"
    with pytest.raises(ValueError, match="key_collision"):
        product_identity_index(contract, (source, source))
    with pytest.raises(ValueError, match="not_in_contract"):
        product_identity_index({"provider_states": []}, (source,))
    with pytest.raises(ValueError, match="directory_ambiguous"):
        product_identity_index({"provider_states": contract["provider_states"] * 2}, (source,))
