"""Off-by-default public pricing in the existing guarded publication lane.

This module creates neither schedules nor workers. Captures never authorise
pricing: an operator-configured, independently validated approval template is
the only source of executable programme selection. Pending work freezes the
immutable candidate so a retry cannot silently switch generations or prices.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from cdr_atomic import atomic_write_bytes, atomic_write_json, canonical_json_bytes
from cdr_file_lock import FileLock
from cdr_public_rates_candidate import Candidate, candidate_digest, read_candidate
from cdr_public_rates_publication import (
    MAX_RECEIPT_BYTES, MAX_SHADOW_BYTES, SHA, authorised_programmes, reviewed_suspensions,
)
from cdr_public_rates_warning import (
    PENDING_REASON, PublicPricingSourcePending, SupersededCandidate, read_source_state,
    validate_warning_candidate, write_warning,
)
from cdr_terms.identity import digest

FLAG = "AR_LOCAL_PUBLIC_RATES_PUBLISH"
TEMPLATE = "AR_LOCAL_PUBLIC_RATES_APPROVAL_TEMPLATE"
CANDIDATE_POINTER = "public_rate_candidate"


def enabled() -> bool:
    return os.environ.get(FLAG, "0") == "1"


def public_snapshot_fence(evidence_root: Path) -> FileLock:
    """Short CAS/promotion fence. Acquire before the source DB transaction.

    Capture acquisition and archive/data upload never hold this lock. The
    existing publication operation locks still own the outer transaction.
    """
    return FileLock(Path(evidence_root).resolve() / 'public-rate-snapshot.lock')


def _root() -> Path:
    configured = os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip()
    if not configured:
        raise ValueError("public_pricing_requires_existing_evidence_root")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("public_pricing_requires_existing_evidence_root")
    from app_payload_revisions import revision_mode_enabled
    if not revision_mode_enabled():
        raise ValueError("public_pricing_requires_immutable_revision_publisher")
    return root


def _relative_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name:
        raise ValueError("invalid_public_pricing_candidate_path")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid_public_pricing_candidate_path")
    path = root / relative
    if path.is_symlink() or root not in path.resolve().parents:
        raise ValueError("invalid_public_pricing_candidate_path")
    return path


def _bound(candidate: Candidate, root: Path, generation: str, day: str) -> Candidate:
    identity = candidate_digest(candidate)
    expected = root / "public-rate-candidates" / digest(generation) / (identity + ".json")
    if (not generation or not day or candidate.get("generationId") != generation
            or candidate.get("runDate") != day or candidate.path.resolve() != expected
            or candidate.get("enabledProgrammeIds") != []):
        raise ValueError("public_pricing_candidate_must_bind_selected_immutable_generation")
    return candidate


def _selected(root: Path, pointer: dict) -> Candidate:
    descriptor = pointer.get(CANDIDATE_POINTER)
    if descriptor is None:
        candidate = read_candidate(root / "public-rate-catalogue-candidate.json")
    else:
        if (not isinstance(descriptor, dict) or set(descriptor) != {"file", "sha256"}
                or not isinstance(descriptor.get("sha256"), str) or not SHA.fullmatch(descriptor["sha256"])):
            raise ValueError("invalid_public_pricing_candidate_descriptor")
        candidate = read_candidate(_relative_file(root, descriptor["file"]))
        if candidate_digest(candidate) != descriptor["sha256"]:
            raise ValueError("public_pricing_candidate_hash_mismatch")
    candidate = _bound(candidate, root, pointer.get("generation_id", ""), pointer.get("observation_date", ""))
    _not_superseded(root, candidate)
    return candidate


def _not_superseded(root: Path, candidate: Candidate) -> None:
    if 'warningSnapshot' in candidate:
        validate_warning_candidate(candidate)
        return
    latest = read_candidate(root / "public-rate-catalogue-candidate.json")
    if latest.get('generationId') != candidate['generationId']:
        return
    _bound(latest, root, candidate['generationId'], candidate['runDate'])
    if candidate_digest(latest) != candidate_digest(candidate):
        raise SupersededCandidate('public_pricing_candidate_superseded')


def pending_public_source(root: Path, generation: str) -> bool:
    """Bounded read-only check; never migrate or acknowledge source evidence."""
    return read_source_state(root, generation) is not None


def _descriptor(root: Path, candidate: Candidate) -> dict:
    return {"file": candidate.path.resolve().relative_to(root).as_posix(), "sha256": candidate_digest(candidate)}


def _publication_candidate(root: Path, pointer: dict) -> Candidate:
    if CANDIDATE_POINTER in pointer:
        candidate = _selected(root, pointer)
        if 'warningSnapshot' not in candidate and pending_public_source(root, candidate['generationId']):
            raise SupersededCandidate('public_pricing_source_warning_supersedes_candidate')
        return candidate
    source = read_candidate(root / 'public-rate-catalogue-candidate.json')
    _bound(source, root, source['generationId'], source['runDate'])
    historical = source['generationId'] != pointer.get('generation_id')
    state = read_source_state(root, pointer.get('generation_id', ''), include_clean=historical)
    if state is not None:
        return write_warning(root, source, state, generation=pointer.get('generation_id'), run_date=pointer.get('observation_date'))
    return _bound(source, root, pointer.get('generation_id', ''), pointer.get('observation_date', ''))


def _source_pointer(repository: Path) -> dict:
    from ar_local_pi_runtime import data_state_root
    from pi_daily_sync import _read_observation_pointer
    state = data_state_root(repository)
    latest = _read_observation_pointer(state, 'latest-observation.json')
    return latest if latest.get('observation_state') == 'partial' else _read_observation_pointer(state, 'latest-complete.json')


def selected_public_generation(evidence_root: Path) -> str | None:
    """Read-only publication authority for CAS; disabled fixtures have none."""
    if not enabled() or Path(evidence_root).resolve() != _root():
        return None
    pointer = _source_pointer(Path(__file__).resolve().parent)
    generation = pointer.get('generation_id')
    return generation if pointer.get('observation_state') in {'complete', 'partial'} and isinstance(generation, str) and generation else None


def enrich_publication_pointer(repo_root: Path, pointer: dict) -> dict:
    """Resolve the mutable discovery pointer once, then freeze its byte hash."""
    if not enabled() or not pointer:
        return pointer
    root = _root()
    candidate = _publication_candidate(root, pointer)
    return {**pointer, CANDIDATE_POINTER: _descriptor(root, candidate)}


def _document(path: Path, maximum: int) -> tuple[dict, bytes]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("public_pricing_approval_document_missing_or_oversized")
    raw = path.read_bytes()
    if len(raw) > maximum:
        raise ValueError("public_pricing_approval_document_oversized")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("public_pricing_approval_document_object_required")
    return value, raw


def _template_candidate(root: Path, template: dict) -> Candidate:
    generation, day, identity = (template.get(key) for key in ("generationId", "runDate", "candidateSha256"))
    if (not isinstance(generation, str) or not isinstance(day, str)
            or not isinstance(identity, str) or not SHA.fullmatch(identity)):
        raise ValueError("invalid_initial_public_pricing_template")
    path = root / "public-rate-candidates" / digest(generation) / (identity + ".json")
    return _bound(read_candidate(path), root, generation, day)


def _shadow(template: dict, path: Path) -> tuple[dict, bytes]:
    descriptor = template.get("shadowReport")
    if not isinstance(descriptor, dict):
        raise ValueError("invalid_public_pricing_template_shadow_report")
    report_path = _relative_file(path.parent.resolve(), descriptor.get("file"))
    report, raw = _document(report_path, MAX_SHADOW_BYTES)
    if hashlib.sha256(raw).hexdigest() != descriptor.get("sha256"):
        raise ValueError("public_pricing_template_shadow_hash_mismatch")
    return report, raw


def _approval(root: Path, candidate: Candidate, template_path: Path) -> Path:
    template, _ = _document(template_path, MAX_RECEIPT_BYTES)
    if template.get("publicationMode", "initial") != "initial":
        raise ValueError("public_pricing_runtime_requires_initial_approval_template")
    original = _template_candidate(root, template)
    original_selection = authorised_programmes(original, template_path)
    if template.get("consumerRelease", {}).get("commit") != os.environ.get("AR_APP_REVISION_CONSUMER_SHA"):
        raise ValueError("public_pricing_approval_must_bind_selected_shipped_consumer")
    report, shadow_raw = _shadow(template, template_path)
    final_cycle = report["cycles"][-1]
    anchor = {"generationId": final_cycle["generationId"], "runDate": final_cycle["runDate"],
              "candidateSha256": final_cycle["candidateSha256"]}
    if anchor != {key: template[key] for key in anchor}:
        raise ValueError("public_pricing_template_must_bind_final_natural_shadow_candidate")
    if candidate_digest(candidate) == candidate_digest(original):
        return template_path
    if template.get("allowsValidatedPriceUpdates") is not True:
        raise ValueError("public_pricing_price_updates_require_explicit_operator_template_permission")
    # Preserve independently checked shadow bytes and every approval binding.
    # Only the current candidate binding changes; the reviewed activation anchor
    # stays fixed and the publication gate rechecks the programme structure.
    folder = root / "public-rate-runtime" / digest(candidate["generationId"])
    shadow_name = "shadow-" + hashlib.sha256(shadow_raw).hexdigest() + ".json"
    atomic_write_bytes(folder / shadow_name, shadow_raw, create_once=True)
    receipt = {**template, "candidateSha256": candidate_digest(candidate), "generationId": candidate["generationId"],
               "runDate": candidate["runDate"], "publicationMode": "validated_update", "approvedShadowCandidate": anchor,
               "shadowReport": {**template["shadowReport"], "file": shadow_name}}
    suspensions = reviewed_suspensions(candidate, set(original_selection))
    receipt.update(programmeIds=sorted(set(original_selection) - set(suspensions)),
                   suspendedProgrammeIds=sorted(suspensions), suspensionReasonCodes=suspensions)
    if 'warningSnapshot' in candidate:
        receipt['warningSnapshotSha256'] = hashlib.sha256(canonical_json_bytes(candidate['warningSnapshot'])).hexdigest()
    path = folder / (hashlib.sha256(canonical_json_bytes(receipt)).hexdigest() + ".json")
    atomic_write_json(path, receipt, create_once=True)
    authorised_programmes(candidate, path)
    return path


def publication_kwargs(repo_root: Path, contract: dict, pointer: dict) -> dict:
    """Builder inputs used by both natural and admitted queued publication."""
    if not enabled():
        return {}
    root = _root()
    if (pointer.get("generation_id") != contract.get("generation_id")
            or pointer.get("observation_date") != contract.get("observation_date")):
        raise ValueError("public_pricing_publication_contract_generation_mismatch")
    candidate = _publication_candidate(root, pointer)
    template = os.environ.get(TEMPLATE, "").strip()
    receipt = _approval(root, candidate, Path(template).expanduser().absolute()) if template else None
    frozen = {**pointer, CANDIDATE_POINTER: _descriptor(root, candidate)}

    def assert_current() -> None:
        selected = _source_pointer(repo_root)
        if (selected.get('generation_id') != candidate['generationId']
                or selected.get('observation_date') != candidate['runDate']):
            raise SupersededCandidate('public_pricing_selected_generation_superseded')
        _selected(root, frozen)
        if 'warningSnapshot' not in candidate and pending_public_source(root, candidate['generationId']):
            raise SupersededCandidate('public_pricing_source_warning_supersedes_candidate')

    return {"public_rates_root": candidate.path.resolve(), "public_rates_receipt": receipt,
            "pre_promotion_guard": assert_current, "pre_promotion_fence": lambda: public_snapshot_fence(root)}


def _warning_ack(root: Path, candidate: Candidate) -> Path:
    return root / 'public-rate-runtime' / 'warnings-published' / (candidate_digest(candidate) + '.json')


def _warning_published(root: Path, candidate: Candidate) -> bool:
    ack = _warning_ack(root, candidate)
    if not ack.exists():
        return False
    value, _ = _document(ack, 2048)
    if (value.get('schemaVersion') != 1 or value.get('candidateSha256') != candidate_digest(candidate)
            or value.get('generationId') != candidate['generationId']
            or value.get('sourceStateSha256') != candidate['warningSnapshot']['sourceStateSha256']
            or not isinstance(value.get('bundleSha256'), str) or not SHA.fullmatch(value['bundleSha256'])):
        raise ValueError('public_warning_publication_state_unreadable')
    return True


def acknowledge_warning_publication(candidate_path: Path, manifest: dict) -> None:
    """Called only after the existing publisher confirms its selected revision."""
    if not enabled():
        return
    candidate = read_candidate(candidate_path)
    if 'warningSnapshot' not in candidate:
        return
    root = _root()
    _bound(candidate, root, candidate['generationId'], candidate['runDate'])
    validate_warning_candidate(candidate, check_current=False)
    bundle = manifest.get('payload_revision', {}).get('bundle_sha256')
    capability = manifest.get('public_rate_catalogue', {})
    if (not isinstance(bundle, str) or not SHA.fullmatch(bundle)
            or capability.get('generationId') != candidate['generationId'] or manifest.get('run_date') != candidate['runDate']):
        raise ValueError('public_warning_publication_revision_binding_required')
    if _warning_published(root, candidate):
        return
    atomic_write_json(_warning_ack(root, candidate), {'schemaVersion': 1, 'candidateSha256': candidate_digest(candidate),
        'generationId': candidate['generationId'], 'sourceStateSha256': candidate['warningSnapshot']['sourceStateSha256'],
        'bundleSha256': bundle}, create_once=True)


def queue_source_warning(evidence_root: Path, *, repo_root: Path | None = None, dry_run: bool = False) -> dict:
    """Recover committed dirty status through the existing publication lane.

    This callback is outside the accepted-check DB transaction/fence. It never
    consumes a collector lease or acknowledges the pending deterministic work.
    The existing watchdog also calls it to recover a crash before this callback.
    """
    if not enabled():
        return {'status': 'disabled'}
    root = _root()
    if Path(evidence_root).resolve() != root:
        raise ValueError('public_pricing_update_evidence_root_mismatch')
    repository = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent
    pointer = _source_pointer(repository)
    if pointer.get('observation_state') not in {'complete', 'partial'}:
        return {'status': 'deferred', 'reasonCode': 'public_pricing_selected_finalization_pending'}
    source = read_candidate(root / 'public-rate-catalogue-candidate.json')
    historical = source['generationId'] != pointer.get('generation_id')
    state = read_source_state(root, pointer.get('generation_id', ''), include_clean=historical)
    if state is None:
        return {'status': 'not_due'}
    if dry_run:
        return {'status': 'dry_run', 'generationId': state['generationId'], 'reasonCode': PENDING_REASON}
    candidate = write_warning(root, source, state, generation=pointer['generation_id'], run_date=pointer['observation_date'])
    frozen = {**pointer, CANDIDATE_POINTER: _descriptor(root, candidate)}
    from pi_daily_sync import mark_payload_publication_pending
    with public_snapshot_fence(root):
        validate_warning_candidate(candidate)
        if _warning_published(root, candidate):
            return {'status': 'already_published', 'candidateSha256': candidate_digest(candidate)}
        mark_payload_publication_pending(repository, PENDING_REASON, frozen)
    from pi_payload_retry_policy import publication_source_key
    return {'status': 'queued', 'candidateSha256': candidate_digest(candidate),
            'sourceKey': publication_source_key({'pointer': frozen}), 'generationId': candidate['generationId']}


def queue_candidate_update(evidence_root: Path, candidate_result: dict, *, repo_root: Path | None = None) -> dict:
    """Accepted reference checks request existing guarded payload-only retries."""
    if not enabled():
        return {"status": "disabled"}
    root = _root()
    if Path(evidence_root).resolve() != root:
        raise ValueError("public_pricing_update_evidence_root_mismatch")
    if not candidate_result.get("file") or candidate_result.get("status") in {"deferred", "incomplete"}:
        return {"status": "deferred", "reasonCode": "public_pricing_snapshot_incomplete"}
    candidate = read_candidate(Path(candidate_result["file"]))
    if candidate_digest(candidate) != candidate_result.get("sha256"):
        raise ValueError("public_pricing_candidate_hash_mismatch")
    from pi_daily_sync import mark_payload_publication_pending
    repository = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent
    pointer = _source_pointer(repository)
    if (candidate.get("generationId") != pointer.get("generation_id")
            or candidate.get("runDate") != pointer.get("observation_date")
            or pointer.get("observation_state") not in {"complete", "partial"}):
        return {"status": "deferred", "reasonCode": "public_pricing_selected_finalization_pending"}
    _bound(candidate, root, pointer["generation_id"], pointer["observation_date"])
    try:
        _not_superseded(root, candidate)
    except SupersededCandidate:
        return {'status': 'superseded', 'reasonCode': 'public_pricing_candidate_superseded'}
    frozen = {**pointer, CANDIDATE_POINTER: _descriptor(root, candidate)}
    mark_payload_publication_pending(repository, "public_pricing_source_changed", frozen)
    from pi_payload_retry_policy import publication_source_key
    return {"status": "queued", "sourceKey": publication_source_key({"pointer": frozen}),
            "candidateSha256": candidate_digest(candidate), "generationId": candidate["generationId"]}
