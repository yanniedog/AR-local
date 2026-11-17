"""Optional setup failures cannot turn a completed capture into a failed ingest."""
from unittest.mock import Mock
import pytest

import pi_daily_sync as sync
import pi_product_evidence_intent as intent
import app_payload_product_evidence_daily as evidence
from app_payload_product_evidence_contract import canonical, decode
from pi_payload_retry_policy import publication_source_key
from tests.test_product_evidence_daily_intent import source
from tests.product_evidence_finalized_fixture import WRITER


def ordinary(source):
    fixture, _, contract = source
    pointer = decode(fixture['pointer'].read_bytes())
    # Remove the fixture's deliberately explicit ready-capable intent; exercise
    # the actual daily ordinary pointer and its unchanged financial CAS key.
    sync.clear_payload_publication_pending(fixture['state'].parent,
                                          sync.pending_publication_pointer(fixture['state'].parent))
    sync.mark_payload_publication_pending(fixture['state'].parent,'publication_started',pointer)
    return fixture,pointer,contract


def test_valid_admission_freezes_flags_and_writer_without_changing_pending_key(source,monkeypatch):
    fixture,pointer,contract=ordinary(source);repo=fixture['state'].parent
    monkeypatch.setenv('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY','1')
    monkeypatch.setenv('AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY','0')
    monkeypatch.setattr(intent,'writer_revision',lambda _:WRITER)
    key=publication_source_key({'pointer':pointer});admitted=intent.admit_financial_intent(repo,pointer)
    monkeypatch.setenv('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY','0')
    monkeypatch.setenv('AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY','invalid')
    monkeypatch.setattr(intent,'writer_revision',lambda _:pytest.fail('immutable intent re-read writer'))
    assert intent.admit_financial_intent(repo,pointer)==admitted
    assert sync.pending_publication_pointer(repo)==pointer
    assert publication_source_key(sync.read_payload_publication_pending(repo))==key
    worker=evidence.FinancialEvidence(repo,fixture['state'],admitted,contract,pending_pointer=pointer)
    root,_=worker.freeze(fixture['root']); assert intent.candidate_pin(repo,pointer)
    assert worker.resume()[0]==root
    monkeypatch.setattr(evidence,'writer_revision',lambda _:'b'*40)
    with pytest.raises(ValueError,match='writer'):worker.resume()
    assert intent.admit_financial_intent(repo,pointer)==admitted


def test_settling_pointer_removes_only_its_immutable_intent_and_candidate_references(source,monkeypatch):
    fixture,pointer,contract=ordinary(source);repo=fixture['state'].parent
    monkeypatch.setenv('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY','1')
    monkeypatch.setattr(intent,'writer_revision',lambda _:WRITER)
    first=intent.admit_financial_intent(repo,pointer)
    evidence.FinancialEvidence(repo,fixture['state'],first,contract,pending_pointer=pointer).freeze(fixture['root'])
    other={**pointer,'generation_id':'obs-technical-control'}
    sync.mark_payload_publication_pending(repo,'another source',other)
    second=intent.admit_financial_intent(repo,other)
    sync.clear_payload_publication_pending(repo,pointer)
    record=sync.read_payload_publication_pending(repo)
    assert record['pointer']==other and intent.financial_intent(repo,other)==second
    assert publication_source_key({'pointer':pointer}) not in record[intent.INTENTS]
    assert publication_source_key({'pointer':pointer}) not in record[intent.PINS]


def test_population_head_supersession_retains_other_queued_frozen_source(source,monkeypatch):
    import pi_population_publication
    fixture,pointer,contract=ordinary(source);repo=fixture['state'].parent
    monkeypatch.setenv('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY','1')
    monkeypatch.setattr(intent,'writer_revision',lambda _:WRITER)
    # Keep an unrelated head first, then queue and actually freeze this source.
    sync.clear_payload_publication_pending(repo,pointer)
    old={**pointer,'generation_id':'obs-old-control'}
    new={**pointer,'generation_id':'obs-new-control'}
    sync.mark_payload_publication_pending(repo,'old',old)
    sync.mark_payload_publication_pending(repo,'current',pointer)
    admitted=intent.admit_financial_intent(repo,pointer)
    worker=evidence.FinancialEvidence(repo,fixture['state'],admitted,contract,pending_pointer=pointer)
    root,_=worker.freeze(fixture['root']);pin=intent.candidate_pin(repo,pointer)
    # The existing population policy is independently tested; simulate only its
    # returned replacement to exercise newly introduced metadata preservation.
    monkeypatch.setattr(pi_population_publication,'supersede_population_pending',
                        lambda state,previous,pointer,replacement:{**replacement,'queued_pointers':[fixture_pointer]})
    fixture_pointer=pointer
    sync.mark_payload_publication_pending(repo,'verified replacement',new,allow_policy_supersession=True)
    assert intent.candidate_pin(repo,pointer)==pin and intent.financial_intent(repo,pointer)==admitted
    assert worker.resume()[0]==root


@pytest.mark.parametrize('fault', [
    'invalid-flag', 'dirty-writer', 'locked-store', 'permission',
    'corrupt-ready-package', 'timeout', 'enqueue-crash',
])
def test_optional_failures_do_not_block_financial_release_or_terminal_backup(source, monkeypatch, capsys, fault):
    import app_payload
    import pi_product_evidence_dispatch as dispatch
    fixture, pointer, contract = ordinary(source)
    repo = fixture['state'].parent
    monkeypatch.setattr(sync, 'REPO_ROOT', repo)
    monkeypatch.setattr(sync, 'ensure_runtime_data_writable', lambda _: None)
    monkeypatch.setattr(sync, 'pause_dashboard_for_ingest', lambda: False)
    monkeypatch.setattr(sync, 'refresh_economic_data', lambda _: None)
    ingest, backup = Mock(), Mock()
    monkeypatch.setattr(sync, 'run_checked', ingest)
    monkeypatch.setattr(sync, 'queue_drive_backup', backup)
    # Retained products supply source bytes. These protocol controls grant no
    # national-coverage, public-write or Pi activation authority.
    monkeypatch.setattr(sync, '_bounded_partial_v1_allowed', lambda _: True)
    monkeypatch.setattr(sync.gate, 'publication_allowed', lambda _: (True, 'bounded'))
    import app_payload_source_verification
    monkeypatch.setattr(app_payload_source_verification, 'verify_reconciled_source', lambda *a: True)
    monkeypatch.setattr(sync, 'v2_publication_allowed', lambda: False)
    monkeypatch.setenv('AR_LOCAL_APP_PAYLOAD', '1')
    monkeypatch.setenv('AR_LOCAL_PRODUCT_EVIDENCE_DELIVERY', 'invalid' if fault == 'invalid-flag' else '1')
    monkeypatch.setenv('AR_LOCAL_PRODUCT_RESPONSE_EVIDENCE_DELIVERY', '0')
    monkeypatch.setattr(intent, 'admit_financial_intent',
                        lambda *a: pytest.fail('financial release consulted optional intent'))
    monkeypatch.setattr(evidence, 'FinancialEvidence',
                        lambda *a, **k: pytest.fail('financial release consulted optional package'))
    errors = {'dirty-writer': ValueError('dirty writer'), 'locked-store': OSError('database locked'),
              'permission': PermissionError('optional store'), 'corrupt-ready-package': ValueError('hash mismatch'),
              'timeout': TimeoutError('optional work'), 'enqueue-crash': RuntimeError('optional crash')}
    if fault != 'invalid-flag':
        def failed_enqueue(*a, **k):
            raise errors[fault]
        monkeypatch.setattr(dispatch, 'enqueue_published', failed_enqueue)
    published = []
    def publish(*args, **kwargs):
        assert 'optional_evidence' not in kwargs
        assert sync.pending_publication_pointer(repo) == pointer
        published.append(kwargs)
        return fixture['base'], True, True
    monkeypatch.setattr(app_payload, 'build_and_publish_dual', publish)
    original = (fixture['root'] / 'manifest.json').read_bytes()
    assert sync.current_publication_pointer(repo) == pointer
    assert sync.main(['--banks-only']) == 0
    assert published and ingest.called and backup.call_args.args == ('terminal-ingest',)
    assert sync.pending_publication_pointer(repo) is None
    assert (fixture['root'] / 'manifest.json').read_bytes() == original
    assert 'optional evidence preparation' in capsys.readouterr().out


@pytest.mark.parametrize('name', [intent.INTENTS, intent.PINS])
def test_corrupt_optional_metadata_cannot_prevent_financial_settlement(source, name):
    fixture, pointer, _ = ordinary(source)
    repo = fixture['state'].parent
    record = sync.read_payload_publication_pending(repo)
    record[name] = ['invalid optional control']
    sync.atomic_replace_json(sync.payload_publication_pending_path(repo), record)
    sync.clear_payload_publication_pending(repo, pointer)
    assert sync.pending_publication_pointer(repo) is None
    retained = list((fixture['state'] / 'product-evidence-pending-errors').glob('*.json'))
    assert len(retained) == 1 and decode(retained[0].read_bytes()) == record
