"""Qualify the Nov2 compatibility patch against retained installed source bytes."""
import ast
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import inspect
import json
from pathlib import Path
import signal
import subprocess
import sys
import types

import pytest

from scripts import ingest_notification_snapshot as current

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/observer-compat-20261102'
MANIFEST = json.loads((FIXTURE / 'manifest.json').read_text())
PATCHED_SHA256 = '5cc8123072e241665ecb048f8bb06234e1986638eb07c2239683feb63a63e5ba'
NOW = datetime(2026, 11, 1, 16, 0, 39, 235198, tzinfo=timezone.utc)


def retained(name):
    with gzip.open(FIXTURE / ('installed-' + name + '.py.gz'), 'rb') as stream:
        raw = stream.read(65537)
    assert len(raw) <= 65536
    assert hashlib.sha256(raw).hexdigest() == MANIFEST[name + '_sha256']
    return raw


def observer_function(source):
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == 'remote_snapshot')
    namespace = {'_remote_recovery': lambda *a: {}, '_remote_pending': lambda *a: {},
                 '_remote_failure_counts': lambda *a: {'available': True}}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<retained-observer>', 'exec'), namespace)
    return namespace['remote_snapshot']


def verify_patched_identity(raw, manifest):
    assert manifest['patched_snapshot_sha256'] == PATCHED_SHA256
    assert hashlib.sha256(raw).hexdigest() == PATCHED_SHA256


@pytest.fixture
def patched_source(tmp_path):
    # Apply the actual review artifact, not a separate implementation of its edit.
    target = tmp_path / 'scripts/ingest_notification_snapshot.py'
    target.parent.mkdir()
    target.write_bytes(retained('snapshot'))
    patch = ROOT / 'deploy/windows/ingest-observer-context.patch'
    command = ['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'apply']
    subprocess.run([*command, '--check', str(patch)], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([*command, str(patch)], cwd=tmp_path, check=True, capture_output=True)
    raw = target.read_bytes()
    verify_patched_identity(raw, MANIFEST)
    return raw


@pytest.fixture
def detector(monkeypatch):
    # The retained remote function prepends the live Pi checkout. Restore this
    # process-global path after each test so later tests cannot import old code.
    monkeypatch.setattr(sys, 'path', list(sys.path))
    # Frozen detector from the recorded commit; no fresh live-hash claim.
    module = types.ModuleType('installed_detector_fixture')
    module.__file__ = str(ROOT / 'pi_issue_watchdog.py')
    exec(compile(retained('detector'), '<installed-detector-8590e238>', 'exec'), module.__dict__)
    monkeypatch.setitem(sys.modules, 'pi_issue_watchdog', module)
    monkeypatch.setattr(signal, 'alarm', lambda *a: None, raising=False)
    module.test_now = NOW

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return module.test_now

    import datetime as clocks
    monkeypatch.setattr(clocks, 'datetime', Clock)
    monkeypatch.setattr(module, 'unit_state', lambda _: {
        'ActiveState': 'inactive', 'Result': 'success', 'ExecMainStatus': '0',
        'started_at': module.latest_daily_due_utc(module.test_now) + timedelta(seconds=3)})
    monkeypatch.setattr(module, 'timer_last_trigger', lambda: None)
    monkeypatch.setattr(module, 'completion', lambda *a: 'PARTIAL')
    monkeypatch.setattr(module, 'configured_store', lambda: pytest.fail('No incident store'))
    monkeypatch.setattr(module, 'deliver', lambda *a: pytest.fail('No delivery'))
    return module


def test_retained_identity_matches_observed_old_caller_and_deployed_detector():
    assert hashlib.sha256(retained('snapshot')).hexdigest() == '350423b4af0eaa8998ab33c2e8e015fc0c12f865456cf62ec89f6f3bf3d179d6'
    assert hashlib.sha256(retained('detector')).hexdigest() == '5fad15564e6f0c6b2926b261419fa21ac961cfee62fa45860db51bc5e609d621'
    assert MANIFEST['detector_commit'] == '8590e238d00f093e7f6d20fccfc2377c7abf1aec'


@pytest.mark.parametrize('change', ['manifest_only', 'bytes_only', 'bytes_and_manifest'])
def test_patched_identity_rejects_manifest_or_matching_rebound_bytes(patched_source, change):
    raw = patched_source
    manifest = dict(MANIFEST)
    if change in {'bytes_only', 'bytes_and_manifest'}:
        raw += b'\n# unreviewed mutation\n'
    if change == 'manifest_only':
        manifest['patched_snapshot_sha256'] = '0' * 64
    elif change == 'bytes_and_manifest':
        manifest['patched_snapshot_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(AssertionError):
        verify_patched_identity(raw, manifest)


def test_old_caller_reproduces_swallowed_keyword_error(detector, monkeypatch):
    original = detector.ingest_checks
    failures = []

    def traced(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except TypeError as error:
            failures.append(str(error))
            raise

    monkeypatch.setattr(detector, 'ingest_checks', traced)
    result = observer_function(retained('snapshot'))()
    assert result['ingest'] == {'status': 'CHECK_FAILED', 'date': None}
    assert result['health_facets'] == []
    assert len(failures) == 1 and "unexpected keyword argument 'observation_at'" in failures[0]


@pytest.mark.parametrize('status', ['PARTIAL', 'COMPLETE', 'MISSING', 'INVALID', 'UNVERIFIED_METADATA_LIMIT'])
def test_applied_patch_preserves_detector_outcome(detector, monkeypatch, patched_source, status):
    monkeypatch.setattr(detector, 'completion', lambda *a: status)
    value = observer_function(patched_source)()
    assert value['ingest'] == {'status': status, 'date': '2026-11-02'}
    assert value['health_facets'][-1] == {
        'key': 'ingest:2026-11-02', 'category': 'INGEST_' + status, 'healthy': status == 'COMPLETE'}
    assert 'observation_at' not in json.dumps(value)


@pytest.mark.parametrize('local,status,day', [
    ('2026-11-02T00:59:59+11:00', 'PARTIAL', '2026-11-01'),
    ('2026-11-02T01:29:59+11:00', 'GRACE', '2026-11-02'),
    ('2026-11-02T01:30:00+11:00', 'PARTIAL', '2026-11-02'),
    ('2026-11-02T03:00:39.235198+11:00', 'PARTIAL', '2026-11-02'),
])
def test_patch_keeps_due_date_and_grace_semantics(detector, patched_source, local, status, day):
    detector.test_now = datetime.fromisoformat(local).astimezone(timezone.utc)
    value = observer_function(patched_source)()
    assert value['checked_at'] == detector.test_now.isoformat()
    assert value['ingest'] == {'status': status, 'date': day}


@pytest.mark.parametrize('fault', ['unit_read', 'unknown_detector_error', 'new_unknown_keyword'])
def test_unknown_evidence_never_becomes_success(detector, monkeypatch, patched_source, fault):
    def failure(*a, **kw):
        raise RuntimeError('private diagnostic')
    if fault == 'unit_read':
        monkeypatch.setattr(detector, 'unit_state', failure)
    elif fault == 'unknown_detector_error':
        monkeypatch.setattr(detector, 'ingest_checks', failure)
    else:
        def new_keyword(observer, *a, **kw):
            observer.observe('ingest:2026-11-02', 'title', 'INGEST_PARTIAL', healthy=False, future_context=True)
        monkeypatch.setattr(detector, 'ingest_checks', new_keyword)
    value = observer_function(patched_source)()
    assert value['ingest'] == {'status': 'CHECK_FAILED', 'date': None}
    assert 'private diagnostic' not in json.dumps(value)


def test_current_repository_observer_already_accepts_installed_detector(detector):
    value = observer_function(inspect.getsource(current.remote_snapshot))()
    assert value['ingest'] == {'status': 'PARTIAL', 'date': '2026-11-02'}
