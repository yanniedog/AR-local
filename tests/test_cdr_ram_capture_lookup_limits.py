"""Native value limits and unsupported-runtime preservation on disposable data."""
import json
import sqlite3
import tracemalloc
from pathlib import Path

import pytest

import cdr_daily
import cdr_ram_capture_cleanup as cleanup
import cdr_ram_capture_lookup as lookup
from cdr_finalization import verify_completion_marker
from tests.test_cdr_ram_capture_cleanup import (
    DAY, FIXTURE, _seal, completed, requires_lookup_limits, source_generation_clock,
)


def test_missing_native_api_preserves_healthy_stage_without_cleanup_db_open(completed, monkeypatch):
    finalized, capture, options, raw, source, marker, archive = completed
    _seal(completed)
    before = {path: path.read_bytes() for root in (options['state_dir'], archive)
              for path in root.rglob('*') if path.is_file()}
    # Simulated lack of the API on capable runtimes; native3.10 also runs the
    # actual original/retry caller test below without changing capabilities.
    monkeypatch.setattr(lookup, 'sqlite_value_limits_available', lambda: False)
    monkeypatch.setattr(lookup.sqlite3, 'connect', lambda *_args, **_kwargs: pytest.fail('Cleanup DB must not open'))
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert result['status'] == 'PRESERVED' and result['reason'] == lookup.UNSUPPORTED
    assert result['query_steps'] == 0 and source.read_bytes() == FIXTURE.read_bytes() and raw.is_dir()
    assert all(path.read_bytes() == body for path, body in before.items())


@pytest.mark.skipif(lookup.sqlite_value_limits_available(), reason='Exercises genuinely unavailable native value-limit APIs')
@pytest.mark.parametrize('automatic_pi', [False, True])
def test_native_unsupported_original_run_and_finalized_retry_preserve_capture(tmp_path, monkeypatch, automatic_pi, source_generation_clock):
    ram, runs, state, archive = [tmp_path / name for name in ('ram', 'runs', 'state', 'archive')]
    monkeypatch.setenv('AR_LOCAL_TERMS_ROOT', str(archive))
    monkeypatch.setattr(cdr_daily, 'local_date', lambda: DAY)
    monkeypatch.setattr(cdr_daily, 'is_raspberry_pi', lambda: automatic_pi)
    monkeypatch.setattr(cdr_daily, 'ensure_runtime_data_writable', lambda *_: None)
    monkeypatch.setattr(cdr_daily, 'write_sanity_report', lambda *_: None)
    monkeypatch.setattr(cdr_daily, '_emit_day_manifest', lambda *_: None)
    record = json.loads(FIXTURE.read_bytes())['data']
    relative = Path('banks') / 'Mortgage' / record['brand'] / record['name'] / record['productId'] / 'product-detail.json'
    def retained_ingest(script, target, day, extra):
        path = target / day / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(cdr_daily, 'run_ingest', retained_ingest)
    actual_connect = sqlite3.connect
    def admitted_connect(database, *args, **kwargs):
        assert 'mode=ro&immutable=1' not in str(database), 'Unsupported cleanup attempted DB open'
        return actual_connect(database, *args, **kwargs)  # The separate real capture may use its disposable DB.
    monkeypatch.setattr(sqlite3, 'connect', admitted_connect)
    actual_cleanup = cdr_daily.cleanup_captured_ram_stage
    outcomes = []
    def observe_cleanup(finalized, capture, **kwargs):
        assert capture['status'] == 'CAPTURED_AND_QUEUED'
        result = actual_cleanup(finalized, capture, **kwargs)
        outcomes.append(result)
        return result
    monkeypatch.setattr(cdr_daily, 'cleanup_captured_ram_stage', observe_cleanup)
    args = cdr_daily.parse_args(['--date', DAY, '--runs', str(runs), '--state', str(state),
                                '--ram-stage', '--ram-root', str(ram)])
    args.ram_stage = not automatic_pi
    assert cdr_daily.run_once(args) == 1
    marker = state / (DAY + '.done.json')
    marker_bytes = marker.read_bytes()
    assert verify_completion_marker(json.loads(marker_bytes), state, DAY)
    assert (ram / 'runs' / DAY / relative).read_bytes() == FIXTURE.read_bytes()
    capture_bytes = {path: path.read_bytes() for path in (archive / 'captures').glob('*.json')}
    monkeypatch.setattr(cdr_daily, 'run_ingest', lambda *_: pytest.fail('Finalized retry must not reingest'))
    assert cdr_daily.run_once(args) == 0
    assert len(outcomes) == 2
    assert all(item['status'] == 'PRESERVED' and item['reason'] == lookup.UNSUPPORTED for item in outcomes)
    assert marker.read_bytes() == marker_bytes and (ram / 'runs' / DAY / relative).read_bytes() == FIXTURE.read_bytes()
    assert all(path.read_bytes() == body for path, body in capture_bytes.items())


@requires_lookup_limits
def test_native_limits_installed_and_verified_before_first_statement(completed, monkeypatch):
    finalized, capture, *_ = completed
    original = sqlite3.connect
    events = []
    class Observed(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            assert self.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) <= lookup.VALUE_LIMIT
            assert self.getlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH) <= 16384
            assert self.getlimit(sqlite3.SQLITE_LIMIT_COLUMN) <= 128
            assert self.getlimit(sqlite3.SQLITE_LIMIT_VDBE_OP) <= 10000
            events.append(args[0])
            return super().execute(*args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: original(*args, factory=Observed, **kwargs))
    assert cleanup._capture(finalized, capture, cleanup.CleanupBudget())['generation_id'] == finalized['generation_id']
    assert events and events[0] == 'PRAGMA mmap_size=0'


@requires_lookup_limits
def test_ignored_native_limit_is_refused_before_any_statement(completed, monkeypatch):
    finalized, capture, options, raw, source, *_ = completed
    _seal(completed)
    original = sqlite3.connect
    class BrokenLimit(sqlite3.Connection):
        def setlimit(self, *args):
            return 1000000000
        def execute(self, *_args, **_kwargs):
            pytest.fail('Unenforced limit must refuse before any query')
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: original(*args, factory=BrokenLimit, **kwargs))
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert result['status'] == 'PRESERVED' and result['reason'] == 'capture_cleanup_sqlite_value_limits_not_enforced'
    assert source.read_bytes() == FIXTURE.read_bytes() and raw.is_dir()


def test_actual_capture_oversized_malformed_value_never_materialized(completed, tmp_path, monkeypatch, record_property):
    finalized, capture, options, raw, source, _, _ = completed
    alternative = tmp_path / 'malformed-archive'
    (alternative / 'captures').mkdir(parents=True)
    receipt = Path(capture['receipt_path'])
    (alternative / 'captures' / receipt.name).write_bytes(receipt.read_bytes())
    database = alternative / 'evidence.sqlite3'
    # Same indexed shape/application, deliberately absent producer length CHECK.
    # The payload is protocol text, not a bank or real completion record.
    connection = sqlite3.connect(database)
    try:
        connection.executescript('PRAGMA application_id=1095914573; PRAGMA user_version=1; '
            'CREATE TABLE ingest_captures(ingest_id TEXT PRIMARY KEY,receipt_sha256 TEXT NOT NULL,'
            'completed_at TEXT NOT NULL,products INTEGER NOT NULL);')
        connection.execute('INSERT INTO ingest_captures VALUES(?,?,?,?)',
                           (finalized['generation_id'], 'x' * (8 * 1024**2), DAY, 1))
        connection.commit()
    finally:
        connection.close()
    before = database.stat()
    monkeypatch.setenv('AR_LOCAL_TERMS_ROOT', str(alternative))
    budget = cleanup.CleanupBudget(max_bytes=1024**2)
    tracemalloc.start()
    try:
        with pytest.raises((sqlite3.Error, ValueError)) as raised:
            cleanup._capture(finalized, capture, budget)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1024**2  # Python allocation only; no claim of measuring SQLite C heap.
    assert source.read_bytes() == FIXTURE.read_bytes() and raw.is_dir()
    after = database.stat()
    assert (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
    if not lookup.sqlite_value_limits_available():
        assert str(raised.value) == lookup.UNSUPPORTED and budget.query_steps == 0
    record_property('native_limits_available', lookup.sqlite_value_limits_available())
    record_property('peak_python_allocated_bytes', peak)
    record_property('query_steps', budget.query_steps)
