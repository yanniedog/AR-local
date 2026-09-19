"""Bounded request spacing shared by document fetches in the collector process."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable


class HostThrottleFailure(Exception):
    pass


class HostThrottle:
    """One HTTP request per host per second, including redirect hops.

    The worker's existing exclusive collector lock provides process ownership.
    Entries expire after the spacing interval; active entries are never evicted
    to make room for another host. Waiting consumes the caller's original budget.
    Production callers supply the actual send callback so ownership covers it.
    """

    def __init__(self, *, clock=time.monotonic, sleep=time.sleep):
        self.clock = clock
        self.sleep = sleep
        self.starts: OrderedDict[str, float] = OrderedDict()
        self.sending: set[str] = set()
        self.lock = threading.Lock()

    def wait(self, host: str, deadline: float, check: Callable[[], None],
             send: Callable[[], None] | None = None) -> None:
        while True:
            check()
            with self.lock:
                now = self.clock()
                if now >= deadline:
                    raise HostThrottleFailure('request_deadline')
                while (self.starts and next(iter(self.starts)) not in self.sending
                       and next(iter(self.starts.values())) + 1 <= now):
                    self.starts.popitem(last=False)
                delay = 0.1 if host in self.sending else max(0.0, self.starts.get(host, now - 1) + 1 - now)
                if delay == 0:
                    if host not in self.starts and len(self.starts) >= 4096:
                        raise HostThrottleFailure('host_throttle_capacity')
                    self.starts[host] = now
                    self.starts.move_to_end(host)
                    if send is None:
                        return
                    self.sending.add(host)
                    break
                if now + delay >= deadline:
                    raise HostThrottleFailure('request_deadline')
            # Recheck the live ingest/resource guard while waiting, not just
            # before the first attempt. Do not block unrelated hosts on sleep.
            self.sleep(min(0.1, delay))
        try:
            check()
            if self.clock() >= deadline:
                raise HostThrottleFailure('request_deadline')
            send()
        finally:
            with self.lock:
                # Timestamp after sending, while this host remains owned. A
                # descheduled sender cannot make the next actual send bunch up.
                self.starts[host] = self.clock()
                self.starts.move_to_end(host)
                self.sending.remove(host)


HOST_THROTTLE = HostThrottle()
