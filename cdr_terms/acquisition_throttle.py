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
    """

    def __init__(self, *, clock=time.monotonic, sleep=time.sleep):
        self.clock = clock
        self.sleep = sleep
        self.starts: OrderedDict[str, float] = OrderedDict()
        self.lock = threading.Lock()

    def wait(self, host: str, deadline: float, check: Callable[[], None]) -> None:
        while True:
            check()
            with self.lock:
                now = self.clock()
                if now >= deadline:
                    raise HostThrottleFailure('request_deadline')
                while self.starts and next(iter(self.starts.values())) + 1 <= now:
                    self.starts.popitem(last=False)
                delay = max(0.0, self.starts.get(host, now - 1) + 1 - now)
                if delay == 0:
                    if len(self.starts) >= 4096:
                        raise HostThrottleFailure('host_throttle_capacity')
                    self.starts[host] = now
                    self.starts.move_to_end(host)
                    return
                if now + delay >= deadline:
                    raise HostThrottleFailure('request_deadline')
            # Recheck the live ingest/resource guard while waiting, not just
            # before the first attempt. Do not block unrelated hosts on sleep.
            self.sleep(min(0.1, delay))


HOST_THROTTLE = HostThrottle()
