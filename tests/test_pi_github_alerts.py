import json
import pytest

from pi_github_alerts import AlertStore, DeliveryError


class GitHubStub:
    def __init__(self):
        self.rows = {}; self.posts = 0; self.fail_after_post = False; self.methods = []

    def find(self, marker, number=None):
        return next((r for r in self.rows.values() if marker in r['body']), None)

    def request(self, method, suffix, value=None):
        self.methods.append(method)
        if method == 'POST':
            self.posts += 1
            self.rows[self.posts] = {**value, 'number': self.posts, 'state': 'open'}
            if self.fail_after_post:
                self.fail_after_post = False
                raise DeliveryError('GITHUB_UNAVAILABLE_OR_INVALID_RESPONSE')
            return self.rows[self.posts]
        number = int(suffix.split('/')[-1]); self.rows[number].update(value)
        return self.rows[number]


def test_ambiguous_create_reconciles_without_duplicate(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub(); github.fail_after_post = True
    store.observe('drive-access', 'Drive access problem', 'AUTH_REFRESH_FAILED', healthy=False)
    assert store.flush(github)['result'] == 'QUEUED'
    assert store.read()['incidents']['drive-access']['delivered_revision'] == 0
    store.flush(github)
    assert github.posts == 1
    assert store.read()['incidents']['drive-access']['issue_number'] == 1


def test_unchanged_failure_does_not_post_again(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub()
    for _ in range(3):
        store.observe('drive-access', 'Drive access problem', 'AUTH_REFRESH_FAILED', healthy=False)
        store.flush(github)
    assert github.posts == 1
    assert store.read()['incidents']['drive-access']['revision'] == 1


def test_offline_failure_then_recovery_still_reports_incident(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub()
    store.observe('drive-access', 'Drive access problem', 'AUTH_REFRESH_FAILED', healthy=False)
    store.observe('drive-access', 'Drive access problem', 'OK', healthy=True)
    store.flush(github)
    assert github.posts == 1 and github.rows[1]['state'] == 'closed'
    assert 'AUTH_REFRESH_FAILED' in github.rows[1]['body']
    assert 'Recovered' in github.rows[1]['body']


def test_recurrence_reopens_same_issue(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub()
    for healthy in (False, True, False):
        store.observe('drive-access', 'Drive access problem', 'AUTH_REFRESH_FAILED', healthy=healthy)
        store.flush(github)
    assert github.posts == 1 and github.rows[1]['state'] == 'open'
    assert 'Last recovery (UTC):' in github.rows[1]['body']
    assert '\nRecovered (UTC):' not in github.rows[1]['body']


def test_concurrent_new_transition_remains_pending(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub()
    original = github.request
    def during_delivery(method, suffix, value=None):
        result = original(method, suffix, value)
        if method == 'POST':
            store.observe('drive-access', 'Drive access problem', 'OK', healthy=True)
        return result
    github.request = during_delivery
    store.observe('drive-access', 'Drive access problem', 'AUTH_REFRESH_FAILED', healthy=False)
    store.flush(github)
    row = store.read()['incidents']['drive-access']
    assert row['revision'] > row['delivered_revision']


def test_new_active_issue_needs_only_post_but_recovery_still_patches(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub()
    store.observe('drive-access', 'Drive access problem', 'AUTH_REFRESH_FAILED', healthy=False)
    store.flush(github)
    assert github.methods == ['POST']
    store.observe('drive-access', 'Drive access problem', 'OK', healthy=True)
    store.flush(github)
    assert github.methods == ['POST', 'PATCH'] and github.rows[1]['state'] == 'closed'


def test_recovered_undelivered_issue_must_be_closed_after_creation(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub()
    store.observe('drive-access', 'Drive access problem', 'AUTH_REFRESH_FAILED', healthy=False)
    store.observe('drive-access', 'Drive access problem', 'OK', healthy=True)
    store.flush(github)
    assert github.methods == ['POST', 'PATCH'] and github.rows[1]['state'] == 'closed'


def test_healthy_never_creates_incident(tmp_path):
    store = AlertStore(tmp_path)
    store.observe('drive-access', 'Drive access problem', 'OK', healthy=True)
    assert store.read()['incidents'] == {}


def test_corrupt_state_never_discards_undelivered_incident(tmp_path):
    store = AlertStore(tmp_path); store.path.write_text('{broken')
    with pytest.raises(json.JSONDecodeError):
        store.observe('drive-access', 'Drive access problem', 'AUTH_REFRESH_FAILED', healthy=False)
    assert store.path.read_text() == '{broken'


def test_failed_recovery_does_not_block_later_incident_and_remains_retryable(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub()
    store.observe('delivery-test:707', 'Delivery test', 'DELIVERY_TEST', healthy=False)
    store.flush(github)
    store.observe('delivery-test:707', 'Delivery test', 'DELIVERY_TEST', healthy=True)
    store.observe('drive-access', 'Drive access problem', 'AUTH_REVOKED', healthy=False)
    original = github.request
    def blocked(method, suffix, value=None):
        if method == 'PATCH' and suffix == 'issues/1':
            raise DeliveryError('GITHUB_HTTP_403')
        return original(method, suffix, value)
    github.request = blocked
    outcome = store.flush(github)
    assert outcome['result'] == 'QUEUED' and outcome['category'] == 'GITHUB_HTTP_403'
    assert outcome['issues'] == [2]
    assert outcome['outcomes'] == [
        {'incident': 'delivery-test:707', 'result': 'QUEUED', 'category': 'GITHUB_HTTP_403'},
        {'incident': 'drive-access', 'result': 'DELIVERED', 'issue': 2}]
    state = store.read()['incidents']
    assert state['delivery-test:707']['delivered_revision'] < state['delivery-test:707']['revision']
    assert state['drive-access']['delivered_revision'] == state['drive-access']['revision']
    github.request = original
    assert store.flush(github)['result'] == 'DELIVERED'
    assert github.posts == 2 and github.rows[1]['state'] == 'closed'


def test_deadline_exhaustion_never_gets_a_fresh_budget_for_later_incident(tmp_path, monkeypatch):
    import time
    import pi_github_alerts as alerts
    store = AlertStore(tmp_path)
    for key in ('a', 'b'):
        store.observe(key, 'Access problem', 'AUTH_REVOKED', healthy=False)
    client = alerts.GitHub('unit/repo', 'unit-secret')
    client.deadline = time.monotonic() - 1
    monkeypatch.setattr(alerts.subprocess, 'run', lambda *a, **kw: pytest.fail('expired budget launched a worker'))
    outcome = store.flush(client)
    assert outcome['result'] == 'QUEUED' and outcome['issues'] == []
    assert [row['category'] for row in outcome['outcomes']] == ['GITHUB_DELIVERY_DEADLINE'] * 2
    assert all(row['delivered_revision'] == 0 for row in store.read()['incidents'].values())


def test_unexpected_delivery_error_text_is_not_exposed_in_incident_outcome(tmp_path):
    store = AlertStore(tmp_path); github = GitHubStub()
    store.observe('drive-access', 'Drive access problem', 'AUTH_REVOKED', healthy=False)
    def fail(*_): raise DeliveryError('unexpected unit-secret provider text')
    github.find = fail
    result = store.flush(github)
    assert result['category'] == 'GITHUB_WORKER_FAILED'
    assert 'unit-secret' not in json.dumps(result)
