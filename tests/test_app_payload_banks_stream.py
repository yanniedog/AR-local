"""Captured bank data plus corruption/resource controls for full-byte streaming."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from app_payload_banks_stream import Limits, Reader, read_banks
from app_payload_bank_catalogue import RetainedEvidenceCache, StreamedRetainedEvidence, retained_evidence
from tests.test_bank_rate_history_selected_source import banks, DAY, save_export
from tests.test_retained_evidence_cache import product


def save(tmp_path, value):
    path = tmp_path / "banks.json"
    path.write_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    return path


@pytest.mark.parametrize("chunk", [1, 2, 7, 64, 65536])
def test_original_captured_document_and_digest_are_identical(tmp_path, banks, chunk):
    path = save(tmp_path, banks)
    expected = path.read_bytes()
    actual, sha, count = read_banks(path, limits=replace(Limits(), chunk_bytes=chunk))
    assert actual == banks
    assert sha == hashlib.sha256(expected).hexdigest() and count == len(expected)


def test_whole_original_above_old_128_mib_cap_streams_without_read_all(tmp_path, banks, monkeypatch):
    path = save(tmp_path, banks)
    # JSON whitespace is a storage-size control, not generated financial data.
    with path.open("ab") as output:
        for _ in range(129):
            output.write(b" " * 1024**2)
    def forbidden(*args, **kwargs):
        raise AssertionError("whole-file allocation")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    actual, sha, count = read_banks(path)
    assert actual == banks and count == path.stat().st_size > 128 * 1024**2
    assert len(sha) == 64


@pytest.mark.parametrize("fault", [b'{"rates":[]', b'{"rates":[],}', b'{"rates":[1,]}',
                                  b'{"rates":[],"rates":[]}', b'{"x":{"y":1,"y":2}}',
                                  b'{"rates":[]} false', b'{"rates":[]}\xff'])
def test_invalid_complete_source_is_never_accepted(tmp_path, fault):
    path = tmp_path / "banks.json"
    path.write_bytes(fault)
    with pytest.raises((ValueError, UnicodeError)):
        read_banks(path, limits=replace(Limits(), chunk_bytes=2))


def test_number_token_split_and_unicode_are_not_truncated(tmp_path):
    # Parser controls only; never used as acceptance bank/rate records.
    value = {"numbers": [12.3e-8, -12345, 0.75], "text": "é☀"}
    assert read_banks(save(tmp_path, value), limits=replace(Limits(), chunk_bytes=1))[0] == value


@pytest.mark.parametrize("limit", ["source_bytes", "value_bytes", "retained_bytes", "array_rows"])
def test_limits_fail_explicitly_without_truncating(tmp_path, banks, limit):
    path = save(tmp_path, banks)
    with pytest.raises(ValueError, match="budget|oversized"):
        read_banks(path, limits=replace(Limits(), **{limit: 1}))


def test_growth_is_bounded_even_after_initial_size_check(tmp_path, banks):
    path = save(tmp_path, banks)
    limit = path.stat().st_size
    with path.open("rb") as source:
        reader = Reader(source, replace(Limits(), source_bytes=limit, chunk_bytes=1))
        reader.more()
        with path.open("ab") as output:
            output.write(b" " * 20)
        with pytest.raises(ValueError, match="source exceeds"):
            reader.document(retain_fields=None, product_consumer=None)


def test_discarded_product_bytes_still_bound_to_contract(tmp_path, banks):
    path = save(tmp_path, banks)
    raw = path.read_bytes()
    expected = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    projected = StreamedRetainedEvidence()
    actual, _, _ = read_banks(path, product_consumer=projected.consume, expected=expected)
    assert actual["products"] == [] and actual["rates"] == banks["rates"]
    assert projected.result == retained_evidence(banks["products"])
    changed = deepcopy(banks)
    changed["products"][0]["description"] = "deliberate source tamper control"
    save(tmp_path, changed)
    with pytest.raises(ValueError, match="differs from its contract"):
        read_banks(path, product_consumer=StreamedRetainedEvidence().consume, expected=expected)


@pytest.mark.parametrize("variant", ["identical", "conflict", "unknown", "negative", "condition"])
def test_streamed_evidence_matches_existing_conservative_projection(product, variant):
    changed = deepcopy(product)
    if variant == "conflict":
        changed["details_json"]["productId"] = "wrong identity control"
    if variant == "unknown":
        changed["details_json"] = None
    if variant == "negative":
        changed["details_json"]["description"] = "No offset facility."
    if variant == "condition":
        changed["details_json"]["features"] = [{"featureType": "OFFSET", "additionalInfo": "Only with package."}]
    rows = [product, changed, changed, product, None, {}]
    projected = StreamedRetainedEvidence(cache=RetainedEvidenceCache())
    for row in rows:
        projected.consume(row)
    assert projected.result == retained_evidence(rows)


def test_evidence_budget_fails_instead_of_omitting(product):
    projected = StreamedRetainedEvidence(max_bytes=1)
    with pytest.raises(ValueError, match="projection budget"):
        projected.consume(product)


def test_selected_history_projection_preserves_full_source_binding(tmp_path, banks):
    from app_payload_bank_rate_source import historical_banks
    exports = save_export(tmp_path, banks)
    evidence, sources = StreamedRetainedEvidence(), {}
    actual = historical_banks(exports, DAY, {}, sources, product_consumer=evidence.consume)
    assert actual["rates"] == banks["rates"] and actual["products"] == []
    assert evidence.result == retained_evidence(banks["products"])
    raw = (exports / "dashboard-cache" / DAY / "banks.json").read_bytes()
    assert sources[DAY]["banks_sha256"] == hashlib.sha256(raw).hexdigest()
    assert sources[DAY]["bytes"] == len(raw)


def test_rate_only_projection_validates_discarded_tail(tmp_path, banks):
    path = save(tmp_path, banks)
    projected, _, _ = read_banks(path, retain_fields={"run_date", "rates"})
    assert projected == {key: banks[key] for key in ("run_date", "rates")}
    with path.open("ab") as output:
        output.write(b"wrong")
    with pytest.raises(ValueError, match="Trailing"):
        read_banks(path, retain_fields={"run_date", "rates"})


def test_source_mutation_while_product_is_projected_is_rejected(tmp_path, banks):
    path = save(tmp_path, banks)
    def mutate(_):
        with path.open("ab") as output:
            output.write(b" ")
    with pytest.raises(ValueError, match="changed during read"):
        read_banks(path, product_consumer=mutate)


def test_top_level_metadata_cannot_allocate_unbounded_key_map(tmp_path):
    path = save(tmp_path, {str(i): [] for i in range(129)})
    with pytest.raises(ValueError, match="Invalid or duplicate"):
        read_banks(path)
