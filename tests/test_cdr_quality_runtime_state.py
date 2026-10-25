"""Publication-control regression tests; all values here are control metadata."""
import ast
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import pi_cdr_quality_runtime_state as state
import pi_payload_retry_policy as retries


@pytest.fixture
def roots(tmp_path):
    data, source, old = (tmp_path / name for name in ("data", "source", "previous"))
    for path in (data / "state", source, old):
        path.mkdir(parents=True)
    shutil.copyfile(Path(state.__file__).with_name("pi_daily_sync.py"), source / "pi_daily_sync.py")
    (old / "pi_daily_sync.py").write_text(
        "def mark_payload_publication_pending(root, reason, pointer=None): pass\n"
        "def clear_payload_publication_pending(root): pass\n")
    return data, source, old


def test_absent_controls_allow_transactional_old_predecessor(roots):
    data, source, old = roots
    snapshot = state.control_state(data)
    contract = state.rollback_contract(source, old)
    assert not contract["queue_compatible"]
    state.require_controls(data, snapshot, contract)
    state.require_predecessor(old, contract)


@pytest.mark.parametrize("queued", [[], [{"generation_id": "retained-a"}, {"generation_id": "retained-b"}]])
def test_old_predecessor_rejects_even_empty_new_queue_field(roots, queued):
    data, source, old = roots
    path = data / "state" / state.PENDING
    path.write_text(json.dumps({"queued_pointers": queued}))
    snapshot = state.control_state(data)
    with pytest.raises(ValueError, match="predecessor cannot preserve"):
        state.require_controls(data, snapshot, state.rollback_contract(source, old))
    shutil.copyfile(source / "pi_daily_sync.py", old / "pi_daily_sync.py")
    state.require_controls(data, snapshot, state.rollback_contract(source, old))
    assert json.loads(path.read_text())["queued_pointers"] == queued


@pytest.mark.parametrize("raw", ['{', '[]', '{"queued_pointers":null}', '{"queued_pointers":[{}]}',
                                 '{"queued_pointers":[],"queued_pointers":[]}'])
def test_unreadable_control_is_never_treated_as_absence(roots, raw):
    data, _, _ = roots
    (data / "state" / state.PENDING).write_text(raw)
    with pytest.raises(ValueError):
        state.control_state(data)


@pytest.mark.parametrize("change", ["pending", "continuity", "retry-add", "retry-remove", "retry-edit", "retry-directory"])
def test_each_publication_control_drift_refuses_rollback_without_restoring(roots, change):
    data, source, old = roots
    retry = data / "state" / state.RETRIES
    retry.mkdir()
    record = retry / ("a" * 64 + ".json")
    record.write_text('{"attempts":1}')
    before = state.control_state(data)
    if change == "pending":
        (data / "state" / state.PENDING).write_text('{"pointer":{"generation_id":"new"}}')
    elif change == "continuity":
        (data / "state" / "app-payload-continuity.json").write_text('{"dates":{}}')
    elif change == "retry-add":
        (retry / ("b" * 64 + ".json")).write_text('{"attempts":1}')
    elif change == "retry-edit":
        record.write_text('{"attempts":2}')
    else:
        record.unlink()
        if change == "retry-directory":
            retry.rmdir()
    changed = state.control_state(data)
    with pytest.raises(ValueError, match="state changed"):
        state.require_controls(data, before, state.rollback_contract(source, old))
    assert state.control_state(data) == changed


def test_predecessor_changed_without_git_head_change_is_rejected(roots):
    _, source, old = roots
    before = state.rollback_contract(source, old)
    (old / "pi_daily_sync.py").write_text((old / "pi_daily_sync.py").read_text() + "# changed\n")
    with pytest.raises(ValueError, match="predecessor publication helper changed"):
        state.require_predecessor(old, before)


def test_matching_helper_bodies_do_not_waive_other_module_changes(roots):
    data, source, old = roots
    shutil.copyfile(source / "pi_daily_sync.py", old / "pi_daily_sync.py")
    (old / "pi_daily_sync.py").write_bytes((old / "pi_daily_sync.py").read_bytes() + b"\n# other module change\n")
    (data / "state" / state.PENDING).write_text('{"queued_pointers":[]}')
    contract = state.rollback_contract(source, old)
    assert contract["candidate_helpers_sha256"] == contract["previous_helpers_sha256"]
    assert contract["queue_compatible"] is False
    with pytest.raises(ValueError, match="predecessor cannot preserve"):
        state.require_controls(data, state.control_state(data), contract)


@pytest.mark.parametrize('helper', ['_mark_payload_publication_pending', '_clear_payload_publication_pending'])
def test_delegated_pending_implementation_is_bound_by_normalized_helper_fingerprint(roots, helper):
    _, source, old = roots
    shutil.copyfile(source / 'pi_daily_sync.py', old / 'pi_daily_sync.py')
    original = state.rollback_contract(source, old)
    assert original['queue_compatible'] is True
    tree = ast.parse((old / 'pi_daily_sync.py').read_text(encoding='utf-8-sig'))
    implementation = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == helper)
    implementation.body.append(ast.Pass())  # Control-only implementation drift.
    (old / 'pi_daily_sync.py').write_text(ast.unparse(tree), encoding='utf-8')
    changed = state.rollback_contract(source, old)
    assert changed['candidate_helpers_sha256'] != changed['previous_helpers_sha256']
    assert changed['queue_compatible'] is False
    with pytest.raises(ValueError, match='predecessor publication helper changed'):
        state.require_predecessor(old, original)


@pytest.mark.parametrize('helper', ['_mark_payload_publication_pending', '_clear_payload_publication_pending'])
def test_missing_checked_delegate_is_rejected_without_guessing_an_implementation(roots, helper):
    _, source, _ = roots
    path = source / 'pi_daily_sync.py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    tree.body = [node for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name != helper]
    path.write_text(ast.unparse(tree), encoding='utf-8')
    with pytest.raises(ValueError, match='publication helpers are unavailable'):
        state._pending_helpers(source)


def test_unused_private_bodies_do_not_make_an_old_predecessor_queue_compatible(roots):
    _, _, old = roots
    path = old / 'pi_daily_sync.py'
    path.write_text(path.read_text() +
        "\ndef _mark_payload_publication_pending(root, reason, pointer=None):\n    queued_pointers = []\n"
        "\ndef _clear_payload_publication_pending(root, pointer=None):\n    queued_pointers = []\n")
    assert state._pending_helpers(old)[2] is False
    assert state.rollback_contract(old, old)['queue_compatible'] is False


def test_retry_directory_cannot_hide_nested_or_nonfile_controls(roots):
    data, _, _ = roots
    (data / "state" / state.RETRIES / "nested").mkdir(parents=True)
    with pytest.raises(ValueError, match="regular file"):
        state.control_state(data)


@pytest.fixture
def reserved_retry(roots, monkeypatch):
    data, _, _ = roots
    monkeypatch.setattr(retries, "data_state_root", lambda _: data / "state")
    reservation = retries.retry_admission(data, {"pointer": {"generation_id": "retained-control"}},
        now_utc=datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc), reserve=True)
    assert reservation["status"] == "ready"
    record = retries.retry_state_path(data, reservation["source_key"])
    return record, reservation


def test_real_released_retry_lock_is_bound_without_changing_retry_state(roots, reserved_retry):
    data, source, old = roots
    record, reservation = reserved_retry
    lock = record.with_suffix(".lock")
    original = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (record, lock)}
    assert original[lock][0] == b"0"
    before = state.control_state(data)
    assert before["files"][lock.relative_to(data / "state").as_posix()]["bytes"] == 1
    state.require_controls(data, before, state.rollback_contract(source, old))
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in original} == original
    retries.finish_retry(data, reservation, succeeded=False, reason="retained failure",
                         now_utc=datetime(2026, 10, 12, 0, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="state changed"):
        state.require_controls(data, before, state.rollback_contract(source, old))
    assert lock.read_bytes() == b"0"


def test_retry_lock_held_by_real_writer_blocks_snapshot_then_recovers(roots, reserved_retry, tmp_path):
    data, _, _ = roots
    record, _ = reserved_retry
    ready = tmp_path / "writer-ready"
    source = ("import sys\nfrom pathlib import Path\nfrom cdr_file_lock import FileLock\n"
              "with FileLock(Path(sys.argv[1])):\n"
              "    Path(sys.argv[2]).write_text('ready')\n"
              "    sys.stdin.readline()\n")
    child = subprocess.Popen([sys.executable, "-B", "-c", source, str(record.with_suffix(".lock")), str(ready)],
                             cwd=Path(state.__file__).parent, stdin=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "owned retry writer did not acquire its lock"
        started = time.monotonic()
        with pytest.raises(ValueError, match="retry lock.*held"):
            state.control_state(data)
        assert time.monotonic() - started < 2
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()  # Only this owned child; Windows TerminateProcess, never signal zero.
            child.wait(timeout=5)
    assert child.returncode == 0
    state.control_state(data)


@pytest.mark.parametrize("name,body", [("a" * 64 + ".lock", b""), ("a" * 64 + ".lock", b"00"),
                                      ("a" * 64 + ".lock", b"{}"), ("unknown.lock", b"0"),
                                      ("unknown.json", b"{}"), ("a" * 64 + ".tmp", b"{}")])
def test_unknown_or_malformed_retry_files_are_preserved_and_rejected(roots, name, body):
    data, _, _ = roots
    retry = data / "state" / state.RETRIES
    retry.mkdir()
    path = retry / name
    path.write_bytes(body)
    with pytest.raises(ValueError):
        state.control_state(data)
    assert path.read_bytes() == body


def test_orphan_released_lock_is_preserved_but_membership_drift_is_rejected(roots):
    from cdr_file_lock import FileLock

    data, source, old = roots
    lock = data / "state" / state.RETRIES / ("a" * 64 + ".lock")
    with FileLock(lock):
        pass  # A writer may die after creating the lock and before writing its record.
    before = state.control_state(data)
    lock.unlink()  # Test-only drift, never recovery behavior.
    with pytest.raises(ValueError, match="state changed"):
        state.require_controls(data, before, state.rollback_contract(source, old))


def test_retry_lock_must_not_be_hardlinked(roots, tmp_path):
    data, _, _ = roots
    retry = data / "state" / state.RETRIES
    retry.mkdir()
    lock = retry / ("a" * 64 + ".lock")
    lock.write_bytes(b"0")
    os.link(lock, tmp_path / "alias")
    with pytest.raises(ValueError, match="unique regular file"):
        state.control_state(data)


def test_retry_locks_stay_held_through_snapshot_and_release_afterward(roots, reserved_retry, monkeypatch):
    from cdr_file_lock import FileLock

    data, _, _ = roots
    record, _ = reserved_retry
    locks = [record.with_suffix(".lock"), record.with_name("b" * 64 + ".lock")]
    with FileLock(locks[1]):
        pass

    def try_writer_lock(path):
        descriptor = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)

    original_finish = state.DigestSnapshot.finish
    observed = []
    def finish(snapshot):
        for path in locks:
            with pytest.raises(OSError):
                try_writer_lock(path)
            observed.append(path)
        return original_finish(snapshot)
    monkeypatch.setattr(state.DigestSnapshot, "finish", finish)
    state.control_state(data)
    assert observed == locks
    for path in locks:
        try_writer_lock(path)


def test_retry_lock_replacement_between_identity_check_and_open_is_rejected(roots, reserved_retry, monkeypatch):
    data, _, _ = roots
    record, _ = reserved_retry
    lock = record.with_suffix(".lock")
    replacement = record.with_name("replacement")
    original_open = state.os.open
    def replace_then_open(path, flags, *args, **kwargs):
        if Path(path) == lock:
            replacement.write_bytes(b"0")
            os.replace(replacement, lock)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(state.os, "open", replace_then_open)
    with pytest.raises(ValueError, match="descriptor differs"):
        state.control_state(data)
    assert lock.read_bytes() == b"0"


def test_retry_lock_added_during_snapshot_is_not_silently_omitted(roots, reserved_retry, monkeypatch):
    from cdr_file_lock import FileLock

    data, _, _ = roots
    record, _ = reserved_retry
    added = record.with_name("b" * 64 + ".lock")
    original_finish = state.DigestSnapshot.finish
    def finish(snapshot):
        with FileLock(added):
            pass
        return original_finish(snapshot)
    monkeypatch.setattr(state.DigestSnapshot, "finish", finish)
    with pytest.raises(ValueError, match="directory changed"):
        state.control_state(data)
    assert added.read_bytes() == b"0"
