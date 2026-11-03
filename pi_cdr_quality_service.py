"""Read-only host HTTP companion; the quality worker retains PrivateNetwork."""
from __future__ import annotations

import copy
from datetime import date
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import socket
import stat
import threading
import time
import uuid

SCHEMA = 'ar-local-service-companion-v1'
SNAPSHOT_SCHEMA = 'ar-local-service-snapshot-v1'
RECEIPT_SCHEMA = 'ar-local-service-receipt-v1'
PROBE_SECONDS, PAIR_SECONDS, INTERVAL_SECONDS = 15.0, 30.0, 5.0
MAX_AGE_SECONDS, MAX_OBSERVATION_GAP = 37.0, 2.0
BODY_LIMIT, HEADER_LIMIT, FILE_LIMIT = 65536, 16384, 16384
ENDPOINTS = ('nginx', 'dashboard')
PORTS = {'nginx': 80, 'dashboard': 8808}
_monotonic = time.monotonic


def _require(value, reason):
    if not value:
        raise ValueError('service_companion:' + reason)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: _require(False, 'nonfinite_json'))
    _require(isinstance(value, dict), 'object_required')
    return value


def _boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def source_sha256():
    return _sha(Path(__file__).read_bytes())


def _binding(binding, *, live=False):
    _require(isinstance(binding, dict) and set(binding) == {'schema', 'source_sha256', 'source_commit',
        'operation', 'unit', 'boot_id', 'nonce'}, 'binding_fields')
    _require(binding['schema'] == SCHEMA, 'binding_schema')
    for name, length in (('source_sha256', 64), ('source_commit', 40), ('nonce', 64)):
        _require(isinstance(binding[name], str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', binding[name]), 'binding_' + name)
    _require(binding['source_sha256'] == source_sha256(), 'helper_source_changed')
    _require(isinstance(binding['unit'], str) and re.fullmatch(r'[A-Za-z0-9_.@:-]+\.service', binding['unit']), 'binding_unit')
    _require(isinstance(binding['boot_id'], str) and str(uuid.UUID(binding['boot_id'])) == binding['boot_id'], 'binding_boot')
    operation = Path(binding['operation'])
    _require(operation.is_absolute() and operation.resolve() == operation, 'binding_operation')
    if live:
        _require(binding['boot_id'] == _boot_id(), 'live_boot_changed')
    return _sha(_canonical(binding))


def _directory(directory, binding=None):
    directory = Path(directory)
    _require(directory.is_absolute() and directory.resolve() == directory, 'directory_noncanonical')
    _require(not any(p.is_symlink() for p in (directory, *directory.parents)), 'directory_symlink')
    info = directory.lstat()
    _require(stat.S_ISDIR(info.st_mode), 'directory_type')
    if binding is not None:
        _require(directory == Path(binding['operation']) / 'pressure', 'directory_binding')
    return info.st_dev, info.st_ino


def _identity(info):
    return tuple(getattr(info, k) for k in ('st_dev', 'st_ino', 'st_mode', 'st_nlink',
        'st_uid', 'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def _read(directory, name):
    original_dir = _directory(directory)
    path = directory / name
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= FILE_LIMIT, 'file_type_or_size')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size <= FILE_LIMIT, 'opened_file_type')
        if name != 'snapshot.json':
            _require(_identity(before)[:-1] == _identity(opened)[:-1], 'file_replaced_before_read')
        raw = stream.read(FILE_LIMIT + 1)
        after = os.fstat(stream.fileno())
    final = path.lstat()
    _require(len(raw) == opened.st_size, 'file_read_size')
    if name == 'snapshot.json':
        _atomic_snapshot_identity(opened, after, final)
    else:
        _require(_identity(opened) == _identity(after) and _identity(final) == _identity(before), 'binding_changed_during_read')
    _require(_directory(directory) == original_dir, 'directory_replaced')
    value = _json(raw)
    _require(_canonical(value) == raw, 'file_not_canonical')
    return value, _sha(raw)


def _atomic_snapshot_identity(opened, after, final):
    _require(stat.S_ISREG(final.st_mode) and final.st_nlink == 1 and final.st_size <= FILE_LIMIT, 'snapshot_path_type')
    stable = ('st_dev','st_ino','st_mode','st_uid','st_gid','st_size','st_mtime_ns')
    _require(all(getattr(opened,k) == getattr(after,k) for k in stable), 'snapshot_mutated_during_read')
    if after.st_nlink == 0:
        _require((final.st_dev,final.st_ino) != (opened.st_dev,opened.st_ino), 'snapshot_unlinked_without_replacement')
    else:
        _require(after.st_nlink == 1 and after.st_ctime_ns == opened.st_ctime_ns, 'snapshot_link_or_ctime_changed')


def read_binding(directory):
    directory = Path(directory)
    binding, digest = _read(directory, 'binding.json')
    _require(_binding(binding) == digest, 'binding_digest')
    _directory(directory, binding)
    return binding, digest


def _write(directory, name, value, *, replace=False):
    anchor = _directory(directory)
    raw = _canonical(value)
    _require(len(raw) <= FILE_LIMIT, 'write_bound')
    final = directory / name
    if replace and final.exists():
        old = final.lstat()
        _require(stat.S_ISREG(old.st_mode) and old.st_nlink == 1, 'replace_target_type')
    temporary = directory / (name + '.' + uuid.uuid4().hex + '.tmp') if replace else final
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
                 | getattr(os, 'O_BINARY', 0), 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    # The worker's ReadOnlyPaths mount is the snapshot write boundary. Keep
    # replacement snapshots owner-writable for Windows control-test parity.
    os.chmod(temporary, 0o600 if replace else 0o400)
    _require(_directory(directory) == anchor, 'write_directory_replaced')
    if replace:
        # Binding is never replaced. The parent owns this fresh private directory.
        os.replace(temporary, final)


def _wait(sock, *, write, deadline):
    remaining = deadline - _monotonic()
    _require(remaining > 0, 'http_deadline')
    ready = select.select([] if write else [sock], [sock] if write else [], [sock], remaining)
    _require(not ready[2] and (ready[1] if write else ready[0]), 'http_deadline_or_socket')
    _require(_monotonic() <= deadline, 'http_deadline')


def _body(wire, *, eof=False):
    """Bounded HTTP/1.x parser; never follows redirects or accepts encoding."""
    position = wire.find(b'\r\n\r\n')
    if position < 0:
        _require(len(wire) <= HEADER_LIMIT and not eof, 'http_headers')
        return None
    _require(position <= HEADER_LIMIT, 'http_header_bound')
    lines = wire[:position].split(b'\r\n')
    _require(re.fullmatch(rb'HTTP/1\.[01] 200(?: [^\r\n]*)?', lines[0]), 'http_status')
    headers = {}
    for line in lines[1:]:
        _require(b':' in line and not line.startswith((b' ', b'\t')), 'http_header')
        key, value = line.split(b':', 1); key, value = key.lower(), value.strip().lower()
        _require(re.fullmatch(rb'[a-z0-9!#$%&\x27*+.^_`|~-]+', key), 'http_header_name')
        _require(key not in headers or key not in (b'content-length', b'transfer-encoding', b'content-encoding'), 'http_header_duplicate')
        headers[key] = value
    _require(headers.get(b'content-encoding', b'identity') == b'identity', 'http_content_encoding')
    body = wire[position + 4:]
    if b'transfer-encoding' in headers:
        _require(headers[b'transfer-encoding'] == b'chunked' and b'content-length' not in headers, 'http_transfer_encoding')
        return _unchunk(body, eof=eof)
    if b'content-length' in headers:
        value = headers[b'content-length']
        _require(re.fullmatch(rb'[0-9]{1,6}', value), 'http_content_length')
        length = int(value)
        _require(length <= BODY_LIMIT and len(body) <= length, 'http_body_bound')
        _require(not eof or len(body) == length, 'http_truncated')
        return body if len(body) == length else None
    _require(len(body) <= BODY_LIMIT, 'http_body_bound')
    return body if eof else None


def _unchunk(body, *, eof):
    output = bytearray(); offset = 0
    while True:
        end = body.find(b'\r\n', offset)
        if end < 0:
            _require(not eof and len(body) - offset <= 16, 'http_chunk_header')
            return None
        _require(re.fullmatch(rb'[0-9a-fA-F]{1,8}', body[offset:end]), 'http_chunk_size')
        size = int(body[offset:end], 16); offset = end + 2
        _require(len(output) + size <= BODY_LIMIT, 'http_body_bound')
        if len(body) < offset + size + 2:
            _require(not eof, 'http_chunk_truncated'); return None
        _require(body[offset + size:offset + size + 2] == b'\r\n', 'http_chunk_terminator')
        output.extend(body[offset:offset + size]); offset += size + 2
        if size == 0:
            _require(offset == len(body), 'http_chunk_trailer')
            return bytes(output)


def _http(endpoint, deadline):
    port = PORTS[endpoint]
    host = 'localhost' + (':8808' if port == 8808 else '')
    request = ('GET /api/latest HTTP/1.1\r\nHost: ' + host + '\r\nConnection: close\r\n'
               'Accept: application/json\r\nAccept-Encoding: identity\r\n\r\n').encode()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setblocking(False)
        connected = sock.connect_ex(('127.0.0.1', port))
        _require(connected in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035), 'http_connect')
        _wait(sock, write=True, deadline=deadline)
        _require(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0, 'http_connect')
        offset = 0
        while offset < len(request):
            _wait(sock, write=True, deadline=deadline)
            try: sent = sock.send(request[offset:])
            except BlockingIOError: continue
            _require(sent > 0, 'http_send'); offset += sent
        wire = bytearray()
        while True:
            _wait(sock, write=False, deadline=deadline)
            try: part = sock.recv(4096)
            except BlockingIOError: continue
            wire.extend(part)
            _require(len(wire) <= HEADER_LIMIT + BODY_LIMIT + 16384, 'http_wire_bound')
            body = _body(bytes(wire), eof=not part)
            if body is not None:
                _require(_monotonic() <= deadline, 'http_deadline')
                return body


def _probe(endpoint, deadline):
    body = _http(endpoint, deadline)
    _require(len(body) <= BODY_LIMIT, 'body_bound')
    manifest = _json(body)
    counts = manifest.get('banks_counts')
    if not isinstance(counts, dict): counts = manifest.get('banks', {})
    rates = counts.get('rates') if isinstance(counts, dict) else None
    # Preserve the operational count shape, but refuse bools/fractional coercion.
    if isinstance(rates, str) and re.fullmatch('[0-9]{1,12}', rates): rates = int(rates)
    _require(type(rates) is int and 0 < rates <= 10**12, 'manifest_rates')
    day = manifest.get('run_date')
    _require(isinstance(day, str) and date.fromisoformat(day).isoformat() == day, 'manifest_date')
    return {'http_status': 200, 'run_date': day, 'rate_count': rates}


SNAPSHOT_FIELDS = {'schema', 'binding_sha256', 'seq', 'started_monotonic', 'finished_monotonic',
    'initial_pass_finished_monotonic', 'probe_count', 'failed_probe_count', 'failure_latched',
    'max_latency_s', 'max_round_gap_s', 'max_pair_duration_s', 'probes'}


def _snapshot(value, binding_sha, previous, now):
    _require(isinstance(value, dict) and set(value) == SNAPSHOT_FIELDS, 'snapshot_fields')
    _require(value['schema'] == SNAPSHOT_SCHEMA and value['binding_sha256'] == binding_sha, 'snapshot_binding')
    for key in ('started_monotonic','finished_monotonic','initial_pass_finished_monotonic',
                'max_latency_s','max_round_gap_s','max_pair_duration_s'):
        _require(_number(value[key]), 'snapshot_number')
    _require(_number(now) and 0 < value['initial_pass_finished_monotonic'] <= value['finished_monotonic'] <= now,
             'snapshot_future_or_initial')
    _require(value['started_monotonic'] <= value['finished_monotonic'] and now - value['finished_monotonic'] <= MAX_AGE_SECONDS,
             'snapshot_stale_or_order')
    _require(type(value['seq']) is int and value['seq'] >= 1 and type(value['probe_count']) is int
             and value['probe_count'] == 2 * value['seq'], 'snapshot_sequence_count')
    if value['seq'] == 1:
        _require(value['initial_pass_finished_monotonic'] == value['finished_monotonic']
                 and value['max_round_gap_s'] == 0, 'first_pass_binding')
    else:
        _require(value['initial_pass_finished_monotonic'] <= value['started_monotonic'], 'initial_pass_order')
        _require((value['started_monotonic'] - value['initial_pass_finished_monotonic']) / (value['seq'] - 1)
                 <= value['max_round_gap_s'], 'cumulative_round_gap_underreported')
    _require(type(value['failed_probe_count']) is int and 0 <= value['failed_probe_count'] <= value['probe_count']
             and type(value['failure_latched']) is bool
             and value['failure_latched'] == (value['failed_probe_count'] > 0), 'snapshot_latch')
    probes = value['probes']
    _require(isinstance(probes, list) and len(probes) == 2, 'snapshot_probe_count')
    for expected, probe in zip(ENDPOINTS, probes):
        _require(isinstance(probe, dict) and set(probe) == {'endpoint','status','http_status','run_date','rate_count','latency_s'}, 'probe_fields')
        _require(probe['endpoint'] == expected and probe['status'] in ('PASS','FAIL') and _number(probe['latency_s']), 'probe_identity')
        if probe['status'] == 'PASS':
            _require(type(probe['http_status']) is int and probe['http_status'] == 200
                     and type(probe['rate_count']) is int and 0 < probe['rate_count'] <= 10**12, 'probe_count_status')
            _require(isinstance(probe['run_date'], str) and date.fromisoformat(probe['run_date']).isoformat() == probe['run_date'], 'probe_date')
    _require(value['failed_probe_count'] >= sum(p['status'] == 'FAIL' for p in probes), 'probe_failure_count')
    _require(max(p['latency_s'] for p in probes) <= value['max_latency_s'] <= PROBE_SECONDS, 'probe_latency')
    _require(value['finished_monotonic'] - value['started_monotonic'] <= value['max_pair_duration_s'] <= PAIR_SECONDS, 'pair_duration')
    _require(value['max_round_gap_s'] <= MAX_AGE_SECONDS, 'round_gap')
    if previous is not None:
        _require(value['seq'] >= previous['seq'], 'sequence_reset')
        if value['seq'] == previous['seq']:
            _require(_canonical(value) == _canonical(previous), 'same_sequence_changed')
        else:
            _require(value['initial_pass_finished_monotonic'] == previous['initial_pass_finished_monotonic']
                     and value['started_monotonic'] >= previous['finished_monotonic'], 'sequence_time_reset')
            for key in ('failed_probe_count','max_latency_s','max_round_gap_s','max_pair_duration_s'):
                _require(value[key] >= previous[key], 'cumulative_reset')
            if value['seq'] == previous['seq'] + 1:
                _require(value['max_round_gap_s'] >= value['started_monotonic'] - previous['started_monotonic'], 'round_gap_underreported')
    _require(not value['failure_latched'], 'failure_latched')
    return value


def read_service_snapshot(directory, binding, previous, now=None):
    expected = _binding(binding, live=True)
    actual, digest = read_binding(directory)
    _require(actual == binding and digest == expected, 'binding_changed')
    value, _ = _read(Path(directory), 'snapshot.json')
    if now is None: now = _monotonic()
    return _snapshot(value, expected, previous, now)


class ServiceCompanion:
    def __init__(self, directory, binding):
        self.directory, self.binding = Path(directory), copy.deepcopy(binding)
        self.binding_sha256 = _binding(self.binding, live=True)
        self._stop, self._ready = threading.Event(), threading.Event()
        self._thread = None; self._fatal = None; self._last = None

    def _round(self):
        start = _monotonic(); deadline = start + PAIR_SECONDS; probes = []
        for endpoint in ENDPOINTS:
            began = _monotonic()
            probe = {'endpoint':endpoint,'status':'FAIL','http_status':None,'run_date':None,'rate_count':None}
            try:
                probe.update(_probe(endpoint, min(deadline, began + PROBE_SECONDS)))
                probe['status'] = 'PASS'
            except Exception:
                pass  # Never persist URLs, exception strings or response bodies.
            probe['latency_s'] = _monotonic() - began
            if probe['latency_s'] > PROBE_SECONDS: probe['status'] = 'FAIL'
            probes.append(probe)
        finish = _monotonic(); previous = self._last
        if finish - start > PAIR_SECONDS: probes[-1]['status'] = 'FAIL'
        failed = sum(p['status'] == 'FAIL' for p in probes) + (previous['failed_probe_count'] if previous else 0)
        value = {'schema':SNAPSHOT_SCHEMA,'binding_sha256':self.binding_sha256,
            'seq': previous['seq'] + 1 if previous else 1, 'started_monotonic':start,'finished_monotonic':finish,
            'initial_pass_finished_monotonic':previous['initial_pass_finished_monotonic'] if previous else (finish if not failed else 0),
            'failed_probe_count':failed,'failure_latched':failed > 0,'probes':probes,
            'max_latency_s':max([p['latency_s'] for p in probes] + [previous['max_latency_s'] if previous else 0]),
            'max_pair_duration_s':max(finish-start, previous['max_pair_duration_s'] if previous else 0),
            'max_round_gap_s':max(start-previous['started_monotonic'], previous['max_round_gap_s']) if previous else 0}
        value['probe_count'] = 2 * value['seq']
        _require(_binding(self.binding, live=True) == self.binding_sha256, 'companion_identity_changed')
        actual, digest = read_binding(self.directory)
        _require(actual == self.binding and digest == self.binding_sha256, 'companion_binding_changed')
        _write(self.directory, 'snapshot.json', value, replace=True)
        self._last = value

    def _run(self):
        try:
            while not self._stop.is_set():
                self._round(); self._ready.set()
                if self._stop.wait(INTERVAL_SECONDS): break
        except BaseException as error:
            self._fatal = type(error).__name__; self._ready.set()

    def _finish(self, timeout=31.0):
        self._stop.set()
        _require(_number(timeout) and timeout <= 31.0, 'cleanup_timeout')
        if self._thread is not None: self._thread.join(timeout=timeout)
        _require(self._thread is None or not self._thread.is_alive(), 'thread_did_not_terminate')
        _require(self._fatal is None, 'thread_failed')

    def __enter__(self):
        startup_deadline = _monotonic() + 32.0
        operation = Path(self.binding['operation'])
        _require(operation.is_dir() and self.directory == operation/'pressure', 'context_directory')
        _require(not any(p.is_symlink() for p in (self.directory, *self.directory.parents)), 'context_symlink')
        self.directory.mkdir(mode=0o700, exist_ok=False)
        _write(self.directory, 'binding.json', self.binding)
        self._thread = threading.Thread(target=self._run, name='ar-local-service-companion', daemon=True)
        self._thread.start()
        try:
            _require(self._ready.wait(timeout=max(0., startup_deadline - _monotonic()))
                     and self._fatal is None, 'startup_failed_or_timeout')
            read_service_snapshot(self.directory, self.binding, None, None)
            _require(_monotonic() <= startup_deadline, 'startup_deadline')
        except BaseException:
            self._finish(timeout=min(31., max(0., startup_deadline - _monotonic()))); raise
        return self

    def __exit__(self, kind, value, traceback):
        self._finish()
        read_service_snapshot(self.directory, self.binding, None, None)
        return False


def require_service_receipt(summary, binding, *, started_monotonic=None, finished_monotonic=None):
    keys = {'schema','binding','binding_sha256','initial_snapshot','last_snapshot','observations','max_age_s',
            'max_observation_gap_s','window_started_monotonic','window_finished_monotonic',
            'first_observed_monotonic','last_observed_monotonic'}
    _require(isinstance(summary, dict) and set(summary) == keys and summary['schema'] == RECEIPT_SCHEMA, 'receipt_schema')
    digest = _binding(binding)
    _require(summary['binding'] == binding and summary['binding_sha256'] == digest, 'receipt_binding')
    for key in keys - {'schema','binding','binding_sha256','initial_snapshot','last_snapshot','observations'}:
        _require(_number(summary[key]), 'receipt_number')
    start, end = summary['window_started_monotonic'], summary['window_finished_monotonic']
    first, last = summary['first_observed_monotonic'], summary['last_observed_monotonic']
    # Host pressure is sampled first; service validation completes afterwards.
    # Preserve actual timestamps and bound that lag at both window edges.
    _require(start <= end and first <= last and start <= first <= start + MAX_OBSERVATION_GAP
             and end <= last <= end + MAX_OBSERVATION_GAP, 'receipt_window_coverage')
    _require((started_monotonic is None or start == started_monotonic)
             and (finished_monotonic is None or end == finished_monotonic), 'receipt_window_binding')
    _require(type(summary['observations']) is int and summary['observations'] >= 2, 'receipt_observations')
    _require(summary['max_observation_gap_s'] <= MAX_OBSERVATION_GAP
             and (last-first)/(summary['observations']-1) <= summary['max_observation_gap_s'], 'receipt_observation_gap')
    initial = _snapshot(summary['initial_snapshot'], digest, None, first)
    final = _snapshot(summary['last_snapshot'], digest, initial, last)
    _require(initial['initial_pass_finished_monotonic'] <= start, 'receipt_initial_pass_after_start')
    _require(max(first-initial['finished_monotonic'], last-final['finished_monotonic']) <= summary['max_age_s'] <= MAX_AGE_SECONDS,
             'receipt_sample_age')
    _require(end-final['finished_monotonic'] <= MAX_AGE_SECONDS, 'receipt_end_sample_stale')
    return summary
