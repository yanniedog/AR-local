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


@pytest.mark.parametrize('hour,minute,restored', [(0, 29, True), (0, 30, False),
                                                (1, 0, False), (3, 29, False), (3, 30, True)])
def test_watchdog_preserves_protected_restoration_window(hour, minute, restored):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    store = FixtureStore()
    unit = 'ar-local-daily-watchdog.service'
    store.job['unit'] = unit
    events, kwargs = callbacks()
    now = datetime(2026, 10, 12, hour, minute, tzinfo=ZoneInfo('Australia/Hobart'))
    assert recover(store, unit, 'a'*32, now=now, **kwargs) is restored
    assert ('restart' in events) is restored
    if not restored: assert events == []


def test_daily_failure_can_restore_inside_watchdog_protected_window():
    from datetime import datetime, timezone
    events, kwargs = callbacks()
    assert recover(FixtureStore(), 'ar-local-daily.service', 'a'*32,
                   now=datetime(2026, 10, 11, 14, tzinfo=timezone.utc), **kwargs)
    assert 'restart' in events
