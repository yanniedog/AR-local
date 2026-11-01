"""Keep real failures alertable while naming the evidence that actually failed."""
import pytest

from pi_ingest_observe import attention_categories, observation_failed
from pi_github_alerts import AlertStore
import pi_issue_watchdog as watch
from scripts import pi_ingest_cloud_incident as cloud
from tests.test_pi_ingest_cloud_incident import API, legacy, pi_incident, report


@pytest.mark.parametrize('result,expected', [
    ({'capture_due': True, 'capture_finalized': False, 'service_active': False}, ['CAPTURE_NOT_FINALIZED']),
    ({'capture_due': True, 'capture_finalized': False, 'service_active': True}, []),
    ({'capture_due': False, 'capture_finalized': False}, []),
    ({'capture_due': True, 'capture_finalized': True, 'publication_due': True,
      'publication': {'publication_current': False}}, ['PUBLICATION_NOT_CURRENT']),
    ({'capture_due': True, 'capture_finalized': True, 'publication_due': True,
      'publication': {'publication_current': False, 'status': 'UNKNOWN'}}, ['PUBLICATION_CHECK_UNAVAILABLE']),
    ({'status': 'UNKNOWN'}, ['CHECK_EVIDENCE_UNAVAILABLE']),
    ({'capture_due': True, 'capture_finalized': True, 'publication_due': True,
      'publication': {'publication_current': True}}, []),
    ({'capture_due': True, 'capture_finalized': False, 'publication_due': True,
      'publication': {'publication_current': False}}, ['CAPTURE_NOT_FINALIZED', 'PUBLICATION_NOT_CURRENT']),
])
def test_checks_remain_distinct_and_alertable(result, expected):
    assert attention_categories(result) == expected
    assert observation_failed(result) == bool(expected)


def test_cloud_migrates_misleading_title_once_without_new_issue_or_recovery():
    row = legacy()
    unrelated = {'name': 'operator-investigating', 'id': 7}
    row['labels'].append(unrelated)
    row.update(comments=5, created_at='2026-10-11T00:00:00Z')
    api = API([row])
    assert cloud.reconcile(api, report())['status'] == 'UPDATED'
    assert api.rows[1]['title'] == cloud.PUBLICATION_TITLE + '2026-10-11'
    assert api.rows[1]['state'] == 'open'
    assert api.rows[1]['labels'] == [unrelated, {'name': 'app-publication-unverified'}]
    for field in ('number', 'user', 'comments', 'created_at'):
        assert api.rows[1][field] == row[field]
    mutations = [(method, path, value) for method, path, value in api.calls if method != 'GET']
    # Only presentation and our labels change on the existing issue; no issue
    # creation/deletion, comment, or recovery transition is authorized here.
    assert [(method, path) for method, path, _ in mutations] == [
        ('PATCH', 'issues/1'), ('POST', 'issues/1/labels'),
        ('DELETE', 'issues/1/labels/ingest-missed')]
    assert 'state' not in mutations[0][2]
    assert mutations[1][2] == {'labels': ['app-publication-unverified']}
    api.calls.clear()
    assert cloud.reconcile(api, report())['status'] == 'UNCHANGED'
    assert all(method == 'GET' for method, _, _ in api.calls)


def test_new_and_legacy_publication_titles_are_not_two_distinct_incidents():
    row = legacy(2); row['title'] = cloud.PUBLICATION_TITLE + '2026-10-11'
    with pytest.raises(cloud.DeliveryError, match='AMBIGUOUS'):
        cloud.reconcile(API([legacy(), row]), report())


def test_renamed_watchdog_issue_keeps_identity_and_does_not_prove_fresh_health():
    row = pi_incident(kind='ingest-watchdog')
    row['title'] = watch.WATCHDOG_TITLE + '2026-10-11'
    api = API([row]); value = report(current=True)
    cloud.reconcile(api, value)
    assert api.rows[row['number']]['state'] == 'open'
    assert value['reported_ingest_incidents'][0]['evidence_scope'] == 'open_github_incident_not_fresh_pi_health'


def test_title_correction_preserves_failure_history_and_is_delivered_once(tmp_path):
    store = AlertStore(tmp_path)
    key = 'ingest-watchdog:2026-11-01'
    store.observe(key, 'Pi ingest watchdog failed: 2026-11-01', 'INGEST_WATCHDOG_FAILED', healthy=False)
    old = store.read()['incidents'][key]
    store.observe(key, watch.WATCHDOG_TITLE + '2026-11-01', 'INGEST_WATCHDOG_FAILED', healthy=False)
    new = store.read()['incidents'][key]
    assert new['revision'] == old['revision'] + 1
    for field in ['marker','first_seen','last_failure_at','changed_at','active','category']:
        assert new[field] == old[field]
    store.observe(key, new['title'], new['category'], healthy=False)
    assert store.read()['incidents'][key] == new
    assert 'does not by itself prove the ingest failed' in store.body(new)


def test_partial_stays_open_and_stale_start_is_not_silenced(tmp_path, monkeypatch):
    from tests.test_pi_issue_watchdog import units, NOW, DUE
    from datetime import timedelta
    monkeypatch.setattr(watch, 'completion', lambda *_: 'PARTIAL')
    monkeypatch.setattr(watch, 'timer_last_trigger', lambda: None)
    store = AlertStore(tmp_path)
    watch.ingest_checks(store, tmp_path, NOW, units(DUE - timedelta(days=1)))
    rows = store.read()['incidents']
    assert rows['ingest-schedule:2026-09-13']['active']
    partial = rows['ingest:2026-09-13']
    assert partial['active'] and partial['category'] == 'INGEST_PARTIAL'
    assert 'incomplete provider coverage' in store.body(partial)


def test_wording_change_cannot_deliver_a_never_failed_healthy_watermark(tmp_path):
    from datetime import datetime, timedelta, timezone
    store = AlertStore(tmp_path)
    now = datetime(2026, 11, 1, 2, tzinfo=timezone.utc)
    store.observe('ingest-schedule:2026-11-01', 'Old wording', 'SCHEDULED_INGEST_NOT_STARTED',
                  healthy=True, observation_at=now)
    store.observe('ingest-schedule:2026-11-01', 'Clearer wording', 'SCHEDULED_INGEST_NOT_STARTED',
                  healthy=True, observation_at=now + timedelta(minutes=1))
    row = store.read()['incidents']['ingest-schedule:2026-11-01']
    assert row['revision'] == row['delivered_revision'] == 0
    assert 'last_failure_at' not in row


def test_actual_capture_service_failure_remains_alertable(tmp_path, monkeypatch):
    from tests.test_pi_issue_watchdog import NOW, DUE
    monkeypatch.setattr(watch, 'unit_state', lambda _: {'started_at': DUE})
    store = AlertStore(tmp_path)
    result = watch.failure_event(store, watch.UNITS[0], NOW)
    assert result['category'] == 'INGEST_SERVICE_FAILED'
    assert store.read()['incidents']['ingest:2026-09-13']['active']


def test_delivered_watchdog_wording_patches_same_issue_once(tmp_path):
    from tests.test_pi_github_alerts import GitHubStub
    store = AlertStore(tmp_path); github = GitHubStub()
    key = 'ingest-watchdog:2026-11-01'
    store.observe(key, 'Pi ingest watchdog failed: 2026-11-01', 'INGEST_WATCHDOG_FAILED', healthy=False)
    store.flush(github)
    old = store.read()['incidents'][key]
    for _ in range(2):
        store.observe(key, watch.WATCHDOG_TITLE + '2026-11-01', 'INGEST_WATCHDOG_FAILED', healthy=False)
        store.flush(github)
    new = store.read()['incidents'][key]
    assert github.methods == ['POST', 'PATCH']
    assert old['issue_number'] == new['issue_number'] == 1
    assert github.rows[1]['state'] == 'open'
    assert new['last_failure_at'] == old['last_failure_at']
    assert new['revision'] == new['delivered_revision'] == 2


@pytest.mark.parametrize('category,scope', [
    ('INGEST_PARTIAL', 'incomplete provider coverage'),
    ('INGEST_SERVICE_FAILED', 'does not identify which capture, export or publication stage failed'),
    ('INGEST_MISSING', 'does not establish whether capture never started'),
    ('INGEST_INVALID', 'Capture completeness is unverified'),
    ('INGEST_UNVERIFIED_METADATA_LIMIT', 'not established as missing or failed'),
    ('INGEST_RUNTIME_EXCEEDED', 'does not establish a finalized capture or publication outcome'),
    ('INGEST_WATCHDOG_FAILED', 'underlying capture and publication results are unverified'),
])
def test_each_failure_scope_states_only_what_the_evidence_proves(tmp_path, category, scope):
    store = AlertStore(tmp_path)
    store.observe('ingest:2026-11-01', 'Needs attention', category, healthy=False)
    row = store.read()['incidents']['ingest:2026-11-01']
    assert row['active'] and row['category'] == category
    assert 'Evidence scope: ' in store.body(row) and scope in store.body(row)


@pytest.mark.parametrize('same_title', [False, True])
def test_watchdog_aliases_for_one_key_are_ambiguous_before_any_mutation(same_title):
    old = pi_incident(1, kind='ingest-watchdog')
    new = pi_incident(2, kind='ingest-watchdog')
    if not same_title:
        new['title'] = watch.WATCHDOG_TITLE + '2026-10-11'
    api = API([old, new])
    with pytest.raises(cloud.DeliveryError, match='AMBIGUOUS_PI_INCIDENT'):
        cloud.reconcile(api, report(current=True))
    assert all(method == 'GET' for method, _, _ in api.calls)
    assert api.rows[1] == old and api.rows[2] == new


def test_distinct_watchdog_dates_are_not_alias_conflicts():
    old = pi_incident(1, kind='ingest-watchdog', day='2026-10-10')
    new = pi_incident(2, kind='ingest-watchdog')
    new['title'] = watch.WATCHDOG_TITLE + '2026-10-11'
    value = report(current=True)
    cloud.reconcile(API([old,new]), value)
    assert [row['issue'] for row in value['reported_ingest_incidents']] == [2]
