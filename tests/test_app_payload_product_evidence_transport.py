"""Real captured facts remain complete through bounded delivery regrouping."""
from copy import deepcopy
from dataclasses import replace
import gzip

import pytest

import app_payload_product_evidence_transport as transport
from app_payload_product_evidence_contract import Limits, decode, digest
from app_payload_product_evidence_transport_contract import DeliveryLimits, JSON_FIELDS, validate_capability, validate_index, validate_shard
from tests.test_app_payload_product_evidence import source, build


def pack(source, tmp_path, **kwargs):
    root, snapshot = build(source, tmp_path, limits=replace(Limits(), page_rows=3))
    output = tmp_path / "delivery"
    prepared = transport.pack_snapshot(root, output, expected_source=snapshot["source"],
                                       core_sha256="a" * 64, details_sha256="b" * 64, **kwargs)
    return root, snapshot, output, prepared


def read_asset(output, descriptor):
    raw = (output / descriptor["name"]).read_bytes()
    assert len(raw) == descriptor["bytes"] and digest(raw) == descriptor["sha256"]
    decoded = gzip.decompress(raw)
    assert len(decoded) == descriptor["decoded_bytes"]
    return decode(decoded)


def test_actual_facts_roundtrip_and_every_route_exact(source, tmp_path):
    from app_payload_product_evidence import iter_product_facts
    root, snapshot, output, prepared = pack(source, tmp_path)
    assert prepared["publication_authorized"] is False and prepared["selection_verified"] is False
    capability = prepared["capability"]
    assert capability["binding"]["source"] == snapshot["source"]
    assert capability["binding"]["snapshot_sha256"] == digest((root / "snapshot.json").read_bytes())
    validate_capability(capability)
    index = read_asset(output, capability["index"])
    validate_index(index, capability)
    shards = {item["sha256"]: read_asset(output, item) for item in capability["shards"]}
    for shard in shards.values():
        validate_shard(shard, capability)
    for product in index["products"]:
        actual = []
        for sequence, page in enumerate(product["pages"]):
            value = shards[page["shard"]]["pages"][page["page"]]
            assert value["identity"] == product["identity"] and value["sequence"] == sequence
            assert len(value["facts"]) == page["facts"]
            actual.extend(value["facts"])
        assert actual == [transport.wire_fact(fact) for fact in iter_product_facts(root, product["identity"]["product_key"])]
    assert sum(len(s["pages"]) for s in shards.values()) == snapshot["totals"]["pages"]


def test_identical_snapshot_builds_identical_assets(source, tmp_path):
    root, snapshot, first, prepared = pack(source, tmp_path)
    second = tmp_path / "delivery-second"
    again = transport.pack_snapshot(root, second, expected_source=snapshot["source"], core_sha256="a" * 64, details_sha256="b" * 64)
    assert prepared == again
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name: p.read_bytes() for p in second.iterdir()}


@pytest.mark.parametrize("field", ["namespace_bytes", "index_raw_bytes", "index_compressed_bytes", "shard_raw_bytes",
                                  "shard_compressed_bytes", "raw_bytes", "compressed_bytes", "product_raw_bytes",
                                  "product_compressed_bytes"])
def test_reduced_limits_fail_without_completion(source, tmp_path, field):
    with pytest.raises(ValueError, match="budget"):
        pack(source, tmp_path, limits=replace(DeliveryLimits(), **{field: 1}))
    assert not (tmp_path / "delivery/prepared.json").exists()


@pytest.mark.parametrize("fault", ["wrong_source", "corrupt_page", "incomplete_snapshot"])
def test_no_fallback_for_detached_or_corrupt_snapshot(source, tmp_path, fault):
    root, snapshot = build(source, tmp_path)
    expected = deepcopy(snapshot["source"])
    if fault == "wrong_source":
        expected["contract_digest"] = "c" * 64
    elif fault == "corrupt_page":
        (root / snapshot["products"][0]["pages"][0]["name"]).write_bytes(b"corrupt")
    else:
        (root / "snapshot.json").unlink()
    output = tmp_path / "delivery"
    with pytest.raises(ValueError):
        transport.pack_snapshot(root, output, expected_source=expected, core_sha256="a" * 64, details_sha256="b" * 64)
    assert not (output / "prepared.json").exists()


def test_large_numeric_source_json_is_preserved_as_text(source, tmp_path):
    _, _, output, prepared = pack(source, tmp_path)
    first = read_asset(output, prepared["capability"]["shards"][0])["pages"][0]["facts"][0]
    for name in JSON_FIELDS:
        assert isinstance(first[name + "_json"], str)
    # Deliberate precision control is descriptive JSON, never a consumer rate.
    from app_payload_product_evidence_transport_contract import wire_fact, validate_wire_fact
    from app_payload_product_evidence import iter_product_facts
    root = tmp_path / "snapshot"
    manifest = decode((root / "snapshot.json").read_bytes())
    fact = next(iter_product_facts(root, manifest["products"][0]["identity"]["product_key"]))
    fact["source_value"] = 9007199254740993
    wire = wire_fact(fact)
    assert wire["source_value_json"] == "9007199254740993"
    validate_wire_fact(wire)


def test_route_cross_generation_or_duplicate_page_is_rejected(source, tmp_path):
    _, _, output, prepared = pack(source, tmp_path)
    cap = prepared["capability"]
    index = read_asset(output, cap["index"])
    altered = deepcopy(index)
    altered["binding"]["snapshot_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="detached"):
        validate_index(altered, cap)
    altered = deepcopy(index)
    altered["products"][0]["pages"].append(altered["products"][0]["pages"][0])
    with pytest.raises(ValueError, match="duplicate"):
        validate_index(altered, cap)
