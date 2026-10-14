"""Reviewed promotion of public programmes through the existing publisher.

This verifies evidence bindings; it does not authenticate an operator or launch
a deployment. The protected Pi controller remains the sole publication writer.
Captured candidates cannot activate themselves or override reviewed adapters.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cdr_atomic import canonical_json_bytes
from cdr_domain.public_pricing_resolver import resolve_public_rate
from cdr_domain.public_pricing_validation import validate_programme
from cdr_public_rates_candidate import candidate_digest, programme_ids, selected_programmes
from cdr_public_rates_warning import PENDING_REASON, validate_warning_candidate

POLICY_PATH = Path(__file__).parent / "contracts/public_rates/publication-policy-v1.json"
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_SHADOW_BYTES = 16 * 1024 * 1024
MAX_CASES = 20000
MAX_RECEIPT_PROGRAMMES = 4096
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
RATE_FIELDS = ("status", "payableRate", "minimumRate", "maximumRate")


class ProgrammeSelection(set):
    """Authorised IDs with independently verified suspension discovery bindings."""
    def __init__(self, identities=(), *, suspensions=None):
        super().__init__(identities)
        self.suspensions = suspensions or {}


def sha256(value: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def programme_structure_sha256(programme: dict) -> str:
    """Price changes can reuse approval; changed relationships cannot.

    Explicit condition values, units, roles, formulas and footnote semantics
    remain bound. Only observed prices, source positions and dating/evidence
    identities are omitted. The semantic programme ID binds adapter version.
    """
    value = json.loads(json.dumps(programme))
    for key in ("freshness", "sourceBindings", "evidenceIds", "effectiveFrom", "effectiveTo"):
        value.pop(key, None)
    for component in value["components"]:
        component.pop("value", None)
        component.get("source", {}).pop("rawValue", None)
        component.get("source", {}).pop("pointer", None)

    def remove_evidence(item):
        if isinstance(item, dict):
            item.pop("evidenceIds", None)
            for nested in item.values():
                remove_evidence(nested)
        elif isinstance(item, list):
            for nested in item:
                remove_evidence(nested)
    remove_evidence(value)
    # These sets have semantic identities; source reordering is not a change
    # to the programme. Phase and explicit alternative ordering is preserved.
    for field, identity in (("components", "componentId"), ("conditions", "conditionId"), ("fees", "feeId")):
        if field in value:
            value[field].sort(key=lambda item: canonical_json_bytes(item.get(identity) or item))
    if 'materialFootnotes' in value:
        value['materialFootnotes'].sort()
    return sha256(value)


def _hash(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _read(path: Path, ceiling: int) -> tuple[dict, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > ceiling:
        raise ValueError("public_pricing_approval_file_unavailable_or_oversized")
    body = path.read_bytes()
    if len(body) > ceiling:
        raise ValueError("public_pricing_approval_file_oversized")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("public_pricing_approval_object_required")
    return value, hashlib.sha256(body).hexdigest()


def reviewed_policy() -> tuple[dict, str]:
    value, identity = _read(POLICY_PATH, MAX_RECEIPT_BYTES)
    if value.get("schemaVersion") != 1 or not isinstance(value.get("reviewedProgrammes"), list):
        raise ValueError("invalid_reviewed_public_pricing_policy")
    seen = set()
    for item in value["reviewedProgrammes"]:
        if (not isinstance(item, dict) or not isinstance(item.get("programmeId"), str)
                or item["programmeId"] in seen or not _hash(item.get("shadowReportSha256"))
                or not _hash(item.get("programmeStructureSha256"))
                or not isinstance(item.get("consumerCommit"), str)
                or not COMMIT.fullmatch(item["consumerCommit"])):
            raise ValueError("invalid_reviewed_public_pricing_programme")
        seen.add(item["programmeId"])
    return value, identity


def validate_shadow_report(report: dict, programme_ids: set[str]) -> dict:
    """Reproduce public results and verify three natural daily evidence cycles.

    Natural trigger identity is an operator-reviewed controller attestation,
    bound by hash. A fixture/manual replay can never satisfy this gate. The
    independent expected figures must be supplied separately from this resolver.
    """
    if (report.get("schemaVersion") != 1 or report.get("publicOnly") is not True
            or report.get("discrepancies") != [] or not programme_ids):
        raise ValueError("public_shadow_report_incomplete_or_discrepant")
    cycles = report.get("cycles")
    if not isinstance(cycles, list) or len(cycles) != 3:
        raise ValueError("three_natural_daily_cycles_required")
    days, generations, previous_hashes, unchanged = [], set(), None, False
    total_cases = 0
    for cycle in cycles:
        if (not isinstance(cycle, dict) or cycle.get("origin") != "natural_daily"
                or not _hash(cycle.get("triggerEvidenceSha256"))
                or not _hash(cycle.get("candidateSha256"))
                or not isinstance(cycle.get("producerCommit"), str)
                or not COMMIT.fullmatch(cycle["producerCommit"])):
            raise ValueError("natural_daily_source_evidence_required")
        day = date.fromisoformat(cycle["runDate"])
        if days and day != days[-1] + timedelta(days=1):
            raise ValueError("shadow_days_must_be_consecutive")
        generation = cycle.get("generationId")
        if not isinstance(generation, str) or not generation or generation in generations:
            raise ValueError("distinct_daily_ingest_generations_required")
        days.append(day)
        generations.add(generation)
        cases = cycle.get("cases")
        if not isinstance(cases, list) or not cases or len(cases) > MAX_CASES:
            raise ValueError("shadow_cases_missing_or_oversized")
        seen, hashes = set(), set()
        for case in cases:
            programme = case["programme"]
            validate_programme(programme)
            identity = programme["programmeId"]
            if identity not in programme_ids:
                raise ValueError("shadow_programme_outside_reviewed_scope")
            seen.add(identity)
            if not _hash(case.get("independentEvidenceSha256")):
                raise ValueError("independent_public_reproduction_required")
            public_evidence = case.get("evidence")
            if not isinstance(public_evidence, list) or not public_evidence:
                raise ValueError("retained_public_evidence_required")
            available = set()
            for evidence in public_evidence:
                url = urlsplit(evidence.get("url", ""))
                if (url.scheme != "https" or not url.hostname or url.username or url.password
                        or not _hash(evidence.get("sha256")) or not isinstance(evidence.get("locator"), str)):
                    raise ValueError("invalid_public_shadow_evidence")
                available.add(evidence["evidenceId"])
                hashes.add(evidence["sha256"])
            needed = set(programme["evidenceIds"])
            needed.update(eid for component in programme["components"] for eid in component["evidenceIds"])
            if not needed or not needed <= available:
                raise ValueError("shadow_evidence_binding_incomplete")
            instant = datetime.fromisoformat(case["asOf"].replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError("shadow_scenario_clock_requires_timezone")
            if instant.astimezone(ZoneInfo("Australia/Hobart")).date() != day:
                raise ValueError("shadow_scenario_clock_must_match_natural_day")
            scenario = case["scenario"]
            if (scenario.get("allowHistorical") or scenario.get("localRate")
                    or case.get("origin", "public") != "public"):
                raise ValueError("local_or_historical_scenario_cannot_verify_current_public_pricing")
            resolution = resolve_public_rate(programme, scenario, case["asOf"])
            expected = case.get("expected")
            if (not isinstance(expected, dict) or expected.get("status") not in {"exact", "from", "range"}
                    or any(resolution.get(key) != expected.get(key) for key in RATE_FIELDS)
                    or resolution["freshness"]["state"] != "current"
                    or resolution["origin"] not in {"published", "publicly_calculated"}):
                raise ValueError("public_shadow_reproduction_discrepancy")
        if seen != programme_ids:
            raise ValueError("every_reviewed_programme_requires_each_daily_cycle")
        unchanged = unchanged or hashes == previous_hashes
        previous_hashes = hashes
        total_cases += len(cases)
    if not unchanged:
        raise ValueError("unchanged_source_cycle_required")
    return {"schemaVersion": 1, "status": "validated", "cycles": 3, "cases": total_cases,
            "programmeIds": sorted(programme_ids), "lastRunDate": days[-1].isoformat(),
            "lastGenerationId": cycles[-1]["generationId"], "lastCandidateSha256": cycles[-1]["candidateSha256"],
            "unchangedSourceCycle": True, "activation": "not_performed"}


def _programme_id_set(value, *, empty=False) -> set[str]:
    if (not isinstance(value, list) or len(value) > MAX_RECEIPT_PROGRAMMES
            or not all(isinstance(item, str) and 0 < len(item) <= 256 for item in value)
            or len(value) != len(set(value)) or not empty and not value):
        raise ValueError('reviewed_public_programme_selection_required')
    return set(value)


def _shadow_scope(report) -> set[str]:
    cycles = report.get('cycles')
    if not isinstance(cycles, list) or len(cycles) != 3:
        raise ValueError('three_natural_daily_cycles_required')
    identities = set()
    for cycle in cycles:
        cases = cycle.get('cases') if isinstance(cycle, dict) else None
        if not isinstance(cases, list) or not cases or len(cases) > MAX_CASES:
            raise ValueError('shadow_cases_missing_or_oversized')
        for case in cases:
            identity = case.get('programme', {}).get('programmeId') if isinstance(case, dict) else None
            if not isinstance(identity, str) or not identity or len(identity) > 256:
                raise ValueError('invalid_public_shadow_programme')
            identities.add(identity)
    if len(identities) > MAX_RECEIPT_PROGRAMMES:
        raise ValueError('public_shadow_scope_oversized')
    return identities


def reviewed_suspensions(candidate: dict, scope: set[str], *, policy: dict | None = None) -> dict[str, list[str]]:
    """Suspension changes publication eligibility, never observed prices."""
    policy = policy if policy is not None else reviewed_policy()[0]
    allowed = {entry['programmeId']: entry for entry in policy['reviewedProgrammes']}
    if not scope <= set(allowed):
        raise ValueError('public_programme_not_in_reviewed_allowlist')
    if 'warningSnapshot' in candidate:
        validate_warning_candidate(candidate)
        return {identity: [PENDING_REASON] for identity in sorted(scope)}
    available = programme_ids(candidate)
    current = {item['programmeId']: item for item in selected_programmes(candidate, scope & available)}
    result = {}
    for identity in sorted(scope):
        if identity not in available:
            result[identity] = ['public_pricing_reviewed_programme_unavailable']
        elif programme_structure_sha256(current[identity]) != allowed[identity]['programmeStructureSha256']:
            result[identity] = ['public_pricing_structure_changed_requires_review']
    return result


def authorised_programmes(candidate: dict, receipt_path: Path | None = None) -> set[str]:
    if candidate.get("enabledProgrammeIds") != []:
        raise ValueError("captured_public_candidate_cannot_activate_programmes")
    validate_warning_candidate(candidate)
    if receipt_path is None:
        return ProgrammeSelection()
    receipt_path = Path(receipt_path)
    receipt, _ = _read(receipt_path, MAX_RECEIPT_BYTES)
    policy, policy_sha = reviewed_policy()
    if (receipt.get("schemaVersion") != 1 or receipt.get("candidateSha256") != candidate_digest(candidate)
            or receipt.get("generationId") != candidate.get("generationId")
            or receipt.get("runDate") != candidate.get("runDate")
            or receipt.get("policySha256") != policy_sha):
        raise ValueError("public_pricing_approval_generation_or_policy_mismatch")
    warning = candidate.get('warningSnapshot')
    if (warning is not None and receipt.get('warningSnapshotSha256') != sha256(warning)
            or warning is None and 'warningSnapshotSha256' in receipt):
        raise ValueError('public_warning_receipt_must_bind_source_state')
    requested = _programme_id_set(receipt.get('programmeIds'), empty=True)
    suspended = _programme_id_set(receipt.get('suspendedProgrammeIds', []), empty=True)
    suspension_codes = receipt.get('suspensionReasonCodes', {})
    scope = requested | suspended
    mode = receipt.get('publicationMode', 'initial')
    if (not scope or requested & suspended or not isinstance(suspension_codes, dict)
            or set(suspension_codes) != suspended or suspended and mode != 'validated_update'):
        raise ValueError('invalid_public_programme_suspension_selection')
    allowed = {entry["programmeId"]: entry for entry in policy["reviewedProgrammes"]}
    available = programme_ids(candidate)
    if not scope <= set(allowed) or not requested <= available:
        raise ValueError("public_programme_not_in_reviewed_allowlist")
    descriptor = receipt.get("shadowReport", {})
    relative = Path(descriptor.get("file", ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("invalid_public_shadow_report_path")
    target = receipt_path.parent / relative
    if target.is_symlink() or receipt_path.parent.resolve() not in target.resolve().parents:
        raise ValueError("invalid_public_shadow_report_path")
    report, report_sha = _read(target, MAX_SHADOW_BYTES)
    if descriptor.get("sha256") != report_sha:
        raise ValueError("public_shadow_report_hash_mismatch")
    release = receipt.get("consumerRelease", {})
    if (not isinstance(release.get("commit"), str) or not COMMIT.fullmatch(release["commit"])
            or any(not _hash(release.get(key)) for key in ("metadataSha256", "apkSha256", "nativeAcceptanceSha256"))
            or any(not _hash(receipt.get(key)) for key in ("operatorApprovalSha256", "canaryReceiptSha256"))):
        raise ValueError("operator_canary_and_consumer_acceptance_bindings_required")
    tested = _shadow_scope(report)
    if not scope <= tested or not tested <= set(allowed):
        raise ValueError('shadow_programme_outside_reviewed_scope')
    if any(allowed[identity]["shadowReportSha256"] != report_sha
           or allowed[identity]["consumerCommit"] != release["commit"] for identity in tested):
        raise ValueError("public_pricing_reviewed_acceptance_mismatch")
    result = validate_shadow_report(report, tested)
    if result["lastRunDate"] > candidate["runDate"]:
        raise ValueError("public_shadow_report_is_from_a_later_day")
    if mode not in {"initial", "validated_update"}:
        raise ValueError("invalid_public_pricing_publication_mode")
    if mode == "validated_update":
        anchor = receipt.get("approvedShadowCandidate")
        expected_anchor = {"generationId": result["lastGenerationId"], "runDate": result["lastRunDate"],
                           "candidateSha256": result["lastCandidateSha256"]}
        if anchor != expected_anchor:
            raise ValueError("public_price_update_requires_approved_shadow_candidate")
    elif result["lastRunDate"] == candidate["runDate"] and (
            result["lastGenerationId"] != candidate["generationId"] or result["lastCandidateSha256"] != candidate_digest(candidate)):
        raise ValueError("public_shadow_report_does_not_bind_selected_candidate")
    validated = {case["programme"]["programmeId"]: case["programme"] for case in report["cycles"][-1]["cases"]}
    for identity in tested:
        structure = allowed[identity]["programmeStructureSha256"]
        if programme_structure_sha256(validated[identity]) != structure:
            raise ValueError("public_pricing_structure_changed_requires_review")
    actual_suspensions = reviewed_suspensions(candidate, scope, policy=policy)
    if requested & set(actual_suspensions):
        raise ValueError('public_pricing_structure_changed_requires_review')
    if suspended != set(actual_suspensions) or suspension_codes != actual_suspensions:
        raise ValueError('public_pricing_suspension_must_match_current_candidate')
    bindings = {identity: {'programmeId': identity, 'productId': validated[identity]['productId'],
                           'section': validated[identity]['section'], 'reasonCodes': actual_suspensions[identity]}
                for identity in sorted(suspended)}
    return ProgrammeSelection(requested, suspensions=bindings)
