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
    with pytest.raises(DeliveryError): store.flush(github)
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
