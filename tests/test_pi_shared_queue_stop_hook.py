from contextlib import contextmanager
import os
from types import SimpleNamespace

import pytest

from pi_shared_queue_stop_hook import recover


class FixtureStore:
    def __init__(self, *, started=True, state='running', invocation='a'*32,
                 ownership='live', same_cgroup=True):
        self.job = dict(id='fixture', unit='ar-local-daily.service',
                        invocation_id=invocation, cgroup='/fixture', state=state)
        if started is not None:
            self.job['command_started'] = started
        self.supervisor = SimpleNamespace(
            cgroup=lambda pid: '/fixture' if same_cgroup else '/other',
            ownership=lambda job: ownership)

    @contextmanager
    def transaction(self):
        yield {'jobs': [self.job]}


def callbacks(*, busy=False, legacy_ready=True):
    events = []
    @contextmanager
    def lease(path, role):
        events.append('lease')
        if busy:
            raise RuntimeError('occupied')
        try:
            yield
        finally:
            events.append('released')
    return events, dict(factory=lambda: lease, ready=lambda units: legacy_ready,
                        restart=lambda: events.append('restart'))


def test_started_matching_ingest_recovers_only_under_native_lease():
    events, kwargs = callbacks()
    assert recover(FixtureStore(), 'ar-local-daily.service', 'a'*32, **kwargs)
    assert events == ['lease', 'restart', 'released']


@pytest.mark.parametrize('options', [dict(started=False), dict(started=None),
                                   dict(state='waiting'), dict(invocation='b'*32),
                                   dict(ownership='unknown'), dict(same_cgroup=False)])
def test_unstarted_or_ambiguous_invocation_never_restarts_dashboard(options):
    events, kwargs = callbacks()
    assert not recover(FixtureStore(**options), 'ar-local-daily.service', 'a'*32, **kwargs)
    assert events == []


@pytest.mark.parametrize('options', [dict(busy=True), dict(legacy_ready=False)])
def test_active_native_or_legacy_owner_prevents_restart(options):
    events, kwargs = callbacks(**options)
    assert not recover(FixtureStore(), 'ar-local-daily.service', 'a'*32, **kwargs)
    assert 'restart' not in events
