"""Presentation migrations use incident metadata, never fabricated health samples."""
from datetime import datetime, timedelta, timezone
import json

import pytest

import pi_github_alerts as alerts
import pi_issue_watchdog as watch
from tests.test_pi_github_alerts import GitHubStub

NOW = datetime(2026, 11, 1, 22, tzinfo=timezone.utc)
DAY = '2026-11-02'  # Latest 01:00 Hobart due date, not the UTC date.
KEY = 'ingest:' + DAY
TITLE = 'Pi ingest needs attention: ' + DAY


def legacy(store, github, key=KEY, title=TITLE, category='INGEST_PARTIAL', *, recovered=False):
    store.observe(key, title, category, healthy=False)
    if recovered:
        store.observe(key, title, category, healthy=True)
    store.flush(github)
    state = store.read()
    row = state['incidents'][key]
    row.pop('body_presentation_version')
    row['operator_note'] = 'Retain this local investigation history.'
    store.write(state)
    github.rows[row['issue_number']]['body'] = row['marker'] + '\nLegacy presentation.'
    return dict(row)


def stable_fields(row):
    return {k: v for k, v in row.items() if k not in {
        'title', 'revision', 'delivered_revision', 'delivered_at',
        'body_presentation_version', 'presentation_only_revision'}}


@pytest.mark.parametrize('stamp,day', [
    ('2026-11-01T23:59:59+11:00', '2026-11-01'),
    ('2026-11-02T00:00:00+11:00', '2026-11-01'),
    ('2026-11-02T00:59:59.999999+11:00', '2026-11-01'),
    ('2026-11-02T01:00:00+11:00', '2026-11-02'),
    ('2026-07-01T00:59:59+10:00', '2026-06-30'),
    ('2026-07-01T01:00:00+10:00', '2026-07-01'),
    ('2027-01-01T00:00:00+11:00', '2026-12-31'),
    ('2026-10-04T00:59:59+10:00', '2026-10-03'),  # DST starts later that morning.
    ('2026-10-04T01:00:00+10:00', '2026-10-04'),
    ('2026-10-04T03:00:00+11:00', '2026-10-04'),
    ('2026-04-05T00:59:59+11:00', '2026-04-04'),  # DST ends later that morning.
    ('2026-04-05T01:00:00+11:00', '2026-04-05'),
    ('2026-04-05T02:30:00+11:00', '2026-04-05'),  # First occurrence.
    ('2026-04-05T02:30:00+10:00', '2026-04-05'),  # Repeated hour.
])
def test_refresh_targets_latest_due_date_across_midnight_and_dst(stamp, day):
    class Capture:
        def refresh_presentations(self, titles):
            self.titles = titles
    store = Capture()
    watch.refresh_current_ingest_presentations(store, datetime.fromisoformat(stamp).astimezone(timezone.utc))
    assert store.titles == {
        'ingest:' + day: 'Pi ingest needs attention: ' + day,
        'ingest-watchdog:' + day: watch.WATCHDOG_TITLE + day,
        'ingest-schedule:' + day: 'Pi scheduled ingest missed: ' + day,
    }


@pytest.mark.parametrize('stamp', ['2026-11-02T00:00:00+11:00', '2026-11-02T00:59:59+11:00'])
def test_midnight_refresh_preserves_health_identity_and_other_days(tmp_path, stamp):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    families = ('ingest', 'ingest-watchdog', 'ingest-schedule')
    for day in ('2026-10-31', '2026-11-01', '2026-11-02'):
        for family in families:
            key = family + ':' + day
            legacy(store, github, key, 'Old wording: ' + key)
    before = store.read()['incidents']
    github.methods.clear()
    now = datetime.fromisoformat(stamp).astimezone(timezone.utc)
    watch.refresh_current_ingest_presentations(store, now)
    after = store.read()['incidents']
    assert after.keys() == before.keys()
    for key, row in after.items():
        assert stable_fields(row) == stable_fields(before[key])
        if key.endswith(':2026-11-01'):
            assert row['revision'] == before[key]['revision'] + 1
            assert row['presentation_only_revision'] == row['revision']
        else:
            assert row == before[key]
    assert github.methods == []
    snapshot = store.path.read_bytes()
    watch.refresh_current_ingest_presentations(store, now)
    assert store.path.read_bytes() == snapshot


@pytest.mark.parametrize('recovered', [False, True])
def test_body_only_refresh_preserves_all_history_and_patches_once(tmp_path, recovered):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    before = legacy(store, github, recovered=recovered)
    # Operator's remote state is not a new Pi health observation.
    github.rows[1]['state'] = 'closed' if not recovered else 'open'
    remote_state = github.rows[1]['state']
    github.methods.clear()
    store.refresh_presentations({KEY: TITLE})
    queued = store.read()['incidents'][KEY]
    assert stable_fields(queued) == stable_fields(before)
    assert queued['revision'] == before['revision'] + 1
    assert queued['delivered_revision'] == before['delivered_revision']
    for _ in range(2):
        store.refresh_presentations({KEY: TITLE})
        store.flush(github)
    after = store.read()['incidents'][KEY]
    assert stable_fields(after) == stable_fields(before)
    assert after['revision'] == after['delivered_revision'] == queued['revision']
    assert github.methods == ['PATCH']
    assert github.rows[1]['state'] == remote_state
    assert 'incomplete provider coverage' in github.rows[1]['body']


def test_presentation_only_delivery_cannot_create_deleted_remote_incident(tmp_path):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    legacy(store, github)
    store.refresh_presentations({KEY: TITLE})
    github.rows.clear(); github.methods.clear()
    result = store.flush(github)
    assert result['category'] == 'GITHUB_PRESENTATION_TARGET_MISSING'
    assert github.methods == []
    before = store.path.read_bytes()
    store.refresh_presentations({KEY: TITLE})
    assert store.path.read_bytes() == before


def test_pending_real_recovery_remains_deliverable_after_refresh(tmp_path):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    legacy(store, github)
    store.observe(KEY, TITLE, 'INGEST_PARTIAL', healthy=True)
    state = store.read(); state['incidents'][KEY].pop('body_presentation_version'); store.write(state)
    before = store.read()['incidents'][KEY]
    store.refresh_presentations({KEY: TITLE})
    assert stable_fields(store.read()['incidents'][KEY]) == stable_fields(before)
    store.flush(github)
    assert github.rows[1]['state'] == 'closed'


@pytest.mark.parametrize('recovered', [False, True])
def test_new_health_transition_supersedes_pending_presentation_before_flush(tmp_path, recovered):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    legacy(store, github, recovered=recovered)
    github.methods.clear()
    store.refresh_presentations({KEY: TITLE})
    presentation = store.read()['incidents'][KEY]
    store.observe(KEY, TITLE, 'INGEST_PARTIAL', healthy=not recovered)
    transition = store.read()['incidents'][KEY]
    assert transition['revision'] == presentation['revision'] + 1
    assert transition['presentation_only_revision'] != transition['revision']
    store.flush(github)
    assert github.rows[1]['state'] == ('open' if recovered else 'closed')
    assert github.methods == ['PATCH']
    store.flush(github)
    assert github.methods == ['PATCH']


def test_new_observations_and_title_revision_do_not_get_redundant_migration(tmp_path):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    store.observe(KEY, TITLE, 'INGEST_PARTIAL', healthy=False)
    store.flush(github)
    before = store.path.read_bytes()
    store.refresh_presentations({KEY: TITLE})
    assert store.path.read_bytes() == before
    store.observe(KEY, 'Updated title', 'INGEST_PARTIAL', healthy=False)
    before = store.path.read_bytes()
    store.refresh_presentations({KEY: 'Updated title'})
    assert store.path.read_bytes() == before


def test_new_body_version_updates_once_without_inventing_failure_or_recovery(tmp_path, monkeypatch):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    before = legacy(store, github)
    store.refresh_presentations({KEY: TITLE})
    monkeypatch.setattr(alerts, 'BODY_PRESENTATION_VERSION', alerts.BODY_PRESENTATION_VERSION + 1)
    store.refresh_presentations({KEY: TITLE})
    queued = store.read()['incidents'][KEY]
    assert queued['presentation_only_revision'] == queued['revision'] == before['revision'] + 2
    assert stable_fields(queued) == stable_fields(before)
    snapshot = store.path.read_bytes()
    store.refresh_presentations({KEY: TITLE})
    assert store.path.read_bytes() == snapshot


def natural_tick(monkeypatch, store, github):
    import pi_drive_access_probe
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)
    monkeypatch.setattr(watch, 'datetime', Clock)
    monkeypatch.setattr(watch, 'configured_store', lambda: store)
    monkeypatch.setattr(watch, 'unit_state', lambda _: {
        'started_at': Clock.fromtimestamp(watch.latest_daily_due_utc(NOW).timestamp(), timezone.utc),
        'ActiveState': 'inactive',
        'Result': 'timeout', 'ExecMainStatus': '1', 'ExecMainPID': '123'})
    monkeypatch.setattr(watch, 'timer_last_trigger', lambda: None)
    monkeypatch.setattr(watch, 'completion', lambda *_: 'PARTIAL')
    monkeypatch.setattr(watch, 'backup_check', lambda *_: {'status': 'RUNNING'})
    monkeypatch.setattr(pi_drive_access_probe, 'probe', lambda *_: {'status': 'PASS', 'category': 'OK'})
    monkeypatch.setattr(watch, 'deliver', lambda current: current.flush(github))


def test_natural_tick_refreshes_failed_watchdog_and_unchanged_partial_without_recovery(tmp_path, monkeypatch, capsys):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    legacy(store, github)
    watchdog = 'ingest-watchdog:' + DAY
    legacy(store, github, watchdog, 'Pi ingest watchdog failed: ' + DAY, 'INGEST_WATCHDOG_FAILED')
    old = 'ingest:2026-11-01'
    legacy(store, github, old, 'Old retained title')
    store.observe('ingest-schedule:' + DAY, 'Never failed watermark', 'SCHEDULED_INGEST_NOT_STARTED',
                  healthy=True, observation_at=NOW - timedelta(minutes=1))
    before = store.read()['incidents']
    github.methods.clear()
    natural_tick(monkeypatch, store, github)
    assert watch.main([]) == 0
    assert json.loads(capsys.readouterr().out)['ingest']['status'] == 'PARTIAL'
    after = store.read()['incidents']
    assert after.keys() == before.keys()
    assert after[old] == before[old]
    assert after['ingest-schedule:' + DAY] == before['ingest-schedule:' + DAY]
    for key in (KEY, watchdog):
        assert stable_fields(after[key]) == stable_fields(before[key])
        assert after[key]['active'] is True
        assert after[key]['revision'] == before[key]['revision'] + 1
    assert after[watchdog]['title'] == watch.WATCHDOG_TITLE + DAY
    assert github.methods == ['PATCH', 'PATCH']
    snapshot = store.path.read_bytes()
    assert watch.main([]) == 0
    assert store.path.read_bytes() == snapshot
    assert github.methods == ['PATCH', 'PATCH']


def test_checks_only_cannot_refresh_existing_or_create_spool(tmp_path, monkeypatch, capsys):
    store = alerts.AlertStore(tmp_path); github = GitHubStub()
    legacy(store, github)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    natural_tick(monkeypatch, store, github)
    monkeypatch.setattr(watch, 'configured_store', lambda: pytest.fail('read-only opened spool'))
    monkeypatch.setattr(watch, 'refresh_current_ingest_presentations', lambda *_: pytest.fail('read-only migration'))
    monkeypatch.setattr(watch, 'deliver', lambda *_: pytest.fail('read-only delivery'))
    assert watch.main(['--checks-only']) == 0
    assert json.loads(capsys.readouterr().out)['delivery']['result'] == 'NOT_REQUESTED'
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_empty_or_revision_zero_rows_are_not_incidents_to_refresh(tmp_path):
    store = alerts.AlertStore(tmp_path)
    store.refresh_presentations({KEY: TITLE})
    assert not store.path.exists()
    store.observe(KEY, TITLE, 'INGEST_PARTIAL', healthy=True, observation_at=NOW)
    before = store.path.read_bytes()
    store.refresh_presentations({KEY: 'New wording'})
    assert store.path.read_bytes() == before
