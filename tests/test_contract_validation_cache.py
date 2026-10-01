"""Repeated history verification stays content-bound and invocation-scoped."""
import json
from unittest.mock import patch

import pytest

import cdr_export_contract as contracts
from cdr_finalization import finalize_observation, verify_completion_marker
from tests.test_irreplaceable_finalization import DATE, make_export


@pytest.fixture
def finalized(tmp_path):
    export = tmp_path / "runs" / DATE / "_exports"
    make_export(export)
    state = tmp_path / "state"
    marker = finalize_observation(
        export, state, state / f"{DATE}.done.json", observation_date=DATE,
        result={"run_date": DATE, "banks_counts": {"rates": 7}},
    )
    return state / marker["export_contract_path"], export, state, marker


def test_identical_contract_validated_once_without_sharing_mutable_results(finalized):
    path, _, _, _ = finalized
    with patch.object(contracts, "validate_contract", wraps=contracts.validate_contract) as validate:
        with contracts.contract_validation_cache():
            first = contracts.load_contract(path)
            expected = json.loads(path.read_bytes())
            first["coverage"]["eligible_rate_rows"] = 999
            with contracts.contract_validation_cache():
                assert contracts.load_contract(path) == expected
            assert validate.call_count == 1
        assert contracts.load_contract(path) == expected
        assert validate.call_count == 2


@pytest.mark.parametrize("fault", ["schema", "digest", "source", "missing"])
def test_changed_source_cannot_reuse_successful_validation(finalized, fault):
    path, _, _, _ = finalized
    with contracts.contract_validation_cache():
        original = contracts.load_contract(path)
        changed = dict(original)
        if fault == "schema":
            changed["schema_version"] = 999
        elif fault == "digest":
            changed["contract_digest"] = "0" * 64
        elif fault == "source":
            changed["source_path"] += "-changed"
        else:
            path.unlink()
        if fault != "missing":
            path.write_text(json.dumps(changed), encoding="utf-8")
        for _ in range(2):
            with pytest.raises((ValueError, FileNotFoundError)):
                contracts.load_contract(path)


def test_cache_does_not_skip_artifact_rehash(finalized):
    path, export, state, marker = finalized
    with contracts.contract_validation_cache():
        assert verify_completion_marker(marker, state, DATE)
        original = (export / "banks.json").read_bytes()
        (export / "banks.json").write_bytes(original.replace(b"rates", b"other"))
        assert contracts.load_contract(path)
        assert not verify_completion_marker(marker, state, DATE)


def test_budgeted_validation_keeps_full_checks(finalized):
    path, _, _, _ = finalized
    charges = []
    with patch.object(contracts, "validate_contract", wraps=contracts.validate_contract) as validate:
        with contracts.contract_validation_cache():
            contracts.load_contract(path)
            contracts.load_contract(path, budget=lambda **charge: charges.append(charge))
            assert validate.call_count == 2
    assert any(charge.get("size") for charge in charges)


def test_exception_clears_invocation_cache(finalized):
    path, _, _, _ = finalized
    with patch.object(contracts, "validate_contract", wraps=contracts.validate_contract) as validate:
        with pytest.raises(RuntimeError):
            with contracts.contract_validation_cache():
                contracts.load_contract(path)
                raise RuntimeError("aborted build")
        with contracts.contract_validation_cache():
            contracts.load_contract(path)
        assert validate.call_count == 2


def test_validation_digest_cache_is_bounded(finalized, monkeypatch):
    path, _, _, _ = finalized
    monkeypatch.setattr(contracts, "_MAX_VALIDATED_CONTRACTS", 1)
    original = path.read_bytes()
    changed = json.loads(original)
    changed["observed_at"] = "2026-08-14T12:00:00Z"
    changed["contract_digest"] = contracts.contract_digest(changed)
    with patch.object(contracts, "validate_contract", wraps=contracts.validate_contract) as validate:
        with contracts.contract_validation_cache():
            contracts.load_contract(path)
            path.write_text(json.dumps(changed), encoding="utf-8")
            contracts.load_contract(path)
            path.write_bytes(original)
            contracts.load_contract(path)
        assert validate.call_count == 3
