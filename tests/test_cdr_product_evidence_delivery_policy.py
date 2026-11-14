"""Pure intent/state tests; technical manifests never imply production acceptance."""
from copy import deepcopy
import pytest

from app_payload_product_evidence_contract import canonical, digest
from app_payload_revisions_state import bundle_sha256
from cdr_product_evidence_delivery_policy import (
    FLAGS, STATUS, MalformedReady, apply_status, delivery_flags, freeze_candidate,
    load_candidate, pending_outcomes,
)
from cdr_product_evidence_preparation import preparation_enabled, unavailable_outcomes
from cdr_product_evidence_source import SourceUnavailable, SourceUnsupported
from tests.product_evidence_finalized_fixture import finalized, WRITER, FACTS, RESPONSES, ENABLED


def test_default_off_does_not_require_source_or_change_legacy_bundle(monkeypatch):
    from pathlib import Path
    def forbidden(*args, **kwargs): pytest.fail('default-off touched source')
    monkeypatch.setattr(Path, 'open', forbidden)
    base = dict(schema_version=1, run_date='2026-05-19', files={k: dict(name=k+'.gz', sha256='a'*64, bytes=1) for k in ('core', 'details')})
    assert delivery_flags({}) == preparation_enabled({}) == ()
    projected = apply_status(base, ())
    assert canonical(projected) == canonical(base) and bundle_sha256(projected) == bundle_sha256(base)
    projected['files']['core']['bytes'] = 2
    assert base['files']['core']['bytes'] == 1


@pytest.mark.parametrize('value', ['', 'true', 'yes', '01', ' 1', '2', 1, True, None])
def test_flags_are_strict_and_never_truthy(value):
    with pytest.raises(ValueError): delivery_flags({FLAGS[FACTS]: value})


def test_lane_selection_and_truthful_optional_statuses(tmp_path):
    base = finalized(tmp_path)['base']
    assert delivery_flags({flag: '1' for flag in FLAGS.values()}) == ENABLED
    for state, reason in [('pending', 'not_prepared'), ('failed', 'preparation_failed'),
                           ('failed', 'budget_exceeded'), ('unsupported', 'unsupported_source_schema'),
                           ('unavailable', 'source_failed')]:
        outcomes = pending_outcomes((FACTS,)); outcomes[FACTS] = dict(state=state, reason=reason)
        result = apply_status(base, (FACTS,), outcomes)
        assert result[STATUS]['lanes'][FACTS] == outcomes[FACTS]
        assert result[STATUS]['lanes'][RESPONSES]['state'] == 'disabled'
        assert FACTS not in result and RESPONSES not in result and result['files'] == base['files']
        assert result[STATUS]['source'] == base['source_observation']


def test_malformed_claimed_ready_cannot_be_downgraded(tmp_path):
    base = finalized(tmp_path)['base']; outcomes = pending_outcomes(ENABLED)
    outcomes[FACTS] = dict(state='available', reason='verified')
    with pytest.raises(MalformedReady): apply_status(base, ENABLED, outcomes)
    error = MalformedReady('technical corruption')
    with pytest.raises(MalformedReady): unavailable_outcomes(ENABLED, error)
    assert unavailable_outcomes(ENABLED, SourceUnavailable('source_unavailable'))[FACTS]['state'] == 'unavailable'
    assert unavailable_outcomes(ENABLED, SourceUnsupported())[FACTS]['state'] == 'unsupported'


def test_candidate_exact_base_selection_writer_and_immutable_intent(tmp_path):
    base = finalized(tmp_path)['base']; raw = canonical(base)
    selection = {k: 'b'*64 for k in ('pointer_sha256', 'completion_sha256', 'contract_file_sha256', 'ledger_event_digest')}
    outcomes = pending_outcomes(ENABLED)
    candidate = freeze_candidate(raw, ENABLED, outcomes, selection, writer_revision=WRITER)
    pins = dict(base_raw=raw, selection=selection, writer_revision=WRITER)
    assert load_candidate(candidate.raw, candidate.sha256, **pins) == candidate
    assert candidate.document()['publication_authorized'] is False
    for altered in [dict(base_raw=raw+b' '), dict(writer_revision='c'*40),
                    dict(selection={**selection, 'pointer_sha256': 'c'*64})]:
        with pytest.raises(ValueError): load_candidate(candidate.raw, candidate.sha256, **{**pins, **altered})
    with pytest.raises(ValueError): load_candidate(candidate.raw, 'f'*64, **pins)
    document = candidate.document(); document['publication_authorized'] = True
    changed = canonical(document)
    with pytest.raises(ValueError): load_candidate(changed, digest(changed), **pins)
    outcomes[FACTS]['state'] = 'failed'; selection['pointer_sha256'] = 'd'*64
    assert candidate.document()['lanes'][FACTS]['state'] == 'pending'
    assert candidate.document()['selection']['pointer_sha256'] == 'b'*64


@pytest.mark.parametrize('enabled', [('unknown',), (FACTS, FACTS), tuple(reversed(ENABLED))])
def test_unknown_duplicate_unsorted_lanes_fail(enabled):
    with pytest.raises(ValueError): pending_outcomes(enabled)
