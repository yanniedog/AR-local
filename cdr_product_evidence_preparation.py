"""Held NEW-output preparation and read-only, caller-pinned package adoption.

No daily caller imports this module. No financial pending record is read/written.
Existing diagnostic markers stay false; returned candidates grant no publication.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from app_payload_product_evidence import prepare_snapshot, validate_snapshot
from app_payload_product_evidence_contract import Limits, SCOPE, canonical, decode, digest, fields, require
from app_payload_product_evidence_delivery_check import read_stable, verify_prepared as verify_facts
from app_payload_product_response_sources import ResponseSources
from app_payload_product_response_transport import verify_prepared as verify_responses
from app_payload_product_response_contract import SCOPE as RESPONSE_SCOPE
from app_payload_product_evidence_reference import encode_reference
from cdr_product_evidence_delivery_policy import (
    MalformedReady, delivery_flags, freeze_candidate, pending_outcomes, validate_enabled,
)
from cdr_product_evidence_source import SourceUnavailable, SourceUnsupported


@dataclass(frozen=True)
class PreparedSourceSnapshot:
    root: Path
    receipt: bytes

    @property
    def sha256(self): return digest(self.receipt)

    def document(self): return decode(self.receipt)


def _source_binding(source, snapshot):
    value = snapshot['source']
    require(all(value[key] == source.contract[key] for key in (
        'generation_id', 'observation_date', 'observation_state', 'contract_digest', 'source_generation_digest')),
        'snapshot differs from finalized source')
    require(value['contract_file_sha256'] == source.selection['contract_file_sha256'], 'snapshot contract bytes differ')
    artifacts = [row for row in source.contract['artifacts'] if row['path'] == 'local-cdr.sqlite']
    require(len(artifacts) == 1 and value['database'] == artifacts[0], 'snapshot database artifact differs')


def prepare_source_snapshot(source, output, *, writer_revision):
    """Caller establishes trusted exact code; this helper binds, not grants, that pin."""
    require(type(writer_revision) is str and re.fullmatch('[0-9a-f]{40}', writer_revision), 'exact writer revision required')
    source.recheck()
    snapshot = prepare_snapshot(source.database, source.contract_path, output)
    _source_binding(source, snapshot)
    source.recheck()
    root = Path(output).absolute(); raw, _ = read_stable(root / 'snapshot.json', Limits().index_bytes)
    receipt = dict(schema='ar-product-evidence-preparation-v1', source=source.source,
                   selection=source.selection, base_manifest_sha256=digest(source.base_raw),
                   snapshot_sha256=digest(raw), writer_revision=writer_revision,
                   contract_normalization=snapshot['source']['contract_normalization'],
                   fact_normalization=snapshot['source']['fact_normalization'],
                   publication_authorized=False, selection_verified=False)
    return PreparedSourceSnapshot(root, canonical(receipt))


def _checked_snapshot(source, prepared, writer_revision):
    require(type(writer_revision) is str and re.fullmatch('[0-9a-f]{40}', writer_revision), 'exact writer revision required')
    receipt = prepared.document()
    fields(receipt, ('schema', 'source', 'selection', 'base_manifest_sha256', 'snapshot_sha256',
                     'writer_revision', 'contract_normalization', 'fact_normalization',
                     'publication_authorized', 'selection_verified'))
    require(receipt['schema'] == 'ar-product-evidence-preparation-v1'
            and receipt['source'] == source.source and receipt['selection'] == source.selection
            and receipt['base_manifest_sha256'] == digest(source.base_raw)
            and receipt['writer_revision'] == writer_revision
            and receipt['publication_authorized'] is False and receipt['selection_verified'] is False,
            'preparation receipt source or authority differs')
    raw, _ = read_stable(prepared.root / 'snapshot.json', Limits().index_bytes)
    require(digest(raw) == receipt['snapshot_sha256'], 'source snapshot marker differs')
    snapshot = validate_snapshot(prepared.root); _source_binding(source, snapshot)
    require(all(receipt[k] == snapshot['source'][k] for k in ('contract_normalization', 'fact_normalization')),
            'preparation normalization provenance differs')
    return dict(source=snapshot['source'], snapshot_sha256=digest(raw), scope=SCOPE,
                core_sha256=source.base['files']['core']['sha256'], details_sha256=source.base['files']['details']['sha256'])


def adopt_prepared(source, prepared, enabled, packages, *, writer_revision, expected_preparation_sha256):
    """Missing package -> pending; supplied claimed-ready corruption -> fatal.

    Packages maps an enabled lane to {root, sha256}; the SHA must be the caller's
    fixed reviewed/writer receipt, never derived from a moving latest pointer.
    The preparation receipt pin must likewise be retained by the trusted caller,
    not discovered from a resumed receipt. No external receipt loader exists here.
    This does not independently rerun arbitrary external normalization code.
    """
    validate_enabled(enabled)
    require(set(packages).issubset(enabled), 'package supplied for disabled or unknown lane')
    if not enabled: return None
    source.recheck()
    try:
        require(type(prepared.receipt) is bytes and len(prepared.receipt) <= 65536, 'preparation receipt exceeds 64 KiB')
        require(digest(prepared.receipt) == expected_preparation_sha256, 'preparation receipt differs from fixed pin')
        binding = _checked_snapshot(source, prepared, writer_revision)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        if packages: raise MalformedReady('claimed-ready source preparation failed adoption') from error
        raise
    outcomes = pending_outcomes(enabled)
    for lane, supplied in packages.items():
        try:
            fields(supplied, ('root', 'sha256'))
            root = Path(supplied['root']).absolute()
            before, _ = read_stable(root / 'prepared.json', 65536 + 1024)
            require(digest(before) == supplied['sha256'], 'claimed-ready marker differs from fixed pin')
            if lane == 'product_evidence_v1':
                proof = verify_facts(root, expected_binding=binding)
            else:
                original = ResponseSources(prepared.root, source.exports, source.contract_path, expected_binding=binding)
                expected = dict(facts=binding, journal={key: original.proof.pointer[key] for key in (
                    'session_id', 'head_digest', 'promotion_manifest_sha256')}, scope=RESPONSE_SCOPE)
                proof = verify_responses(root, expected_binding=expected); original.recheck()
            reference, _ = encode_reference(lane, proof['capability'], source.base)
            require(read_stable(root / 'prepared.json', len(before))[0] == before, 'claimed-ready marker changed')
            outcomes[lane] = dict(state='available', reason='verified', reference=reference, prepared_sha256=supplied['sha256'])
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            raise MalformedReady('claimed-ready evidence failed adoption') from error
    source.recheck()
    return freeze_candidate(source.base_raw, enabled, outcomes, source.selection, writer_revision=writer_revision)


def unavailable_outcomes(enabled, error):
    """Explicit optional status only; never convert ready corruption to omission."""
    if isinstance(error, MalformedReady): raise error
    require(isinstance(error, SourceUnavailable), 'unknown optional source failure')
    outcomes = pending_outcomes(enabled)
    for lane in enabled: outcomes[lane] = dict(state='unsupported' if isinstance(error, SourceUnsupported) else 'unavailable', reason=error.reason)
    return outcomes


def preparation_enabled(environment=None):
    """Check before touching a source path: disabled defaults perform no I/O."""
    return delivery_flags(environment)
