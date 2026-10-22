"""Native filesystem/SQLite controls and retained real exports; no invented rate rows."""
from contextlib import closing
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

import ar_local_restore_io as io
import ar_local_restore_verification as restore
import cdr_ledger_v2 as ledger
import cdr_quality_sqlite as views
import cdr_sqlite_budget as budget
import pi_backup_foundation as backup
import laptop_backup_daily_verify as daily
import cdr_observation as observation
import cdr_attempt_evidence_promotion as promotion
import cdr_raw_attempt_journal as raw_journal
import cdr_journal_evidence as journal_evidence
from tests.test_ar_local_restore_integrity import _write_current_finalized
from tests.test_restore_deadline_and_links import _control_database, _snapshot
from tests.test_pi_backup_foundation import make_policy


@pytest.mark.parametrize('suffix', ['', '-wal', '-shm', '-journal'])
def test_actual_transient_link_swap_at_open_cannot_attest_other_input(tmp_path, monkeypatch, suffix):
    database = tmp_path / 'source.sqlite'
    _control_database(database)
    source = Path(str(database) + suffix)
    if suffix:
        source.write_bytes(b'journal transport control')
    other, saved = tmp_path / 'other', tmp_path / 'saved'
    other.write_bytes(source.read_bytes())
    link_probe = tmp_path / 'probe'
    try:
        link_probe.symlink_to(other)
    except OSError as exc:
        pytest.skip(f'Native symlinks unavailable: {exc}')
    link_probe.unlink()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    opened, swapped = io.os.open, []
    def swap(path, flags, *args, **kwargs):
        if Path(path) == source:
            source.rename(saved)
            source.symlink_to(other)
            swapped.append(True)
            try:
                return opened(path, flags, *args, **kwargs)
            finally:
                source.unlink()
                saved.rename(source)
        return opened(path, flags, *args, **kwargs)
    monkeypatch.setattr(io.os, 'open', swap)
    monkeypatch.setattr(views.sqlite3, 'connect', lambda *_a, **_k: pytest.fail('swapped input reached SQLite'))
    with pytest.raises((ValueError, OSError)) as failure:
        with views.database_view(database):
            pytest.fail('transient linked input accepted')
    assert swapped == [True], repr(failure.value)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_opened_regular_inode_must_equal_inventoried_source(tmp_path, monkeypatch):
    source, other = tmp_path / 'source', tmp_path / 'other'
    source.write_bytes(b'retained')
    other.write_bytes(b'changed!')
    original = io.os.open
    handles = []
    def redirect(path, flags):
        descriptor = original(other if Path(path) == source else path, flags)
        handles.append(descriptor)
        return descriptor
    monkeypatch.setattr(io.os, 'open', redirect)
    with pytest.raises(ValueError, match='changed while opening'):
        io.hash_file(source)
    with pytest.raises(OSError):
        os.fstat(handles[0])
    assert source.read_bytes() == b'retained'
    assert other.read_bytes() == b'changed!'


def test_sqlite_uses_private_copy_and_original_descriptor_identity_through_use(tmp_path, monkeypatch):
    source = tmp_path / 'source.sqlite'
    _control_database(source)
    before = source.read_bytes()
    connections = []
    original = sqlite3.connect
    def connect(path, *args, **kwargs):
        connections.append(Path(path))
        assert Path(path) != source
        return original(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    with views.database_view(source) as (connection, receipt):
        assert connection.execute('SELECT count(*) FROM evidence').fetchone()[0] == 5000
        assert receipt['source_sha256'] == hashlib.sha256(before).hexdigest()
        assert receipt['journal_mode'] == 'no_retained_journal'
    assert connections and all(not p.exists() for p in connections)
    assert source.read_bytes() == before


def test_canonical_secondary_connections_and_hashes_use_the_same_pinned_copy(tmp_path, monkeypatch):
    _write_current_finalized(tmp_path)
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    connections = []
    original = sqlite3.connect
    def connect(path, *args, **kwargs):
        text = str(path)
        assert 'cdr-audit-sqlite-' in text, text
        connections.append(text)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    report = restore.verify_restored_state(tmp_path)
    assert report['ok'], report['findings']
    assert len(connections) >= 2
    assert {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_unbound_canonical_path_cannot_escape_active_pinned_copy_scope(tmp_path):
    source, private, unrelated = (tmp_path / name for name in ['source', 'private', 'unrelated'])
    with io.database_copy(source, private):
        assert io.database_path(source) == private
        with pytest.raises(ValueError, match='not pinned'):
            io.database_path(unrelated)
    assert io.database_path(unrelated) == unrelated


@pytest.mark.parametrize('operation', ['hash', 'copy', 'json', 'legacy_hash', 'legacy_json', 'promoted_hash'])
def test_actual_payload_chunks_observe_shared_deadline(tmp_path, monkeypatch, operation):
    source, target = tmp_path / 'source', tmp_path / 'copy'
    source.write_bytes(b'"' + b'x' * (2 * io.CHUNK_BYTES) + b'"')
    original = io.chunks
    clock, consumed = [0.0], []
    monkeypatch.setattr(budget.time, 'monotonic', lambda: clock[0])
    def observed(stream, size):
        for block in original(stream, size):
            consumed.append(len(block))
            yield block
            clock[0] = 11.0
    monkeypatch.setattr(io, 'chunks', observed)
    with pytest.raises(TimeoutError):
        with budget.audit_budget(10.0):
            if operation == 'hash':
                io.hash_file(source)
            elif operation == 'copy':
                io.copy_file(source, target)
            elif operation == 'legacy_hash':
                daily._sha256_file(source)
            elif operation == 'legacy_json':
                daily._read_json(source)
            elif operation == 'promoted_hash':
                promotion._hash_file(source)
            else:
                io.read_json(source)
    assert consumed == [io.CHUNK_BYTES]
    assert source.stat().st_size == 2 * io.CHUNK_BYTES + 2
    assert not target.exists() or target.stat().st_size == io.CHUNK_BYTES


def test_canonical_sidecar_timeout_propagates_without_becoming_unreadable(tmp_path, monkeypatch):
    _write_current_finalized(tmp_path)
    exports = next((tmp_path/'runs').glob('*/_exports'))
    clock, reads = [0.0], []
    original = io.chunks
    monkeypatch.setattr(budget.time, 'monotonic', lambda: clock[0])
    def consumed(stream, size):
        for block in original(stream, size):
            reads.append(len(block))
            yield block
            clock[0] = 11.0
    monkeypatch.setattr(io, 'chunks', consumed)
    with pytest.raises(TimeoutError):
        with budget.audit_budget(10.0):
            observation.load_verified_observation(exports)
    assert len(reads) == 1


@pytest.mark.parametrize('phase', ['inventory_hash', 'raw_body', 'semantic_body', 'semantic_detail', 'promotion_summary'])
def test_real_promoted_journal_inner_deadline_is_never_downgraded_to_partial_evidence(tmp_path, monkeypatch, phase):
    exports = _write_current_finalized(tmp_path)
    status = json.loads((exports/'ingest-status.json').read_text())
    pointer = status['raw_attempt_journal']
    journal = promotion.verify_promoted_attempt_evidence(exports, pointer)
    accounting = json.loads((exports/'product-accounting-v1.json').read_text())
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    clock, calls = [0.0], []
    monkeypatch.setattr(budget.time, 'monotonic', lambda: clock[0])
    if phase == 'inventory_hash':
        owner, name = promotion, 'restore_hash_file'
    elif phase == 'raw_body':
        owner, name = raw_journal, 'optional_read_bytes'
    elif phase in {'semantic_body', 'semantic_detail'}:
        owner, name = journal_evidence, 'optional_read_bytes'
    else:
        owner, name = raw_journal.RawAttemptJournal, 'summary'
    original = getattr(owner, name)
    def completed(*args, **kwargs):
        value = original(*args, **kwargs)
        calls.append(True)
        clock[0] = 11.0
        return value
    monkeypatch.setattr(owner, name, completed)
    with pytest.raises(TimeoutError):
        with budget.audit_budget(10.0):
            if phase == 'raw_body':
                journal.summary(recover=False)
            elif phase == 'semantic_body':
                journal_evidence.validate_journal_evidence(accounting, status['provider_states'], journal)
            elif phase == 'semantic_detail':
                journal_evidence.journal_product_evidence(journal)
            else:
                promotion.verify_promoted_attempt_evidence(exports, pointer)
    assert calls == [True]
    assert {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('timed', [False, True])
def test_daily_canonical_hash_reuses_bound_private_database(tmp_path, monkeypatch, timed):
    source = tmp_path/'local-cdr.sqlite'
    _control_database(source)
    original = daily.restore_hash_file
    paths = []
    def hashed(path):
        paths.append(path)
        assert path != source
        return original(path)
    monkeypatch.setattr(daily, 'restore_hash_file', hashed)
    timer = budget.audit_budget(budget.time.monotonic() + 30) if timed else nullcontext()
    with timer, views.database_view(source):
        assert daily._sha256_file(source) == hashlib.sha256(source.read_bytes()).hexdigest()
    assert len(paths) == 1


def _retained_journal_control(source, style):
    companion = Path(str(source) + ('-wal' if style == 'wal' else '-journal'))
    with closing(sqlite3.connect(source)) as writer:
        if style == 'wal':
            writer.execute('CREATE TABLE evidence(value INTEGER)')
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('INSERT INTO evidence VALUES (1)')
            writer.commit()
        else:
            writer.execute('CREATE TABLE evidence(value BLOB)')
            writer.executemany('INSERT INTO evidence VALUES (?)', [(b'a'*1024,)]*100)
            writer.commit()
            writer.execute('PRAGMA cache_size=1')
            writer.execute('UPDATE evidence SET value=zeroblob(1024)')
        retained = {p:p.read_bytes() for p in (source, companion)}
    for path, body in retained.items():
        path.write_bytes(body)
    return retained


@pytest.mark.parametrize('timed', [False, True])
@pytest.mark.parametrize('style', ['wal', 'hot_rollback'])
def test_recovered_view_hash_is_distinct_from_unchanged_source_evidence(tmp_path, timed, style):
    source = tmp_path/'local-cdr.sqlite'
    retained = _retained_journal_control(source, style)
    raw = {p.name:hashlib.sha256(body).hexdigest() for p,body in retained.items()}
    timer = budget.audit_budget(budget.time.monotonic()+30) if timed else nullcontext()
    with timer, restore._restore_database_view(source) as (connection, snapshot):
        expected = 1 if style == 'wal' else b'a'*1024
        assert connection.execute('SELECT value FROM evidence LIMIT 1').fetchone()[0] == expected
        if style == 'wal':
            # Checkpoint ONLY the owned private copy to make the recovered byte
            # view explicit; the retained main/WAL pair must stay unchanged.
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
        view_hash = daily._sha256_file(source)
        assert view_hash != raw[source.name]
        assert view_hash == io.hash_file(io.database_path(source))
        assert snapshot['source_sha256'] == raw[source.name]
        assert snapshot['source_files'] == raw
        assert snapshot['recovery_policy'] == 'sqlite_native_committed_view'
    assert {p:p.read_bytes() for p in retained} == retained


@pytest.mark.parametrize('timed', [False, True])
def test_valid_wal_view_cannot_supply_canonical_sidecar_free_acceptance(tmp_path, timed):
    exports = _write_current_finalized(tmp_path)
    source = exports/'local-cdr.sqlite'
    wal = Path(str(source)+'-wal')
    with closing(sqlite3.connect(source)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('PRAGMA user_version=11')
        writer.commit()
        retained = {p:p.read_bytes() for p in (source, wal)}
    for path, body in retained.items():
        path.write_bytes(body)
    assert len(retained[wal]) >= 32
    timer = budget.audit_budget(budget.time.monotonic()+30) if timed else nullcontext()
    with timer, restore._restore_database_view(source) as (connection, snapshot):
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 11
        with pytest.raises(ValueError, match='sidecar-free immutable'):
            daily.daily_reconciliation_bounded(source, connection=connection)
        assert snapshot['source_sha256'] == hashlib.sha256(retained[source]).hexdigest()
    assert {p:p.read_bytes() for p in retained} == retained


@pytest.mark.parametrize('snapshot_id', ['', '.', '..', '../outside', 'dir/name', r'dir\name',
    '/absolute', r'C:\absolute', 'C:drive', 'name:stream', 'bad\x00name', 'NUL', 'nul.txt', 'CON', 'LPT1', 'trailing.', 'trailing '])
def test_unsafe_snapshot_identifier_is_rejected_before_any_read_or_receipt(tmp_path, monkeypatch, snapshot_id):
    policy = make_policy(tmp_path)
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    def forbidden(*_a, **_k):
        pytest.fail('unsafe identifier reached source or receipt')
    monkeypatch.setattr(backup, 'verify_snapshot', forbidden)
    monkeypatch.setattr(backup, 'atomic_create_json', forbidden)
    with pytest.raises(ValueError, match='one unambiguous path component'):
        backup.restore_drill(policy, snapshot_id, tmp_path/'scratch', 'pytest', ['restore-drill'])
    assert {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('phase', ['snapshot_hash', 'scratch', 'copy_chunk', 'restored_manifest'])
def test_non_sql_expiry_retains_real_failure_receipt_and_last_pass(tmp_path, monkeypatch, phase):
    policy, snapshot, latest = _snapshot(tmp_path)
    original_bytes = {p.relative_to(snapshot).as_posix(): p.read_bytes() for p in snapshot.rglob('*') if p.is_file()}
    previous, clock = latest.read_bytes(), [0.0]
    monkeypatch.setattr(budget.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(backup, '_verify_restored_state', lambda _root: {'ok': True, 'findings': []})
    if phase == 'snapshot_hash':
        original = backup.restore_hash_file
        def hashed(*args, **kwargs):
            result = original(*args, **kwargs)
            clock[0] = budget.RESTORE_BUDGET_SECONDS + 1
            return result
        monkeypatch.setattr(backup, 'restore_hash_file', hashed)
    elif phase == 'scratch':
        original = backup._prepare_restore_destination
        def prepared(*args, **kwargs):
            clock[0] = budget.RESTORE_BUDGET_SECONDS + 1
            return original(*args, **kwargs)
        monkeypatch.setattr(backup, '_prepare_restore_destination', prepared)
    elif phase == 'copy_chunk':
        original = io.copy_stream
        def copied(*args, **kwargs):
            result = original(*args, **kwargs)
            clock[0] = budget.RESTORE_BUDGET_SECONDS + 1
            return result
        monkeypatch.setattr(io, 'copy_stream', copied)
    else:
        original = restore.sha256_file
        def restored_hash(*args, **kwargs):
            result = original(*args, **kwargs)
            if 'restore-control-snapshot-' in str(args[0]):
                clock[0] = budget.RESTORE_BUDGET_SECONDS + 1
            return result
        monkeypatch.setattr(restore, 'sha256_file', restored_hash)
    with pytest.raises(RuntimeError, match='receipt='):
        backup.restore_drill(policy, 'control-snapshot', tmp_path / 'scratch', 'pytest', ['restore-drill'])
    receipts = list((policy.backup_dir / 'receipts').glob('*.restore.*.json'))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt['result'] == 'FAIL'
    assert receipt['checks']['findings'] == ['restore_exception:TimeoutError']
    assert receipt['manifest_sha256'] == hashlib.sha256(original_bytes['manifest.json']).hexdigest()
    assert not receipt['scratch_retained']
    assert latest.read_bytes() == previous
    assert {p.relative_to(snapshot).as_posix(): p.read_bytes() for p in snapshot.rglob('*') if p.is_file()} == original_bytes


def test_unreadable_initial_manifest_records_honest_failure_without_invented_identity(tmp_path):
    policy, snapshot, latest = _snapshot(tmp_path)
    previous = latest.read_bytes()
    (snapshot / 'manifest.json').unlink()
    with pytest.raises(RuntimeError, match='receipt='):
        backup.restore_drill(policy, 'control-snapshot', tmp_path / 'scratch', 'pytest', ['restore-drill'])
    receipt = json.loads(next((policy.backup_dir / 'receipts').glob('*.restore.*.json')).read_text())
    assert receipt['result'] == 'FAIL'
    assert receipt['manifest_sha256'] is None
    assert receipt['candidate_code_sha'] is None
    assert receipt['scratch_path'] is None and not receipt['scratch_retained']
    assert latest.read_bytes() == previous


def test_complete_real_ledger_budget_refuses_mid_read_without_downgrading_timeout(tmp_path, monkeypatch):
    _write_current_finalized(tmp_path)
    state = tmp_path / 'state'
    assert ledger.verify_ledger(state)['ok']
    original, clock, reads = ledger.read_json, [0.0], []
    monkeypatch.setattr(budget.time, 'monotonic', lambda: clock[0])
    def read(path, **kwargs):
        value = original(path, **kwargs)
        reads.append(path)
        clock[0] = 11.0
        return value
    monkeypatch.setattr(ledger, 'read_json', read)
    with pytest.raises(TimeoutError):
        with budget.audit_budget(10.0):
            ledger.verify_ledger(state, budget=io.checkpoint)
    assert len(reads) == 1
