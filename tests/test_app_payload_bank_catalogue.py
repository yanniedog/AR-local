"""Real published financial rows; malformed storage controls are explicit."""
from copy import deepcopy
from datetime import date, timedelta
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from app_payload_bank_catalogue import HistoricalCatalogue, published_evidence
from app_payload_prepack_history import prepack
from app_payload_revisions_state import bundle_sha256

FIXTURE = Path(__file__).parent / "fixtures/bank_rate_catalogue_real_2026-05-19_2026-09-26.json"


@pytest.fixture
def observations():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "6b03da88fb9c49ed05f938ea88f9e3f7bb2a65bc34eefb1eb54d51b3354a8334"
    return json.loads(raw)["observations"]


def packed(observations):
    first, last = date.fromisoformat(observations[0]["date"]), date.fromisoformat(observations[-1]["date"])
    axis = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    builder = HistoricalCatalogue(axis)
    for observation in observations:
        builder.observe(observation["date"], observation["sections"],
                        lambda row, section: published_evidence(row, section, observation["details"]),
                        observation["source"])
    return builder.finish()


def test_all_historical_tiers_and_date_scoped_facts_survive(observations):
    saved = deepcopy(observations)
    result = packed(observations)
    assert observations == saved
    assert result["evidence"][0] == {"status": "unknown"}
    assert len(result["sources"]) == 3
    known = [item for item in result["evidence"] if item["status"] == "known"]
    assert any(any(f.get("value") is True for f in item["detail"].get("facts", [])) for item in known)
    positions = {result["run_dates"].index(item["date"]) for item in observations}
    for section, tiers in result["sections"].items():
        current = {row["product_key"] for row in observations[-1]["sections"][section]}
        assert any(tier["row"]["product_key"] not in current for tier in tiers)
        for tier in tiers:
            assert "rate" not in tier["row"] and "rate_index" not in tier["row"]
            for start, count, rates, evidence_id in tier["spans"]:
                assert set(range(start, start + count)) <= positions
                assert rates == sorted(rates) and rates
                evidence = result["evidence"][evidence_id]
                if evidence["status"] == "known":
                    assert evidence["identity"]["product_key"] == tier["row"]["product_key"]
                    assert evidence["identity"]["dataset"] == section
    assert any(span[1] == 2 for tiers in result["sections"].values() for tier in tiers for span in tier["spans"])


@pytest.mark.parametrize("fault", ["missing", "wrong_provider", "malformed_facts", "malformed_constraints"])
def test_unknown_or_conflicting_published_metadata_cannot_donate_features(observations, fault):
    current = observations[-1]
    row = current["sections"]["Mortgage"][0]
    assert published_evidence(row, "Mortgage", current["details"])["status"] == "known"
    details = deepcopy(current["details"])
    if fault == "missing":
        details.pop(row["product_key"])
    elif fault == "wrong_provider":
        details[row["product_key"]]["displayIdentity"] = {"provider": "identity mismatch control"}
    else:
        details[row["product_key"]][fault.removeprefix("malformed_")] = "invalid container control"
    assert published_evidence(row, "Mortgage", details) == {"status": "unknown"}


def public_cache(tmp_path, observations):
    """Real row/detail slices inside operational-only test publication envelopes."""
    root = tmp_path / "source"
    for folder in ("cores", "details", "manifests"):
        (root / folder).mkdir(parents=True)
    index = {"schema_version": 1, "revision_protocol": 1, "dates": [], "revision_heads": {}}
    for observation in observations:
        day = observation["date"]
        tag = "app-payload-" + day + "-r000001"
        base = "https://github.com/yanniedog/AR-local/releases/download/" + tag
        manifest = {"schema_version": 1, "run_date": day, "tag": tag, "files": {}}
        for key, folder, data in (("core", "cores", {"sections": {s: {"rates": rows} for s, rows in observation["sections"].items()}}),
                                  ("details", "details", {"products": observation["details"]})):
            blob = gzip.compress(json.dumps({"schema_version": 1, "run_date": day, **data}).encode(), mtime=0)
            sha = hashlib.sha256(blob).hexdigest()
            (root / folder / (sha + ".gz")).write_bytes(blob)
            name = key + "-" + day + "-" + sha[:12] + ".json.gz"
            manifest["files"][key] = {"name": name, "bytes": len(blob), "sha256": sha, "url": base + "/" + name}
        bundle = bundle_sha256(manifest)
        head = {"revision": 1, "generation_id": "sha256-" + bundle, "bundle_sha256": bundle}
        manifest["payload_revision"] = {"schema_version": 1, **head, "parent_revision": None}
        raw = json.dumps(manifest).encode()
        (root / "manifests" / (day + ".json")).write_bytes(raw)
        index["dates"].append(day)
        index["revision_heads"][day] = {**head, "manifest_url": base + "/manifest.json", "manifest_sha256": hashlib.sha256(raw).hexdigest()}
    index.update(count=len(index["dates"]), latest_date=index["dates"][-1])
    raw = json.dumps(index).encode()
    (root / "dates-index.json").write_bytes(raw)
    return root, hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("nested", [False, True])
def test_private_prepack_verifies_complete_sources_without_changing_input(tmp_path, observations, nested):
    root, index_sha = public_cache(tmp_path, observations)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
    output = (root if nested else tmp_path) / "derived"
    report = prepack(root, output, index_sha256=index_sha)
    core = json.loads((output / "core.json").read_bytes())
    assert core["bank_rate_history_catalogue"]["sections"] == packed(observations)["sections"]
    assert report["status"] == "PASS" and report["publication_verified"] is False
    assert report["observed_dates"] == 3 and report["source_count"] == 3
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == value for path, value in before.items())
    with pytest.raises(ValueError, match="new directory"):
        prepack(root, output, index_sha256=index_sha)


@pytest.mark.parametrize("fault", ["index", "manifest", "core", "details"])
def test_private_prepack_rejects_corrupt_bound_inputs(tmp_path, observations, fault):
    root, index_sha = public_cache(tmp_path, observations)
    if fault == "index":
        index_sha = "0" * 64
    else:
        folder = {"manifest": "manifests", "core": "cores", "details": "details"}[fault]
        target = next((root / folder).iterdir())
        target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError, match="differs"):
        prepack(root, tmp_path / "derived", index_sha256=index_sha)
    assert not (tmp_path / "derived").exists()
