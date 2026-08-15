"""Contract-level regression tests for dormant historical candidates."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import json

import pytest
from jsonschema import ValidationError

from cdr_historical_contract import (
    HistoricalContractError,
    candidate_identity,
    canonical_json_bytes,
    sha256_bytes,
    strict_json_bytes,
    unique_portable_paths,
    validate_candidate,
    validate_contract_tree,
    validate_history_index,
    validate_source_manifest,
)


DIGEST = "1" * 64
COMMIT = "2" * 40


def _unavailable() -> dict[str, object]:
    return {"state": "unavailable", "value": None, "reason": "not retained"}


def _candidate() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "contract": "legacy-historical-candidate-v1",
        "coordinate": {"date": "2026-05-13", "variant_ordinal": 1, "revision_ordinal": 1},
        "lineage": {"relation": "root_projection", "parent_candidate_sha256": None, "parent_source_manifest_sha256": None},
        "observation_state": "partial",
        "promotion_eligible": False,
        "blockers": ["partial evidence"],
        "source": {"snapshot_id": "snapshot", "source_manifest_sha256": DIGEST, "variant_sha256": DIGEST},
        "tool": {"commit": COMMIT, "python_version": "locked", "files": [{"path": "tool.py", "bytes": 1, "sha256": DIGEST}]},
        "populations": {"products": 1, "rates": 1, "failures": 0},
        "quarantine": {"semantic_collision_groups": 0, "semantic_collision_rows": 0, "semantic_duplicate_same_value_groups": 0, "semantic_duplicate_same_value_rows": 0, "semantic_nonunique_rows": 0, "td_no_evidence_terms": 0, "taxonomy_rows": 0, "missing_evidence_rows": 0},
        "unavailable": {"register": _unavailable(), "providers": _unavailable(), "attempts": _unavailable()},
        "artifacts": [{"path": "pi/data/banks.json", "bytes": 10, "sha256": DIGEST}],
    }
    identity = candidate_identity(value)
    value["candidate_id"] = f"hist-2026-05-13-v0001-r0001-{identity[:12]}"
    return value


def test_contract_tree_is_dormant_and_exact() -> None:
    lock = validate_contract_tree()
    assert lock["retained_dates"] == 92
    assert lock["gap_entries"] == 2
    assert lock["minimum_candidates"] == 95
    assert lock["critical_population"] == {
        "files": 1932,
        "bytes": 25586769110,
        "products": 230852,
        "rates": 1319589,
        "failures": 8077,
    }
    assert lock["candidate_input_population"] == {
        "files": 1495,
        "bytes": 21179877992,
    }
    assert lock["immutable_critical_population"] == {
        "files": 1756,
        "bytes": 21280983214,
    }
    assert lock["transient_evidence_population"]["candidate_input"] is False
    assert lock["transient_evidence_population"]["files"] == 176


def test_strict_json_rejects_duplicate_keys_and_non_finite_values() -> None:
    with pytest.raises(HistoricalContractError, match="duplicate JSON key"):
        strict_json_bytes(b'{"a":1,"a":2}')
    with pytest.raises(HistoricalContractError, match="non-finite"):
        strict_json_bytes(b'{"a":NaN}')


@pytest.mark.parametrize(
    "path",
    ["/absolute.json", "C:/drive.json", "a/../b.json", "a\\b.json", "../escape"],
)
def test_portable_paths_reject_absolute_traversal_and_windows_forms(path: str) -> None:
    with pytest.raises(HistoricalContractError):
        unique_portable_paths([path])


def test_portable_paths_reject_casefold_collisions() -> None:
    with pytest.raises(HistoricalContractError, match="case-fold"):
        unique_portable_paths(["Evidence/A.json", "evidence/a.json"])


def test_source_manifest_binds_artifact_population_and_unavailable_is_null() -> None:
    artifacts = [{"role": "banks_projection", "path": "pi/data/banks.json", "bytes": 3, "sha256": DIGEST}]
    value = {
        "schema_version": 1,
        "contract": "legacy-historical-source-manifest-v1",
        "snapshot_id": "snapshot",
        "observation_date": "2026-05-13",
        "observation_state": "partial",
        "artifact_set_sha256": sha256_bytes(canonical_json_bytes(artifacts)),
        "artifacts": artifacts,
        "populations": {"products": 1, "rates": 1, "failures": 0},
        "unavailable": {"register": _unavailable(), "providers": _unavailable(), "attempts": _unavailable()},
        "blockers": ["not complete"],
    }
    assert validate_source_manifest(value)["unavailable"]["providers"]["value"] is None
    invalid = deepcopy(value)
    invalid["unavailable"]["providers"]["value"] = 0
    with pytest.raises(ValidationError):
        validate_source_manifest(invalid)
    transient = deepcopy(value)
    transient["artifacts"][0]["path"] = "pi/data/local-cdr.sqlite-shm"
    transient["artifact_set_sha256"] = sha256_bytes(
        canonical_json_bytes(transient["artifacts"])
    )
    with pytest.raises(HistoricalContractError, match="cannot be candidate inputs"):
        validate_source_manifest(transient)


def test_candidate_is_partial_non_promotable_and_hash_bound() -> None:
    value = _candidate()
    assert validate_candidate(value) == value
    for field, replacement in (("observation_state", "complete"), ("promotion_eligible", True)):
        invalid = deepcopy(value)
        invalid[field] = replacement
        with pytest.raises(ValidationError):
            validate_candidate(invalid)
    invalid = deepcopy(value)
    invalid["candidate_id"] = str(value["candidate_id"][:-12]) + "0" * 12
    with pytest.raises(HistoricalContractError, match="does not bind"):
        validate_candidate(invalid)


def test_candidate_rejects_operational_publication_fields() -> None:
    invalid = deepcopy(_candidate())
    invalid["latest"] = True
    with pytest.raises((ValidationError, HistoricalContractError)):
        validate_candidate(invalid)
    assert b"publisher" not in canonical_json_bytes(_candidate())
    assert b"url" not in canonical_json_bytes(_candidate()).lower()


def test_correction_requires_exact_parent_digests_and_revision() -> None:
    invalid = deepcopy(_candidate())
    invalid["lineage"]["relation"] = "legacy_external_correction"
    identity = candidate_identity(invalid)
    invalid["candidate_id"] = f"hist-2026-05-13-v0001-r0001-{identity[:12]}"
    with pytest.raises(HistoricalContractError, match="requires same-date parent"):
        validate_candidate(invalid)


def test_history_index_requires_exact_dates_gaps_and_candidate_count() -> None:
    start = date(2026, 5, 13)
    gaps = {date(2026, 5, 14), date(2026, 6, 26)}
    dates = []
    cursor = start
    while len(dates) < 92:
        if cursor not in gaps:
            dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    entries = []
    for index, value in enumerate(dates):
        count = 2 if value in {"2026-05-19", "2026-05-20", "2026-05-26"} else 1
        candidates = [
            {"candidate_id": f"candidate-{index}-{variant}", "sha256": f"{index * 2 + variant:064x}", "bytes": 1}
            for variant in range(count)
        ]
        entries.append({"date": value, "candidates": candidates})
    value = {
        "schema_version": 1,
        "contract": "legacy-historical-index-v1",
        "dates": entries,
        "gaps": [
            {"date": "2026-05-14", "status": "known_gap", "reason": "none"},
            {"date": "2026-06-26", "status": "unclassified_gap", "reason": "none"},
        ],
        "candidate_count": 95,
        "updates_operational_latest_complete": False,
    }
    assert validate_history_index(value)["candidate_count"] == 95
    invalid = json.loads(json.dumps(value))
    invalid["dates"].reverse()
    with pytest.raises(HistoricalContractError, match="sorted"):
        validate_history_index(invalid)
