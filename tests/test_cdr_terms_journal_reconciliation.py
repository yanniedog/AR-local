import hashlib
import json

import pytest

from cdr_terms.journal_reconciliation import reconcile_export
from cdr_terms.journal_sources import JournalSource


def fixture(tmp_path, *, product_id="p", detail="Account", duplicate=False):
    body = b'{"data":{"productId":"p","name":"Account"}}'
    source = JournalSource("bank", "p", "body", "event", hashlib.sha256(body).hexdigest(),
                           "2026-09-14T15:00:00Z", body)
    product = {"provider": "bank", "product_id": product_id, "product_key": "bank|p||Account",
               "details_json": json.dumps({"productId": "p", "name": detail})}
    document = {"run_date": "2026-09-15", "products": [product] * (2 if duplicate else 1)}
    raw = json.dumps(document).encode(); path = tmp_path / "banks.json"; path.write_bytes(raw)
    contract = {"normalization_version": "legacy-v1", "observation_date": "2026-09-15",
                "observation_state": "partial", "provider_states": [{"provider_dir": "bank", "provider_uid": "uid"}],
                "artifacts": [{"path": "banks.json", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]}
    return contract, (source,), path


def test_exact_selected_projection(tmp_path):
    result = reconcile_export(*fixture(tmp_path), artifact_path="banks.json")
    assert result["products"] == 1 and result["observation_state"] == "partial"
    assert result["full_population_accounting"] is False


@pytest.mark.parametrize("options,error", [({"product_id": "wrong"}, "identity_mismatch"),
                                         ({"detail": "Altered"}, "projection_mismatch"),
                                         ({"duplicate": True}, "count_mismatch")])
def test_rejects_bound_but_inconsistent_projection(tmp_path, options, error):
    with pytest.raises(ValueError, match=error):
        reconcile_export(*fixture(tmp_path, **options), artifact_path="banks.json")


def test_rejects_tampered_export(tmp_path):
    contract, sources, path = fixture(tmp_path); path.write_bytes(b"altered")
    with pytest.raises(ValueError, match="integrity_mismatch"):
        reconcile_export(contract, sources, path, artifact_path="banks.json")


def test_rejects_unknown_normalization(tmp_path):
    contract, sources, path = fixture(tmp_path); contract["normalization_version"] = "future"
    with pytest.raises(ValueError, match="normalization_unsupported"):
        reconcile_export(contract, sources, path, artifact_path="banks.json")
