"""Turn one captured ingest into complete, evidence-bound product accounting."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from cdr_contracts import (
    DATASETS,
    canonical_json_bytes,
    normalize_provider_display_name,
    product_uid,
)
from cdr_ingest_support import iter_banking_brands_from_payload
from cdr_journal_evidence import journal_product_evidence, validate_journal_evidence
from cdr_product_accounting import (
    OPTIONAL_DETAIL_SECTIONS,
    build_product_accounting,
)
from cdr_raw_attempt_journal import RawAttemptJournal
from cdr_provider_identity_registry import (
    REGISTRY_FILENAME,
    ProviderIdentityRegistryError,
    validate_registry_snapshot_bytes,
)


class ProductInventoryError(ValueError):
    """The captured run cannot be reconciled without guessing."""


_SECTIONS = {
    "Mortgage": "mortgage",
    "Savings": "savings",
    "TD": "term_deposit",
}
_OMISSION_CODES = {"no_current_rate", "product_closed", "unsupported_category"}
_NORMALIZATION_CODES = {
    "classification_unresolved",
    "detail_array_invalid",
    "detail_invalid_json",
    "identity_mismatch",
    "rate_invalid",
    "field_omitted_invalid",
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProductInventoryError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise ProductInventoryError(f"{label} must be an object")
    return value


def load_ingest_status(run_root: Path) -> dict[str, Any]:
    return _json(run_root / "banks" / "ingest-status.json", "ingest status")


def _provider_registry(
    run_root: Path, status: Mapping[str, Any]
) -> dict[str, Any]:
    pointer = status.get("provider_identity_registry")
    journal = status.get("raw_attempt_journal")
    if not isinstance(pointer, Mapping) or not isinstance(journal, Mapping):
        raise ProductInventoryError("provider identity registry evidence is absent")
    raw_path = str(pointer.get("path") or "")
    relative = PurePosixPath(raw_path)
    journal_relative = PurePosixPath(str(journal.get("path") or ""))
    if (
        pointer.get("verified") is not True
        or pointer.get("path_resolution") != "relative_to_ingest_run_root"
        or pointer.get("retention") != "follows_ingest_run_root"
        or relative != journal_relative / REGISTRY_FILENAME
        or relative.is_absolute()
        or "\\" in raw_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ProductInventoryError("provider identity registry pointer is invalid")
    try:
        payload = run_root.joinpath(*relative.parts).read_bytes()
    except OSError as error:
        raise ProductInventoryError("provider identity registry evidence is unreadable") from error
    if (
        pointer.get("bytes") != len(payload)
        or pointer.get("sha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise ProductInventoryError("provider identity registry evidence digest disagrees")
    try:
        return validate_registry_snapshot_bytes(payload)
    except ProviderIdentityRegistryError as error:
        raise ProductInventoryError("provider identity registry evidence is invalid") from error


def _verified_journal(
    run_root: Path, status: Mapping[str, Any]
) -> tuple[RawAttemptJournal, dict[str, Any]]:
    pointer = status.get("raw_attempt_journal")
    if not isinstance(pointer, Mapping) or pointer.get("verified") is not True:
        raise ProductInventoryError("raw attempt journal is not verified")
    raw_path = str(pointer.get("path") or "")
    relative = PurePosixPath(raw_path)
    if (
        not raw_path
        or "\\" in raw_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ProductInventoryError("raw attempt journal path is unsafe")
    session_id = str(pointer.get("session_id") or "")
    if relative.parts != ("_raw-attempt-journals-v1", session_id):
        raise ProductInventoryError("raw attempt journal path disagrees with its session")
    try:
        journal = RawAttemptJournal(
            run_root.joinpath(*relative.parts[:-1]), session_id
        )
        summary = journal.summary(recover=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise ProductInventoryError("raw attempt journal verification failed") from error
    for field in (
        "schema_version",
        "session_id",
        "attempts",
        "head_digest",
        "observed_at",
        "verified",
    ):
        if pointer.get(field) != summary.get(field):
            raise ProductInventoryError(
                f"raw attempt journal disagrees with ingest status: {field}"
            )
    return journal, summary


def observed_at_from_journal(run_root: Path, status: Mapping[str, Any]) -> str:
    _, summary = _verified_journal(run_root, status)
    value = summary.get("observed_at")
    if not isinstance(value, str):
        raise ProductInventoryError("journal lacks a stable observation timestamp")
    return value


def _fallback_register_identity(
    row: Mapping[str, Any], registry: Mapping[str, Any]
) -> tuple[str, str, bool]:
    signature = (
        str(row.get("identity_authority") or ""),
        normalize_provider_display_name(
            str(row.get("brand_name") or row.get("legal_entity_name") or "")
        ),
    )
    by_signature: dict[tuple[str, str], str] = {}
    by_anchor: dict[tuple[str, str], set[str]] = defaultdict(set)
    for binding in registry.get("bindings") or []:
        uid = str(binding["provider_uid"])
        by_signature[(str(binding["authority"]), str(binding["display_name"]))] = uid
        for alias in binding["authorized_aliases"]:
            by_signature[(str(alias["authority"]), str(alias["display_name"]))] = uid
        for anchor in binding["anchors"]:
            by_anchor[(str(anchor["kind"]), str(anchor["value"]))].add(uid)
    strong = ("data_holder_brand_id", "interim_id")
    anchor_fields = (
        strong
        if any(str(row.get(key) or "").strip() for key in strong)
        else ("data_holder_id",)
    )
    anchor_uids = {
        uid
        for key in anchor_fields
        if str(row.get(key) or "").strip()
        for uid in by_anchor.get((key, str(row[key]).strip()), set())
    }
    mapped = by_signature.get(signature)
    if mapped is not None and not (anchor_uids - {mapped}):
        return mapped, "fallback", False
    if anchor_uids:
        return sorted(anchor_uids | ({mapped} if mapped else set()))[0], "fallback_conflict", True
    raise ProductInventoryError("fallback provider is not bound by the verified registry")


def _journal_register_providers(
    journal: RawAttemptJournal, registry: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    successful_register = False
    for record in journal.evidence_records(recover=False):
        context = record["context"]
        if (
            context.get("phase") != "register_discovery"
            or record["outcome"] != "success"
            or not 200 <= record["status"] < 300
        ):
            continue
        successful_register = True
        try:
            payload = json.loads((journal.root / str(record["body_path"])).read_bytes())
            rows = iter_banking_brands_from_payload(payload)
            for source in rows:
                row = dict(source)
                if row.get("provider_identity_status") != "official":
                    uid, status, held = _fallback_register_identity(row, registry)
                    row.update(
                        provider_uid=uid,
                        provider_identity_status=status,
                        provider_identity_held=held,
                    )
                key = (
                    str(row.get("endpoint_url") or "").lower(),
                    str(row.get("brand_name") or "").lower(),
                    str(row.get("legal_entity_name") or "").lower(),
                )
                merged[key] = row
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise ProductInventoryError("register journal evidence is invalid") from error
    if not successful_register:
        raise ProductInventoryError("register journal lacks a successful response")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in merged.values():
        grouped[str(row["provider_uid"])].append(row)
    expected: dict[str, dict[str, Any]] = {}
    for uid, rows in grouped.items():
        row = dict(rows[0])
        if len(rows) > 1:
            row.update(provider_identity_status="identity_collision", provider_identity_held=True)
        expected[uid] = row
    return expected


def _provider_maps(
    banks: Mapping[str, Any],
    status: Mapping[str, Any],
    journal_providers: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_dir: dict[str, dict[str, Any]] = {}
    by_uid: dict[str, dict[str, Any]] = {}
    for raw in banks.get("provider_observations") or []:
        if not isinstance(raw, Mapping):
            raise ProductInventoryError("provider observation is invalid")
        provider_dir = str(raw.get("provider_dir") or "")
        uid = str(raw.get("provider_uid") or "")
        if not provider_dir or not uid or provider_dir in by_dir or uid in by_uid:
            raise ProductInventoryError("provider identities are missing or duplicated")
        record = dict(raw)
        expected = journal_providers.get(uid)
        identity_fields = (
            "legal_entity_name",
            "endpoint_url",
            "data_holder_id",
            "data_holder_brand_id",
            "interim_id",
            "identity_authority",
        )
        if (
            expected is None
            or record.get("brand_name")
            != (expected.get("brand_name") or expected.get("legal_entity_name") or provider_dir)
            or record.get("provider_identity_status")
            != expected.get("provider_identity_status")
            or (record.get("provider_identity_held") is True)
            != (expected.get("provider_identity_held") is True)
            or any(
                str(record.get(field) or "") != str(expected.get(field) or "")
                for field in identity_fields
            )
        ):
            raise ProductInventoryError("provider identity disagrees with register journal")
        by_dir[provider_dir] = record
        by_uid[uid] = record
    states = status.get("provider_states")
    if not isinstance(states, list):
        raise ProductInventoryError("ingest status lacks provider states")
    state_by_uid = {
        str(item.get("provider_uid") or ""): item
        for item in states
        if isinstance(item, Mapping)
    }
    state_uids = set(state_by_uid)
    registered = status.get("providers_registered")
    if (
        isinstance(registered, bool)
        or not isinstance(registered, int)
        or registered != len(by_uid)
        or len(state_by_uid) != len(states)
        or state_uids != set(by_uid)
    ):
        raise ProductInventoryError("registered provider population does not reconcile")
    if any(
        state_by_uid[uid].get("provider_dir") not in {None, provider["provider_dir"]}
        for uid, provider in by_uid.items()
    ):
        raise ProductInventoryError("provider directory disagrees with ingest status")
    return by_dir, by_uid


def _product_candidates(
    run_root: Path,
    providers: Mapping[str, Mapping[str, Any]],
    journal_evidence: Mapping[tuple[str, str], list[Mapping[str, str]]],
) -> dict[str, dict[str, Any]]:
    banks_root = run_root / "banks"
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for dataset in DATASETS:
        root = banks_root / dataset
        if not root.is_dir():
            continue
        for id_path in sorted(root.rglob("product-id.txt")):
            relative = id_path.relative_to(banks_root)
            if len(relative.parts) < 5:
                raise ProductInventoryError("product evidence path is malformed")
            provider_dir = relative.parts[1]
            provider = providers.get(provider_dir)
            if provider is None:
                raise ProductInventoryError("product references an unknown provider")
            try:
                raw_id = id_path.read_bytes()
                cdr_id = raw_id.decode("utf-8").strip()
            except (OSError, UnicodeError) as error:
                raise ProductInventoryError("product ID evidence is unreadable") from error
            if not cdr_id or len(cdr_id) > 512 or any(ord(char) < 32 for char in cdr_id):
                raise ProductInventoryError("product ID evidence is invalid")
            uid = product_uid(str(provider["provider_uid"]), dataset, cdr_id)
            detail = id_path.parent / "product-detail.json"
            evidence = journal_evidence.get((provider_dir, cdr_id), [])
            if not evidence:
                raise ProductInventoryError("product lacks current journal-bound evidence")
            evidence_ids = {
                str(record["body_sha256"])
                for record in evidence
                if record["phase"] == "products_index"
            }
            if detail.is_file():
                try:
                    detail_digest = _sha(
                        canonical_json_bytes(json.loads(detail.read_bytes()))
                    )
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                    raise ProductInventoryError("product detail is unreadable") from error
                matching_details = {
                    str(record["body_sha256"])
                    for record in evidence
                    if record["phase"] in {"product_detail", "classification_detail"}
                    and record["canonical_digest"] == detail_digest
                }
                if not matching_details:
                    raise ProductInventoryError(
                        "product detail disagrees with current journal evidence"
                    )
                evidence_ids.update(matching_details)
            if not evidence_ids:
                raise ProductInventoryError("product lacks current journal-bound evidence")
            grouped[uid].append(
                {
                    "product_uid": uid,
                    "provider_uid": provider["provider_uid"],
                    "provider_dir": provider_dir,
                    "dataset": dataset,
                    "cdr_product_id": cdr_id,
                    "display_name": relative.parts[-3],
                    "detail_present": detail.is_file(),
                    "evidence_ids": sorted(evidence_ids),
                }
            )
    output: dict[str, dict[str, Any]] = {}
    natural_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    for uid, records in grouped.items():
        first = dict(records[0])
        first["evidence_ids"] = sorted(
            {value for record in records for value in record["evidence_ids"]}
        )
        first["duplicate"] = len(records) != 1
        output[uid] = first
        natural_ids[(first["provider_uid"], first["cdr_product_id"])].add(uid)
    for uids in natural_ids.values():
        if len(uids) > 1:
            for uid in uids:
                output[uid]["duplicate"] = True
    return output


def _failure_records(path: Path) -> tuple[list[tuple[dict[str, Any], str]], list[str]]:
    records: list[tuple[dict[str, Any], str]] = []
    corrupt: list[str] = []
    try:
        lines = path.read_bytes().splitlines()
    except OSError as error:
        raise ProductInventoryError("failure journal is unreadable") from error
    for line in lines:
        if not line.strip():
            continue
        digest = _sha(line)
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            corrupt.append(digest)
            continue
        if not isinstance(value, dict):
            corrupt.append(digest)
            continue
        records.append((value, digest))
    return records, corrupt


def _seed(
    *,
    scope: str,
    code: str,
    observed_at: str,
    evidence_digest: str,
    sections: list[str],
    phase: str,
    provider_uid: str | None = None,
    product_uid_value: str | None = None,
    http_status: int | None = None,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "provider_uid": provider_uid,
        "product_uid": product_uid_value,
        "affected_sections": sorted(set(sections)),
        "phase": phase,
        "code": code,
        "http_status": http_status,
        "occurrence_count": 1,
        "first_seen_at": observed_at,
        "last_seen_at": observed_at,
        "evidence_digest": evidence_digest,
        "public_safe": True,
    }


def _status_code(value: Any) -> tuple[str, int | None]:
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return "cdr_error", value
    text = str(value or "").strip()
    if text in _NORMALIZATION_CODES:
        return text, None
    return "detail_fetch_failed", None


def _is_closed(row: Mapping[str, Any], observation_date: str) -> bool:
    value = str(row.get("effective_to") or "").strip()
    if not value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date() <= date.fromisoformat(
            observation_date
        )
    except ValueError:
        return False


def build_product_inventory(
    run_root: Path,
    banks: Mapping[str, Any],
    *,
    status: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
) -> tuple[dict[str, Any], str, list[str]]:
    """Return ProductAccountingV1, stable observed-at, and global blockers."""

    run_root = run_root.expanduser().resolve()
    observation_date = run_root.name
    date.fromisoformat(observation_date)
    status_copy = dict(status or load_ingest_status(run_root))
    journal, journal_summary = _verified_journal(run_root, status_copy)
    observed_at = observed_at or journal_summary.get("observed_at")
    if not isinstance(observed_at, str):
        raise ProductInventoryError("journal lacks a stable observation timestamp")
    registry = (
        _provider_registry(run_root, status_copy)
        if status_copy.get("provider_identity_registry") is not None
        else {"schema_version": 1, "bindings": []}
    )
    journal_providers = _journal_register_providers(journal, registry)
    providers_by_dir, providers_by_uid = _provider_maps(
        banks, status_copy, journal_providers
    )
    fallback_providers = [
        provider
        for provider in providers_by_uid.values()
        if str(provider.get("provider_uid") or "").startswith("provider-fallback:")
    ]
    if status_copy.get("provider_identity_registry") is not None or fallback_providers:
        fallback_uids = {binding["provider_uid"] for binding in registry["bindings"]}
        if any(provider["provider_uid"] not in fallback_uids for provider in fallback_providers):
            raise ProductInventoryError("fallback provider identity is absent from its registry")
    journal_evidence = journal_product_evidence(journal)
    candidates = _product_candidates(run_root, providers_by_dir, journal_evidence)
    normalized_by_uid: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in banks.get("products") or []:
        if not isinstance(row, Mapping) or str(row.get("product_uid") or "") not in candidates:
            raise ProductInventoryError("normalized product is not in captured population")
        normalized_by_uid[str(row["product_uid"])].append(row)
    rates_by_uid: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in banks.get("rates") or []:
        if not isinstance(row, Mapping) or str(row.get("product_uid") or "") not in candidates:
            raise ProductInventoryError("normalized rate is not in captured population")
        rates_by_uid[str(row["product_uid"])].append(row)

    issue_seeds: list[dict[str, Any]] = []
    blockers: list[str] = []
    failures, corrupt = _failure_records(run_root / "banks" / "failures.jsonl")
    for digest in corrupt:
        issue_seeds.append(
            _seed(
                scope="run", code="failure_record_corrupt", observed_at=observed_at,
                evidence_digest=digest, sections=["products", "rates"], phase="reconciliation",
            )
        )
        blockers.append("failure_record_corrupt")

    candidate_lookup: dict[tuple[str, str], list[str]] = defaultdict(list)
    for uid, item in candidates.items():
        candidate_lookup[(item["provider_dir"], item["cdr_product_id"])].append(uid)
    provider_issue_codes: dict[str, set[str]] = defaultdict(set)
    for record, digest in failures:
        provider_dir = str(record.get("bank") or "").strip()
        provider = providers_by_dir.get(provider_dir)
        if provider is None:
            issue_seeds.append(
                _seed(
                    scope="run", code="failure_unattributed", observed_at=observed_at,
                    evidence_digest=digest, sections=["products", "rates"], phase="reconciliation",
                )
            )
            blockers.append("failure_unattributed")
            continue
        uid = str(provider["provider_uid"])
        phase = str(record.get("phase") or "")
        product_id_value = str(record.get("product_id") or "").strip()
        product_uids = candidate_lookup.get((provider_dir, product_id_value), [])
        if product_uids:
            code, http = _status_code(record.get("status"))
            for product in product_uids:
                issue_seeds.append(
                    _seed(
                        scope="product", code=code, observed_at=observed_at,
                        evidence_digest=digest, sections=["details", "products", "rates"],
                        phase="product_detail" if phase != "normalization" else "normalization",
                        provider_uid=uid, product_uid_value=product, http_status=http,
                    )
                )
        elif phase == "holder":
            provider_issue_codes[uid].add("holder_worker_crash")
        elif phase == "products_index":
            provider_issue_codes[uid].add("products_index_failed")
        else:
            provider_issue_codes[uid].add("provider_population_unknown")

    for record in banks.get("quarantines") or []:
        if not isinstance(record, Mapping):
            continue
        provider_dir = str(record.get("bank") or "")
        provider = providers_by_dir.get(provider_dir)
        product_ids = candidate_lookup.get((provider_dir, str(record.get("product_id") or "")), [])
        if provider is None or not product_ids:
            blockers.append("normalization_failure_unattributed")
            continue
        code = str(record.get("status") or "")
        code = code if code in _NORMALIZATION_CODES else "detail_invalid_json"
        sections = record.get("affected_sections")
        if (
            not isinstance(sections, list)
            or not sections
            or not all(isinstance(item, str) and item for item in sections)
        ):
            sections = ["details", "products", "rates"]
        digest = str(record.get("evidence_digest") or "")
        if len(digest) != 64:
            digest = _sha(canonical_json_bytes(record))
        for product in product_ids:
            issue_seeds.append(
                _seed(
                    scope="product", code=code, observed_at=observed_at,
                    evidence_digest=digest, sections=sections,
                    phase="normalization", provider_uid=str(provider["provider_uid"]),
                    product_uid_value=product,
                )
            )

    for provider_dir, provider in providers_by_dir.items():
        uid = str(provider["provider_uid"])
        population = provider.get("population")
        if not isinstance(population, Mapping):
            provider_issue_codes[uid].add("provider_population_unknown")
            continue
        errors = set(population.get("population_errors") or [])
        if errors:
            provider_issue_codes[uid].add("pagination_incomplete")
        for product_id_value in population.get("duplicate_conflicts") or []:
            for product in candidate_lookup.get((provider_dir, str(product_id_value)), []):
                issue_seeds.append(
                    _seed(
                        scope="product", code="duplicate_conflict", observed_at=observed_at,
                        evidence_digest=_sha(canonical_json_bytes(population)),
                        sections=["products", "rates"], phase="validation", provider_uid=uid,
                        product_uid_value=product,
                    )
                )

    for uid, candidate in candidates.items():
        rows = normalized_by_uid.get(uid, [])
        if candidate["duplicate"] or len(rows) > 1:
            issue_seeds.append(
                _seed(
                    scope="product", code="duplicate_conflict", observed_at=observed_at,
                    evidence_digest=candidate["evidence_ids"][0], sections=["products", "rates"],
                    phase="validation", provider_uid=candidate["provider_uid"], product_uid_value=uid,
                )
            )
        elif not rows:
            existing = {seed["code"] for seed in issue_seeds if seed["product_uid"] == uid}
            if not existing:
                issue_seeds.append(
                    _seed(
                        scope="product", code="detail_fetch_failed", observed_at=observed_at,
                        evidence_digest=candidate["evidence_ids"][0],
                        sections=["details", "products", "rates"], phase="product_detail",
                        provider_uid=candidate["provider_uid"], product_uid_value=uid,
                    )
                )
        elif not rates_by_uid.get(uid):
            code = "product_closed" if _is_closed(rows[0], observation_date) else "no_current_rate"
            issue_seeds.append(
                _seed(
                    scope="product", code=code, observed_at=observed_at,
                    evidence_digest=str(rows[0]["evidence_id"]), sections=["products", "rates"],
                    phase="normalization", provider_uid=candidate["provider_uid"],
                    product_uid_value=uid,
                )
            )

    state_by_uid = {
        str(item.get("provider_uid")): dict(item)
        for item in status_copy.get("provider_states") or []
        if isinstance(item, Mapping)
    }
    for uid, codes in provider_issue_codes.items():
        provider = providers_by_uid[uid]
        digest = _sha(canonical_json_bytes(provider.get("population") or {"provider_uid": uid}))
        state = state_by_uid[uid]
        for code in sorted(codes):
            issue_seeds.append(
                _seed(
                    scope="provider", code=code, observed_at=observed_at,
                    evidence_digest=digest, sections=["products", "rates"],
                    phase="holder" if code == "holder_worker_crash" else "products_index",
                    provider_uid=uid,
                )
            )
        if state.get("state") in {"complete", "empty"}:
            state["state"] = "partial"

    if status_copy.get("register_provenance_complete") is not True:
        issue_seeds.append(
            _seed(
                scope="register", code="register_failed", observed_at=observed_at,
                evidence_digest=_sha(canonical_json_bytes(status_copy.get("register_attempts") or [])),
                sections=["register", "products", "rates"], phase="register_discovery",
            )
        )
        blockers.append("register_failed")
    if status_copy.get("failure_provenance_complete") is not True:
        blockers.append("failure_provenance_incomplete")
    if status_copy.get("coverage_evidence_complete") is not True:
        blockers.append("coverage_evidence_incomplete")

    reasons_by_product: dict[str, set[str]] = defaultdict(set)
    omitted_sections_by_product: dict[str, set[str]] = defaultdict(set)
    for seed in issue_seeds:
        if seed["product_uid"] is not None:
            uid = str(seed["product_uid"])
            reasons_by_product[uid].add(str(seed["code"]))
            if seed["code"] == "field_omitted_invalid":
                omitted_sections_by_product[uid].update(seed["affected_sections"])
    products: list[dict[str, Any]] = []
    for uid, candidate in candidates.items():
        row = normalized_by_uid.get(uid, [None])[0]
        reasons = sorted(reasons_by_product[uid])
        if not reasons:
            disposition, core_valid, details_complete = "published_full", True, True
        elif set(reasons) <= _OMISSION_CODES:
            disposition, core_valid, details_complete = "omitted_valid", False, bool(row)
        elif (
            set(reasons) == {"field_omitted_invalid"}
            and omitted_sections_by_product[uid]
            and omitted_sections_by_product[uid] <= OPTIONAL_DETAIL_SECTIONS
            and row
            and rates_by_uid.get(uid)
        ):
            disposition, core_valid, details_complete = "published_core_only", True, False
        else:
            disposition, core_valid, details_complete = "quarantined_invalid", False, bool(row)
        products.append(
            {
                "product_uid": uid,
                "provider_uid": candidate["provider_uid"],
                "cdr_product_id": candidate["cdr_product_id"],
                "dataset": candidate["dataset"],
                "display_name": str((row or {}).get("product_name") or candidate["display_name"]),
                "legacy_product_key": (row or {}).get("legacy_product_key"),
                "disposition": disposition,
                "reason_codes": reasons,
                "evidence_ids": candidate["evidence_ids"],
                "core_valid": core_valid,
                "details_complete": details_complete,
            }
        )
    disposition_by_uid = {item["product_uid"]: item["disposition"] for item in products}
    issues = [
        {
            **seed,
            "disposition": disposition_by_uid[seed["product_uid"]]
            if seed["product_uid"] is not None
            else None,
        }
        for seed in issue_seeds
    ]

    datasets_by_provider: dict[str, set[str]] = defaultdict(set)
    for product in products:
        datasets_by_provider[str(product["provider_uid"])].add(str(product["dataset"]))
        if product["disposition"] in {"published_core_only", "quarantined_invalid"}:
            state = state_by_uid[str(product["provider_uid"])]
            if state.get("state") in {"complete", "empty"}:
                state["state"] = "partial"
    provider_inputs = []
    for uid, provider in providers_by_uid.items():
        state = state_by_uid[uid]
        provider_inputs.append(
            {
                "provider_uid": uid,
                "brand_name": state.get("brand_name") or provider.get("brand_name") or provider["provider_dir"],
                "datasets": sorted(datasets_by_provider[uid]),
                "state": state.get("state"),
                "attempted": state.get("state") != "not_attempted",
                "population_known": state.get("population_known"),
            }
        )
    status_copy["provider_states"] = list(state_by_uid.values())
    counts: dict[str, int] = defaultdict(int)
    for state in status_copy["provider_states"]:
        counts[str(state.get("state"))] += 1
    status_copy["provider_state_counts"] = dict(counts)
    accounting = build_product_accounting(
        observation_date, status_copy, provider_inputs, products, issues
    )
    validate_journal_evidence(accounting, status_copy.get("provider_states"), journal)
    return accounting, observed_at, sorted(set(blockers))
