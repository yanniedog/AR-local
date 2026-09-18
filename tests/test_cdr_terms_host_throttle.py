"""Connection-control tests; no synthetic business facts or network traffic."""
import pytest

from cdr_terms import acquisition as http
from cdr_terms.acquisition_throttle import HostThrottle, HostThrottleFailure


class Clock:
    def __init__(self):
        self.now = 100.0
        self.waits = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture
def limited():
    clock = Clock()
    return clock, HostThrottle(clock=clock.time, sleep=clock.sleep)


def test_same_host_spaced_but_other_host_is_immediate(limited):
    clock, limiter = limited
    for host in ('bank.example', 'other.example', 'bank.example', 'bank.example'):
        limiter.wait(host, 104, lambda: None)
    assert clock.now == pytest.approx(102)
    assert sum(clock.waits) == pytest.approx(2)
    assert max(clock.waits) <= 0.1


def test_deadline_refuses_without_reserving_slot_or_sleeping(limited):
    clock, limiter = limited
    limiter.wait('bank.example', 102, lambda: None)
    with pytest.raises(HostThrottleFailure, match='request_deadline'):
        limiter.wait('bank.example', 101, lambda: None)
    assert clock.waits == []
    assert limiter.starts == {'bank.example': 100}


def test_guard_change_during_wait_stops_before_second_admission(limited):
    clock, limiter = limited
    limiter.wait('bank.example', 102, lambda: None)
    def guard():
        if clock.now > 100:
            raise http.OperationalDeferral('ingest_active')
    with pytest.raises(http.OperationalDeferral, match='ingest_active'):
        limiter.wait('bank.example', 102, guard)
    assert clock.now == pytest.approx(100.1)
    assert limiter.starts['bank.example'] == 100


def test_host_bound_never_evicts_active_host(limited):
    clock, limiter = limited
    for index in range(4096):
        limiter.wait(str(index), 102, lambda: None)
    with pytest.raises(HostThrottleFailure, match='host_throttle_capacity'):
        limiter.wait('new', 102, lambda: None)
    assert len(limiter.starts) == 4096 and limiter.starts['0'] == 100
    clock.now = 101
    limiter.wait('new', 102, lambda: None)
    assert limiter.starts == {'new': 101}


def test_expired_caller_cannot_connect(limited):
    clock, limiter = limited
    with pytest.raises(HostThrottleFailure, match='request_deadline'):
        limiter.wait('bank.example', clock.now, lambda: None)
    assert not limiter.starts


def test_http_admission_shares_budget_and_rechecks_guard(monkeypatch, limited):
    clock, limiter = limited
    monkeypatch.setattr(http, 'HOST_THROTTLE', limiter)
    policy = http.FetchPolicy(allowed_hosts=frozenset({'bank.example'}))
    http._throttle_request('https://bank.example/a', policy, 103)
    http._throttle_request('https://bank.example/b', policy, 103)
    assert clock.now == pytest.approx(101)
    with pytest.raises(http.FetchFailure, match='request_deadline'):
        http._throttle_request('https://bank.example/c', policy, 101.5)
    assert limiter.starts['bank.example'] == pytest.approx(101)
    policy = http.FetchPolicy(request_guard=lambda: 'ingest_active')
    with pytest.raises(http.OperationalDeferral, match='ingest_active'):
        http._throttle_request('https://bank.example/c', policy, 103)
    assert limiter.starts['bank.example'] == pytest.approx(101)


def test_rejected_host_never_reserves_a_slot(monkeypatch, limited):
    _, limiter = limited
    monkeypatch.setattr(http, 'HOST_THROTTLE', limiter)
    with pytest.raises(http.FetchFailure, match='host_not_allowed'):
        http._connection('https://unapproved.example/', http.FetchPolicy(allowed_hosts=frozenset({'bank.example'})), 3)
    assert not limiter.starts


@pytest.mark.parametrize('timeout,success,delay', [(3, True, 0), (3, True, 0.9), (0.5, False, 0)])
def test_redirect_hop_uses_same_host_spacing_and_original_deadline(monkeypatch, limited, timeout, success, delay):
    from tests.test_cdr_terms_graph import Connection, Response
    clock, limiter = limited
    monkeypatch.setattr(http.time, 'monotonic', clock.time)
    monkeypatch.setattr(http, 'HOST_THROTTLE', limiter)
    monkeypatch.setattr(http, '_public_address', lambda *args: '93.184.216.34')
    starts, requests, sends = [], [], []
    class Pinned(Connection):
        def __init__(self, *args):
            response = Response(302, {'Location': '/second'}) if not starts else Response(200)
            response.read1 = response.read
            super().__init__(response, requests)
        def connect(self):
            if not starts:
                clock.now += delay
            starts.append(clock.now)
        def request(self, method, target, headers):
            sends.append(clock.now)
            super().request(method, target, headers)
    monkeypatch.setattr(http, '_PinnedHTTPS', Pinned)
    policy = http.FetchPolicy(timeout_seconds=timeout, allowed_hosts=frozenset({'bank.example'}))
    if success:
        result = http.fetch_document('https://bank.example/first', policy=policy)
        assert result['status'] == 'fetched' and sends == [100 + delay, pytest.approx(101 + delay)]
        assert [r[0] for r in requests] == ['/first', '/second']
    else:
        with pytest.raises(http.FetchFailure, match='request_deadline'):
            http.fetch_document('https://bank.example/first', policy=policy)
        assert len(requests) == 1 and sends == [100]


def test_concurrent_fetchers_cannot_claim_same_host_together():
    import time
    from concurrent.futures import ThreadPoolExecutor
    limiter = HostThrottle()
    deadline = time.monotonic() + 5
    def enter(_):
        limiter.wait('bank.example', deadline, lambda: None)
        return time.monotonic()
    with ThreadPoolExecutor(max_workers=3) as pool:
        times = sorted(pool.map(enter, range(3)))
    assert all(right - left >= 0.99 for left, right in zip(times, times[1:]))
