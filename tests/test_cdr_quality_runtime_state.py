"""Publication-control regression tests; all values here are control metadata."""
import json
import shutil
from pathlib import Path

import pytest

import pi_cdr_quality_runtime_state as state


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


def test_retry_directory_cannot_hide_nested_or_nonfile_controls(roots):
    data, _, _ = roots
    (data / "state" / state.RETRIES / "nested").mkdir(parents=True)
    with pytest.raises(ValueError, match="regular file"):
        state.control_state(data)
