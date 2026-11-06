"""Independent root observer for the entire fixed CI transaction.

Uses the plaintext broker's qualified Linux pidfd/accounting pattern. No unit
queries run in the 100ms sampler. All descendants share one aggregate budget.
"""
from __future__ import annotations
import os
from pathlib import Path
import select
import signal
import threading
import time

MIB = 1024**2


def members(group):
    root = Path('/sys/fs/cgroup') / group.lstrip('/')
    result = set(); count = 0
    for path in root.rglob('cgroup.procs'):
        count += 1
        if count > 256: raise RuntimeError('resource cgroup inventory exceeds bound')
        for text in path.read_text().splitlines():
            if not text.isdigit(): raise RuntimeError('invalid native cgroup PID')
            result.add(int(text))
    if not count: raise RuntimeError('native resource cgroup unavailable')
    return result


def host_sample():
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    vm = dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    page = os.sysconf('SC_PAGE_SIZE')
    if type(page) is not int or page < 1024 or page & (page - 1): raise RuntimeError('invalid page size')
    return {'available': int(memory['MemAvailable'].split()[0]) * 1024,
            'out': int(vm['pswpout']), 'in': int(vm['pswpin']), 'page': page}


def process(pid, group):
    """An exited pinned process may disappear; live accounting errors fail."""
    try: fd = os.pidfd_open(pid)
    except ProcessLookupError: return None
    try:
        poll = select.poll(); poll.register(fd, select.POLLIN)
        if poll.poll(0): return None
        path = Path('/proc') / str(pid)
        try:
            ticks = int((path / 'stat').read_text().rsplit(')', 1)[1].split()[19])
            values = dict(line.split(':', 1) for line in (path / 'smaps_rollup').read_text().splitlines() if ':' in line)
            if (path / 'cgroup').read_text().strip() != '0::' + group:
                raise RuntimeError('resource process escaped cgroup')
            if poll.poll(0): return None
            if int((path / 'stat').read_text().rsplit(')', 1)[1].split()[19]) != ticks:
                raise RuntimeError('resource PID identity changed')
            return {'ticks': ticks, 'rss': int(values['Rss'].split()[0]) * 1024,
                    'swap': int(values['Swap'].split()[0]) * 1024}
        except (FileNotFoundError, ProcessLookupError):
            if poll.poll(250): return None
            raise RuntimeError('live process resource proof unavailable')
    finally:
        os.close(fd)


def violation(host, baseline, previous, rss, swap, gap):
    if host['page'] != baseline['page']: return 'page_size_changed'
    if any(host[k] < previous[k] or previous[k] < baseline[k] for k in ('in', 'out')): return 'swap_counter_reset'
    if host['out'] != baseline['out']: return 'host_swap_out_activity'
    if (host['in'] - baseline['in']) * host['page'] > 16 * MIB: return 'cold_swap_in_budget'
    if host['available'] < 2560 * MIB: return 'host_memory_reserve'
    if rss >= 640 * MIB: return 'aggregate_rss_early_stop'
    if swap: return 'workload_swapped'
    if gap > 2: return 'supervision_sample_gap'
    return None


def kill_scope(group, excluded):
    """Only pidfd-pinned members of this exact invocation may be terminated."""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        pending = members(group) - set(excluded)
        if not pending: return True
        for pid in pending:
            try: fd = os.pidfd_open(pid)
            except ProcessLookupError: continue
            try:
                poll = select.poll(); poll.register(fd, select.POLLIN)
                if poll.poll(0): continue
                path = Path('/proc') / str(pid)
                ticks = (path / 'stat').read_text().rsplit(')', 1)[1].split()[19]
                if (path / 'cgroup').read_text().strip() != '0::' + group:
                    raise RuntimeError('cleanup process escaped cgroup')
                if ticks != (path / 'stat').read_text().rsplit(')', 1)[1].split()[19]:
                    raise RuntimeError('cleanup PID identity changed')
                if not poll.poll(0): signal.pidfd_send_signal(fd, signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError):
                if not poll.poll(250): raise
            finally:
                os.close(fd)
        time.sleep(.05)
    return not (members(group) - set(excluded))


class Observer:
    def __init__(self, binding):
        self.group = binding['cgroup']
        self.baseline = self.previous = host_sample()
        self.reason = None; self.last = time.monotonic(); self.samples = 0
        self.peak_rss = self.peak_swap = self.max_gap = 0
        self.stop = threading.Event(); self.thread = None; self.worker_active = False
        # Root coordinator, sudo parents and the exact queue wrapper only.
        self.excluded = {}; pid = os.getpid()
        for _ in range(8):
            item = process(pid, self.group)
            if item is None: raise RuntimeError('trusted resource owner exited')
            self.excluded[pid] = item['ticks']
            if pid == binding['owner_pid']: break
            pid = int((Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[1])
        else: raise RuntimeError('resource controller is not a bounded child of queue owner')
        if self.excluded[binding['owner_pid']] != binding['owner_ticks']:
            raise RuntimeError('resource queue owner identity differs')

    def sample(self):
        rss = swap = 0; current_members = members(self.group)
        if not set(self.excluded) <= current_members: raise RuntimeError('trusted controller left cgroup')
        for pid in current_members:
            item = process(pid, self.group)
            if item is None:
                if pid in self.excluded: raise RuntimeError('trusted controller exited')
                continue
            if pid in self.excluded and item['ticks'] != self.excluded[pid]:
                raise RuntimeError('trusted controller PID reused')
            rss += item['rss']; swap += item['swap']
        now = time.monotonic(); host = host_sample(); gap = now - self.last
        self.samples += 1; self.peak_rss = max(self.peak_rss, rss); self.peak_swap = max(self.peak_swap, swap)
        self.max_gap = max(self.max_gap, gap)
        reason = violation(host, self.baseline, self.previous, rss, swap, gap)
        self.previous, self.last = host, now
        if reason: raise RuntimeError(reason)

    def _run(self):
        while not self.stop.wait(.1):
            try: self.sample()
            except BaseException as error:
                self.reason = self.reason or str(error)
                if self.worker_active:
                    try: kill_scope(self.group, self.excluded)
                    except BaseException: self.reason += ';cleanup_unproven'

    def start(self):
        self.sample(); self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start()
        return self

    def check(self):
        if self.reason: raise RuntimeError('whole-transaction resources: ' + self.reason)
        if self.thread is not None and not self.thread.is_alive(): raise RuntimeError('resource observer stopped')

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=5)
        if self.thread and self.thread.is_alive(): self.reason = self.reason or 'observer_join_timeout'
        try: self.sample()
        except BaseException as error: self.reason = self.reason or str(error)
        return {'schema': 'ar-local-ci-resources-v1', 'result': 'FAIL' if self.reason else 'PASS',
                'reason': self.reason, 'baseline': self.baseline, 'last_host': self.previous, 'samples': self.samples,
                'peak_rss_bytes': self.peak_rss, 'peak_swap_bytes': self.peak_swap,
                'maximum_sample_gap_seconds': self.max_gap, 'mode': 'sampled_whole_cgroup_rss'}
