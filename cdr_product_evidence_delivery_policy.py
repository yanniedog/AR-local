"""Held, default-off optional delivery policy; no financial or runtime mutations."""
from dataclasses import dataclass
import os
import re

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require, SHA
from app_payload_product_evidence_reference import LANES, SOURCE_FIELDS, _source, validate_reference
from app_payload_revisions_state import bundle_sha256

FLAGS = {
    'product_evidence_v1': 'AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY',
    'product_response_evidence_v1': 'AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY',
}
STATUS = 'optional_product_evidence_status'
REASONS = {
    'disabled': {'disabled_by_configuration'},
    'pending': {'not_prepared'},
    'unavailable': {'source_unavailable', 'source_failed', 'source_superseded', 'source_unverified'},
    'unsupported': {'unsupported_source_schema'},
    'failed': {'preparation_failed', 'budget_exceeded'},
    'available': {'verified'},
}
SELECTION_FIELDS = ('pointer_sha256', 'completion_sha256', 'contract_file_sha256', 'ledger_event_digest')
MAX_DOCUMENT = 65536


class MalformedReady(ValueError):
    """Claimed-ready corruption cannot become a silent optional omission."""


def delivery_flags(environment=None):
    environment = os.environ if environment is None else environment
    enabled = []
    for lane, flag in FLAGS.items():
        value = environment.get(flag, '0')
        require(type(value) is str and value in ('0', '1'), f'{flag} requires 0 or 1')
        if value == '1': enabled.append(lane)
    return tuple(sorted(enabled))


def validate_enabled(enabled):
    require(type(enabled) in (list, tuple) and list(enabled) == sorted(set(enabled))
            and all(lane in LANES for lane in enabled), 'invalid enabled evidence lanes')


def pending_outcomes(enabled):
    validate_enabled(enabled)
    return {lane: dict(state='pending', reason='not_prepared') if lane in enabled else
            dict(state='disabled', reason='disabled_by_configuration') for lane in LANES}


def source_reference(manifest):
    require(type(manifest) is dict, 'manifest source must be an object')
    value = manifest.get('source_observation')
    require(type(value) is dict and all(key in value for key in SOURCE_FIELDS), 'missing manifest source')
    source = {key: value[key] for key in SOURCE_FIELDS}; _source(source)
    require(source['observation_date'] == manifest.get('run_date'), 'manifest source date differs')
    return source


def validate_outcomes(manifest, enabled, outcomes):
    validate_enabled(enabled); fields(outcomes, LANES)
    for lane, outcome in outcomes.items():
        ready = type(outcome) is dict and outcome.get('state') == 'available'
        try:
            fields(outcome, ('state', 'reason', 'reference', 'prepared_sha256') if ready else ('state', 'reason'))
            state, reason = outcome['state'], outcome['reason']
            require(type(state) is str and state in REASONS and type(reason) is str and reason in REASONS[state],
                    'invalid evidence delivery state or reason')
            require((state != 'disabled') == (lane in enabled), 'disabled/enabled delivery status differs')
            if ready:
                require(type(outcome['prepared_sha256']) is str and SHA.fullmatch(outcome['prepared_sha256']),
                        'invalid prepared marker digest')
                validate_reference(lane, outcome['reference'], manifest)
        except (ValueError, KeyError, TypeError) as error:
            if ready: raise MalformedReady('claimed-ready evidence is malformed') from error
            raise


def apply_status(manifest, enabled, outcomes=None):
    """Pure projection; disabled-by-default leaves legacy bytes/identity unchanged.

    Inputs claiming ready require a separately verified prepared package. This
    schema check alone is not source adoption or asset-integrity evidence.
    """
    validate_enabled(enabled)
    if not enabled:
        require(outcomes is None, 'disabled delivery cannot consume outcomes')
        return decode(canonical(manifest))
    require(not any(key in manifest for key in (*LANES, STATUS)), 'base already contains evidence delivery')
    source = source_reference(manifest); validate_outcomes(manifest, enabled, outcomes)
    result = decode(canonical(manifest))
    result[STATUS] = dict(schema='ar-product-evidence-status-v1', source=source,
                         lanes={lane: {key: outcome[key] for key in ('state', 'reason')} for lane, outcome in outcomes.items()})
    for lane, outcome in outcomes.items():
        if outcome['state'] == 'available': result[lane] = decode(canonical(outcome['reference']))
    require(len(canonical(result)) <= MAX_DOCUMENT, 'delivery manifest exceeds 64 KiB')
    return result


@dataclass(frozen=True)
class FrozenCandidate:
    """Immutable bytes; readers receive fresh objects, never mutable intent aliases."""
    raw: bytes

    @property
    def sha256(self): return digest(self.raw)

    def document(self): return decode(self.raw)


def freeze_candidate(base_raw, enabled, outcomes, selection, *, writer_revision):
    require(type(base_raw) is bytes and len(base_raw) <= MAX_DOCUMENT, 'invalid base manifest bytes')
    validate_enabled(enabled); require(bool(enabled), 'disabled delivery has no optional candidate')
    base = decode(base_raw); apply_status(base, enabled, outcomes)
    fields(selection, SELECTION_FIELDS)
    require(all(type(value) is str and SHA.fullmatch(value) for value in selection.values()), 'invalid selected source binding')
    require(type(writer_revision) is str and re.fullmatch('[0-9a-f]{40}', writer_revision), 'exact writer revision required')
    value = dict(schema='ar-product-evidence-candidate-v1', source=source_reference(base),
                 base_manifest_sha256=digest(base_raw), base_bundle_sha256=bundle_sha256(base),
                 selection=selection, writer_revision=writer_revision, enabled=list(enabled), lanes=outcomes, publication_authorized=False)
    raw = canonical(value); require(len(raw) <= MAX_DOCUMENT, 'optional candidate exceeds 64 KiB')
    return FrozenCandidate(raw)


def load_candidate(raw, expected_sha256, *, base_raw, selection, writer_revision):
    require(type(raw) is bytes and len(raw) <= MAX_DOCUMENT and digest(raw) == expected_sha256,
            'optional candidate digest or bytes differ')
    value = decode(raw)
    fields(value, ('schema', 'source', 'base_manifest_sha256', 'base_bundle_sha256', 'selection',
                   'writer_revision', 'enabled', 'lanes', 'publication_authorized'))
    expected = freeze_candidate(base_raw, value['enabled'], value['lanes'], selection, writer_revision=writer_revision)
    require(raw == expected.raw, 'optional candidate source/base/intent changed')
    return expected
