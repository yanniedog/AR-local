"""Read private detail-source archives without extracting or mutating evidence."""
from __future__ import annotations

import hashlib
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cdr_export_contract import load_contract


@dataclass(frozen=True)
class JournalSource:
    provider: str
    product_id: str
    relative_path: str
    event_path: str
    sha256: str
    response_completed_at: str
    body: bytes


def _read_members(archive_path: Path, inventory: dict, max_bytes: int) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    total = 0
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive:
            name = member.name
            path = PurePosixPath(name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or "\\" in name or name in members or name not in inventory
                    or not name.startswith("attempt-evidence/")):
                raise ValueError("journal_archive_member_invalid")
            expected = inventory[name]
            total += member.size
            if (member.size != expected["bytes"] or member.size > 16 * 1024 * 1024
                    or total > max_bytes or len(members) >= 20000):
                raise ValueError("journal_archive_bounds_exceeded")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("journal_archive_member_unreadable")
            body = stream.read(member.size + 1)
            if len(body) != member.size or hashlib.sha256(body).hexdigest() != expected["sha256"]:
                raise ValueError("journal_archive_digest_mismatch")
            members[name] = body
    return members


def read_detail_sources(archive_path: Path, contract_path: Path, *,
                        max_bytes: int = 64 * 1024 * 1024) -> tuple[JournalSource, ...]:
    """Validate a subset of a finalized source; never claim complete coverage.

    Caller must independently bind the contract to a finalized marker/ledger,
    reconcile accounting, and retain partial coverage before issuing a capture.
    """
    contract = load_contract(contract_path)
    return _read_detail_sources(archive_path, contract, max_bytes=max_bytes)


def _read_detail_sources(archive_path: Path, contract: dict, *,
                         max_bytes: int = 64 * 1024 * 1024) -> tuple[JournalSource, ...]:
    """Internal path for a caller retaining one already validated contract."""
    if not 0 < max_bytes <= 128 * 1024 * 1024:
        raise ValueError("journal_archive_invalid_budget")
    inventory = {a["path"]: a for a in contract["artifacts"]}
    members = _read_members(archive_path, inventory, max_bytes)
    metadata = {p for p in inventory if p.startswith("attempt-evidence/") and p.endswith(".json")}
    if not metadata <= members.keys():
        raise ValueError("journal_archive_metadata_missing")
    sources: dict[tuple[str, str], JournalSource] = {}
    expected = set(metadata)
    for name in sorted(metadata):
        if "/events/" not in name:
            continue
        event = json.loads(members[name])
        context, response = event["context"], event["response"]
        if (context.get("phase") not in {"product_detail", "classification_detail"}
                or response.get("outcome") != "success" or not 200 <= response["status"] < 300):
            continue
        provider, product_id = context.get("provider"), context.get("product_id")
        if not isinstance(provider, str) or not provider or not isinstance(product_id, str) or not product_id:
            raise ValueError("journal_product_identity_missing")
        relative = name.split("/events/", 1)[0] + "/" + event["body_path"]
        if relative not in members:
            raise ValueError("journal_detail_body_missing")
        body = members[relative]
        if (event["body_path"] != "bodies/" + response["body_sha256"] + ".body"
                or len(body) != response["body_bytes"]
                or hashlib.sha256(body).hexdigest() != response["body_sha256"]):
            raise ValueError("journal_event_body_mismatch")
        payload = json.loads(body)
        record = payload.get("data", payload) if isinstance(payload, dict) else None
        if not isinstance(record, dict) or record.get("productId", record.get("id")) != product_id:
            raise ValueError("journal_response_product_mismatch")
        key = (provider, product_id)
        source = JournalSource(provider, product_id, relative, name, response["body_sha256"],
                               response["completed_at"], body)
        if key in sources and sources[key].sha256 != source.sha256:
            raise ValueError("journal_product_response_conflict")
        sources.setdefault(key, source)
        expected.add(relative)
    if members.keys() != expected or not sources:
        raise ValueError("journal_archive_selection_mismatch")
    return tuple(sources[key] for key in sorted(sources))
