"""Single inline phase accounting; no fresh budget on retry or child creation."""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

MIB = 1024**2
CONTROL = 16 * MIB
LIMITS = {'verified_read': 3 * 1024**3 - CONTROL, 'compressed': 64 * MIB,
          'decoded': 202797370, 'metadata': MIB, 'headers': 1024,
          'output': 512 * MIB - CONTROL}
_METER = ContextVar('historical_fee_inline_meter', default=None)


def integer(value):
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ValueError('nonnegative_exact_counter_required')
    return value


def account_exact(kind, amount):
    meter = _METER.get()
    if meter is not None:
        meter.exact(kind, amount)


def read_exact_work(stream, amount):
    meter = _METER.get()
    return stream.read(amount) if meter is None else meter.read(stream, amount, 'verified_read')


@contextmanager
def exact_meter(meter):
    # ContextVar isolates independent threads/tasks; inherited contexts may not
    # start another phase or silently replace the parent's meter.
    if _METER.get() is not None:
        raise ValueError('nested_historical_meter_refused')
    token = _METER.set(meter)
    try:
        yield
    finally:
        _METER.reset(token)


class PhaseBudget:
    """The ledger reserves all limits before constructing this inline reader.

    A failed read conservatively keeps its maximum charge. Successful short
    reads refund only that read's unused bytes. No counter uses a live receipt
    alias. Native blocked I/O and peak RSS require the separate outer supervisor.
    """
    def __init__(self, *, deadline):
        self.started = time.monotonic()
        self.deadline = min(deadline, self.started + 600)
        self.counts = {}
        self.limits = dict(LIMITS)
        self.owner = __import__('threading').get_ident()
        self.closed = False
        self.directories = {}

    def guard_directories(self, paths):
        from cdr_historical_fee_archive import safe_path
        for path in paths:
            info = safe_path(path, directory=True).stat()
            if not info.st_ino:
                raise ValueError('directory_identity_unavailable')
            self.directories[str(path)] = (info.st_dev, info.st_ino)

    def claim_directory(self, path):
        self.check()
        path.mkdir()
        self.guard_directories((path,))
        self.check()

    def check(self, kind=None, amount=0):
        if self.closed or __import__('threading').get_ident() != self.owner:
            raise ValueError('inline_budget_owner_or_lifetime_mismatch')
        if time.monotonic() >= self.deadline:
            raise ValueError('archive_deadline_exceeded')
        if self.directories:
            from cdr_historical_fee_archive import safe_path
            for path, expected in self.directories.items():
                info = safe_path(path, directory=True).stat()
                if (info.st_dev, info.st_ino) != expected:
                    raise ValueError('admitted_directory_identity_changed')
        if kind is not None:
            integer(amount)
            if kind not in self.limits:
                raise ValueError('unknown_budget_category')
            total = self.counts.get(kind, 0) + amount
            if total > self.limits[kind]:
                raise ValueError('archive_' + kind + '_bound_exceeded')
            self.counts[kind] = total

    def _read_charge(self, kind, amount):
        self.check()
        keys = ('verified_read',) if kind == 'verified_read' else ('verified_read', kind)
        for key in keys:
            if self.counts.get(key, 0) + amount > self.limits[key]:
                raise ValueError('archive_' + key + '_bound_exceeded')
        for key in keys:
            self.check(key, amount)
        return keys

    def read(self, stream, amount, kind):
        integer(amount)
        keys = self._read_charge(kind, amount)
        body = stream.read(amount)
        if not isinstance(body, bytes) or len(body) > amount:
            raise ValueError('invalid_reader_reply')
        self.check()
        for key in keys:
            self.counts[key] -= amount - len(body)
        return body

    def exact(self, kind, amount):
        # sha() calls account once before hashing its resident buffer. gzip
        # decoded bytes count separately from their compressed input read.
        if kind not in ('checksum', 'gzip_decoded'):
            raise ValueError('unknown_exact_work')
        self.check('verified_read', integer(amount))

    def snapshot(self):
        self.check()
        return dict(self.counts)


class ControlBudget:
    """Fully precharged inside both total work and created-output allowances.

    All code, approval, schema, index, record, head and receipt work uses this
    same concrete meter. It never invokes the scoped financial hash hook.
    """
    def __init__(self, *, deadline):
        self.deadline = deadline
        self.counts = {'read_checksum': 0, 'output': 0}
        self.reads = {}
        self.completed_reads = {}
        self.owner = __import__('threading').get_ident()

    def check(self):
        if self.owner != __import__('threading').get_ident():
            raise ValueError('control_owner_mismatch')
        if time.monotonic() >= self.deadline:
            raise ValueError('control_deadline_exceeded')

    def charge(self, kind, amount):
        self.check()
        if kind not in self.counts:
            raise ValueError('unknown_control_category')
        total = self.counts[kind] + integer(amount)
        if total > CONTROL:
            raise ValueError('control_' + kind + '_bound_exceeded')
        self.counts[kind] = total

    def admit_read(self, name, amount):
        if self.reads.get(name, 0) >= 2:
            raise ValueError('control_record_reread_bound')
        self.charge('read_checksum', amount)
        self.reads[name] = self.reads.get(name, 0) + 1

    def note_completed_read(self, name, file_identity, size):
        """Bind a successful already-admitted read; never charge/refund a new one.

        A trusted bootstrap bridge may transfer its measured debits/read counts
        first, then its successful handle identities. Failed reservations remain
        charged and must not be registered as completed reads.
        """
        self.check()
        count = self.reads.get(name, 0)
        previous = self.completed_reads.get(name)
        if (type(name) is not str or type(size) is not int or size < 0
                or type(file_identity) is not tuple or len(file_identity) != 4
                or any(type(value) is not int or value < 0 for value in file_identity)
                or file_identity[2] != size
                or type(count) is not int or count not in (1, 2)
                or previous is not None and previous[0] >= count
                or self.counts['read_checksum'] < size):
            raise ValueError('successful_metered_read_identity_required')
        self.completed_reads[name] = (count, file_identity, size)
