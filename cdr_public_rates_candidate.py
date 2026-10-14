"""Bounded, generation-bound internal candidate archive in the evidence root.

This derived cache is separate from the smaller published app catalogue. Source
observations and programme versions remain in the original evidence database.
Only approved programmes and their evidence are loaded by the public publisher.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Callable

from cdr_atomic import atomic_write_json, canonical_json_bytes

MAX_ROOT_BYTES = 24 * 1024**2
MAX_CHUNK_BYTES = 4 * 1024**2
MAX_CHUNKS = 2048
MAX_CHUNK_IDENTITIES = 10000
SHA = re.compile(r"[0-9a-f]{64}\Z")


class Candidate(dict):
    def __init__(self, body: dict, *, path: Path, capture_sha256: str):
        super().__init__(body)
        self.path = path
        self.capture_sha256 = capture_sha256


def candidate_digest(candidate: dict) -> str:
    if isinstance(candidate, Candidate):
        return candidate.capture_sha256
    return hashlib.sha256(canonical_json_bytes(candidate)).hexdigest()


def _json(path: Path, maximum: int) -> tuple[dict, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("public_candidate_file_missing_or_oversized")
    raw = path.read_bytes()
    if len(raw) > maximum:
        raise ValueError("public_candidate_file_oversized")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("public_candidate_object_required")
    return value, hashlib.sha256(raw).hexdigest()


def read_candidate(path: Path) -> Candidate:
    path = Path(path)
    value, identity = _json(path, MAX_ROOT_BYTES)
    if "candidateFile" in value:
        expected = value.get("sha256")
        relative = Path(value["candidateFile"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("invalid_public_candidate_pointer")
        target = path.parent / relative
        if target.is_symlink() or path.parent.resolve() not in target.resolve().parents:
            raise ValueError("invalid_public_candidate_pointer")
        value, captured = _json(target, MAX_ROOT_BYTES)
        if captured != expected:
            raise ValueError("public_candidate_pointer_hash_mismatch")
        path, identity = target, captured
    if len(path.stem) == 64 and path.stem != identity:
        raise ValueError("public_candidate_filename_hash_mismatch")
    if value.get("schemaVersion") != 1 or not isinstance(value.get("generationId"), str):
        raise ValueError("public_candidate_generation_required")
    candidate = Candidate(value, path=path, capture_sha256=identity)
    _descriptors(candidate, "programme")
    _descriptors(candidate, "evidence")
    return candidate


def _descriptors(candidate: dict, kind: str) -> dict[str, dict]:
    chunks = candidate.get(kind + "Chunks", [])
    if not isinstance(chunks, list) or len(chunks) > MAX_CHUNKS:
        raise ValueError("public_candidate_chunk_budget_exceeded")
    result, names = {}, set()
    for item in chunks:
        if (not isinstance(item, dict) or not isinstance(item.get("sha256"), str)
                or not SHA.fullmatch(item["sha256"]) or item.get("name") != item["sha256"] + ".json"
                or item["name"] in names or type(item.get("bytes")) is not int
                or not 1 <= item["bytes"] <= MAX_CHUNK_BYTES):
            raise ValueError("invalid_public_candidate_chunk")
        ids = item.get(kind + "Ids")
        if (not isinstance(ids, list) or not ids or len(ids) > MAX_CHUNK_IDENTITIES
                or not all(isinstance(key, str) and 0 < len(key) <= 4096 for key in ids)
                or len(ids) != len(set(ids))):
            raise ValueError("invalid_public_candidate_chunk_identities")
        names.add(item["name"])
        for key in ids:
            if key in result:
                raise ValueError("conflicting_public_candidate_identity")
            result[key] = item
    return result


def programme_ids(candidate: dict) -> set[str]:
    inline = {p["programmeId"] for p in candidate["programmes"]}
    chunks = set(_descriptors(candidate, "programme"))
    if inline & chunks:
        raise ValueError("conflicting_public_candidate_identity")
    return inline | chunks


def _select(candidate: dict, requested: set[str], kind: str) -> list[dict]:
    field = "programmes" if kind == "programme" else "evidence"
    identity_field = kind + "Id"
    result = {}
    for item in candidate[field]:
        key = item[identity_field]
        if key in result:
            raise ValueError("conflicting_public_candidate_identity")
        if key in requested:
            result[key] = item
    descriptors = _descriptors(candidate, kind)
    missing = requested - set(result)
    if not missing <= set(descriptors):
        raise ValueError("public_candidate_identity_not_retained")
    needed = {descriptors[key]["name"]: descriptors[key] for key in missing}
    if needed and not isinstance(candidate, Candidate):
        raise ValueError("public_candidate_chunks_require_verified_file_context")
    for descriptor in needed.values():
        path = candidate.path.parent / descriptor["name"]
        if path.is_symlink() or path.parent.resolve() not in path.resolve().parents:
            raise ValueError("invalid_public_candidate_chunk_path")
        chunk, identity = _json(path, MAX_CHUNK_BYTES)
        if (identity != descriptor["sha256"] or path.stat().st_size != descriptor["bytes"]
                or chunk.get("schemaVersion") != 1 or chunk.get("generationId") != candidate["generationId"]):
            raise ValueError("public_candidate_chunk_binding_mismatch")
        records = chunk.get(field)
        if not isinstance(records, list) or len(records) != len(descriptor[kind + "Ids"]):
            raise ValueError("public_candidate_chunk_routing_mismatch")
        keys = [item[identity_field] for item in records]
        if len(keys) != len(set(keys)) or set(keys) != set(descriptor[kind + "Ids"]):
            raise ValueError("public_candidate_chunk_routing_mismatch")
        for item in records:
            if item[identity_field] in requested:
                result[item[identity_field]] = item
    return [result[key] for key in sorted(requested)]


def selected_programmes(candidate: dict, ids: set[str]) -> list[dict]:
    return _select(candidate, ids, "programme")


def selected_evidence(candidate: dict, ids: set[str]) -> list[dict]:
    return _select(candidate, ids, "evidence")


def write_chunks(directory: Path, generation: str, kind: str, records: Iterable[dict],
                 *, checkpoint: Callable[[], None] | None = None) -> list[dict]:
    """Stream bounded chunks; never materialise the complete candidate archive."""
    field = "programmes" if kind == "programme" else "evidence"
    identity_field = kind + "Id"
    prefix = canonical_json_bytes({"schemaVersion": 1, "generationId": generation, field: []})
    current, size, descriptors, seen = [], len(prefix), [], set()

    def flush():
        nonlocal current, size
        if not current:
            return
        if checkpoint:
            checkpoint()
        value = {"schemaVersion": 1, "generationId": generation, field: current}
        body = canonical_json_bytes(value)
        if len(body) > MAX_CHUNK_BYTES:
            raise ValueError("public_candidate_record_budget_exceeded")
        identity = hashlib.sha256(body).hexdigest()
        name = identity + ".json"
        atomic_write_json(directory / name, value, create_once=True)
        descriptors.append({"name": name, "sha256": identity, "bytes": len(body),
                            kind + "Ids": [item[identity_field] for item in current]})
        if len(descriptors) > MAX_CHUNKS:
            raise ValueError("public_candidate_chunk_budget_exceeded")
        current, size = [], len(prefix)

    for record in records:
        if checkpoint:
            checkpoint()
        key = record[identity_field]
        if key in seen:
            raise ValueError("conflicting_public_candidate_identity")
        seen.add(key)
        record_size = len(canonical_json_bytes(record))
        if record_size + len(prefix) > MAX_CHUNK_BYTES:
            raise ValueError("public_candidate_record_budget_exceeded")
        if current and (size + record_size > MAX_CHUNK_BYTES or len(current) >= MAX_CHUNK_IDENTITIES):
            flush()
        current.append(record)
        size += record_size
    flush()
    return descriptors
