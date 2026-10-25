"""Archive integrity and bounded lazy loading; all records are transport-only."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cdr_atomic import atomic_write_json, canonical_json_bytes
from cdr_public_rates_candidate import (
    MAX_CHUNK_BYTES, candidate_digest, programme_ids, read_candidate,
    selected_evidence, selected_programmes, write_chunks,
)


def archive(tmp_path, *, count=40, padding=900000):
    # Deliberately larger than the entire public 24 MiB budget. The private
    # derived archive may hold disabled programmes; only reviewed subsets ship.
    records = ({"programmeId": str(index), "transportOnly": "x" * padding} for index in range(count))
    chunks = write_chunks(tmp_path, "generation-A", "programme", records)
    evidence = write_chunks(tmp_path, "generation-A", "evidence", [{"evidenceId": "public-source", "transportOnly": True}])
    body = {"schemaVersion": 1, "generationId": "generation-A", "programmes": [], "evidence": [],
            "programmeChunks": chunks, "evidenceChunks": evidence}
    sha = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    path = tmp_path / (sha + ".json")
    atomic_write_json(path, body, create_once=True)
    return path, body


def test_large_internal_archive_loads_only_the_selected_subset(tmp_path, monkeypatch):
    path, body = archive(tmp_path)
    assert sum(item["bytes"] for item in body["programmeChunks"]) > 24 * 1024**2
    assert all(item["bytes"] <= MAX_CHUNK_BYTES for item in body["programmeChunks"])
    candidate = read_candidate(path)
    opened = []
    original = Path.read_bytes
    def read(file):
        opened.append(file.name)
        return original(file)
    monkeypatch.setattr(Path, "read_bytes", read)
    assert len(programme_ids(candidate)) == 40
    assert opened == []
    selected = selected_programmes(candidate, {"39"})
    assert selected[0]["programmeId"] == "39"
    assert len(opened) == 1
    assert candidate_digest(candidate) == path.stem
    assert selected_evidence(candidate, {"public-source"})[0]["transportOnly"]
    with pytest.raises(ValueError, match="verified_file_context"):
        selected_programmes(body, {"39"})


def test_corrupt_chunk_and_mixed_generation_fail_closed(tmp_path):
    path, body = archive(tmp_path, count=1, padding=10)
    candidate = read_candidate(path)
    descriptor = body["programmeChunks"][0]
    chunk_path = tmp_path / descriptor["name"]
    chunk_path.write_bytes(chunk_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="binding_mismatch"):
        selected_programmes(candidate, {"0"})
    other = {"schemaVersion": 1, "generationId": "generation-B", "programmes": [{"programmeId": "0", "transportOnly": "x" * 10}]}
    raw = canonical_json_bytes(other)
    digest = hashlib.sha256(raw).hexdigest()
    atomic_write_json(tmp_path / (digest + ".json"), other)
    candidate["programmeChunks"] = [{"name": digest + ".json", "sha256": digest, "bytes": len(raw), "programmeIds": ["0"]}]
    with pytest.raises(ValueError, match="binding_mismatch"):
        selected_programmes(candidate, {"0"})


def test_unfinished_candidate_does_not_replace_the_verified_pointer(tmp_path):
    path, _ = archive(tmp_path, count=1, padding=10)
    pointer = tmp_path / "candidate-pointer.json"
    atomic_write_json(pointer, {"candidateFile": path.name, "sha256": path.stem})
    calls = 0
    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise TimeoutError("admission deadline")
    with pytest.raises(TimeoutError, match="admission"):
        write_chunks(tmp_path, "generation-new", "programme", [{"programmeId": str(i)} for i in range(8)], checkpoint=checkpoint)
    assert read_candidate(pointer).capture_sha256 == path.stem
    atomic_write_json(pointer, {"candidateFile": "../outside.json", "sha256": path.stem})
    with pytest.raises(ValueError, match="pointer"):
        read_candidate(pointer)


def test_missing_duplicate_and_oversized_records_are_rejected(tmp_path):
    path, body = archive(tmp_path, count=1, padding=10)
    with pytest.raises(ValueError, match="not_retained"):
        selected_programmes(read_candidate(path), {"absent"})
    with pytest.raises(ValueError, match="conflicting"):
        write_chunks(tmp_path, "g", "programme", [{"programmeId": "same"}, {"programmeId": "same"}])
    with pytest.raises(ValueError, match="record_budget"):
        write_chunks(tmp_path, "g", "programme", [{"programmeId": "big", "padding": "x" * MAX_CHUNK_BYTES}])
    body["programmeChunks"] *= 2
    atomic_write_json(tmp_path / "duplicated.json", body)
    with pytest.raises(ValueError, match="invalid_public_candidate_chunk"):
        read_candidate(tmp_path / "duplicated.json")
