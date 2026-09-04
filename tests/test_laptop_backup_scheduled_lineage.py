from __future__ import annotations

import json
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

import laptop_backup_scheduled as scheduled
import laptop_backup_scheduled_lineage as lineage
import laptop_pull_backup as receiver


def _args() -> Namespace:
    return Namespace(
        plan_git_commit=receiver.PLAN_GIT_COMMIT,
        candidate_code_sha="c" * 40,
        protected_code_sha="9" * 40,
        operator="pytest",
    )


def _baseline(target: Path) -> dict[str, str]:
    (target / "catalog").mkdir(parents=True)
    scheduled.record_execution(
        target, _args(), "PASS", "NO_BACKUP_DATA_WRITE", {"status": "UP_TO_DATE"}
    )
    return json.loads(
        (target / "catalog/latest-scheduled.json").read_text(encoding="utf-8")
    )


def test_record_execution_bootstraps_first_scheduled_record(tmp_path: Path) -> None:
    target = tmp_path / "backup"
    (target / "catalog").mkdir(parents=True)

    path = scheduled.record_execution(
        target, _args(), "PASS", "NO_BACKUP_DATA_WRITE", {"status": "UP_TO_DATE"}
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    pointer = json.loads(
        (target / "catalog/latest-scheduled.json").read_text(encoding="utf-8")
    )
    assert record["previous_execution"] is None
    assert pointer["record_path"] == path.relative_to(target).as_posix()
    assert pointer["record_sha256"] == receiver.sha256_file(path)


def test_record_execution_rolls_forward_orphan_after_pointer_replace_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "backup"
    baseline = _baseline(target)
    pointer_path = target / "catalog/latest-scheduled.json"
    original_replace = receiver.atomic_replace
    failed = False

    def fail_new_record_pointer(path: Path, payload: bytes) -> None:
        nonlocal failed
        value = json.loads(payload)
        if path == pointer_path and value.get("record_path") != baseline["record_path"] and not failed:
            failed = True
            raise OSError("injected pointer crash")
        original_replace(path, payload)

    monkeypatch.setattr(receiver, "atomic_replace", fail_new_record_pointer)
    with pytest.raises(OSError, match="pointer crash"):
        scheduled.record_execution(
            target, _args(), "PASS", "NO_BACKUP_DATA_WRITE", {"status": "UP_TO_DATE"}
        )
    orphan = next(
        path for path in (target / "catalog/scheduled-runs").glob("*.json")
        if path.relative_to(target).as_posix() != baseline["record_path"]
    )
    assert json.loads(pointer_path.read_text(encoding="utf-8")) == baseline

    final = scheduled.record_execution(
        target, _args(), "PASS", "NO_BACKUP_DATA_WRITE", {"status": "UP_TO_DATE"}
    )
    final_value = json.loads(final.read_text(encoding="utf-8"))
    assert final_value["previous_execution"] == {
        "record_path": orphan.relative_to(target).as_posix(),
        "record_sha256": receiver.sha256_file(orphan),
    }
    assert json.loads(pointer_path.read_text(encoding="utf-8"))["record_path"] == (
        final.relative_to(target).as_posix()
    )


def test_first_record_pointer_crash_adopts_one_authenticated_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "backup"
    (target / "catalog").mkdir(parents=True)
    pointer_path = target / "catalog/latest-scheduled.json"
    original_replace = receiver.atomic_replace
    failed = False

    def fail_once(path: Path, payload: bytes) -> None:
        nonlocal failed
        if path == pointer_path and not failed:
            failed = True
            raise OSError("injected first pointer crash")
        original_replace(path, payload)

    monkeypatch.setattr(receiver, "atomic_replace", fail_once)
    with pytest.raises(OSError, match="first pointer crash"):
        scheduled.record_execution(
            target, _args(), "PASS", "NO_BACKUP_DATA_WRITE", {"status": "UP_TO_DATE"}
        )
    root = next((target / "catalog/scheduled-runs").glob("*.json"))

    final = scheduled.record_execution(
        target, _args(), "PASS", "NO_BACKUP_DATA_WRITE", {"status": "UP_TO_DATE"}
    )

    assert json.loads(root.read_text(encoding="utf-8"))["previous_execution"] is None
    assert json.loads(final.read_text(encoding="utf-8"))["previous_execution"] == {
        "record_path": root.relative_to(target).as_posix(),
        "record_sha256": receiver.sha256_file(root),
    }


def test_scheduled_record_mutex_serializes_independent_processes(tmp_path: Path) -> None:
    target = tmp_path / "backup"
    (target / "catalog").mkdir(parents=True)
    ready, release, acquired = (tmp_path / name for name in ("ready", "release", "acquired"))
    holder_code = "\n".join((
        "import sys,time",
        "from pathlib import Path",
        "from laptop_backup_scheduled_lineage import scheduled_record_mutex as m",
        "t,r,x=map(Path,sys.argv[1:])",
        "with m(t):",
        " r.write_text('ready')",
        " while not x.exists(): time.sleep(.02)",
    ))
    contender_code = (
        "import sys; from pathlib import Path; "
        "from laptop_backup_scheduled_lineage import scheduled_record_mutex as m; "
        "t,a=map(Path,sys.argv[1:]);\nwith m(t): a.write_text('acquired')"
    )
    holder = subprocess.Popen([sys.executable, "-c", holder_code, str(target), str(ready), str(release)])
    contender: subprocess.Popen[bytes] | None = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        contender = subprocess.Popen([sys.executable, "-c", contender_code, str(target), str(acquired)])
        time.sleep(0.25)
        assert not acquired.exists()
        release.write_text("release", encoding="utf-8")
        assert holder.wait(timeout=5) == 0
        assert contender.wait(timeout=5) == 0
        assert acquired.exists()
    finally:
        release.touch()
        if holder.poll() is None:
            holder.kill()
        if contender is not None and contender.poll() is None:
            contender.kill()


def test_legacy_predecessor_requires_explicit_transition_candidate() -> None:
    old_candidate = "d" * 40
    record = {
        "schema_version": 1,
        "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": "1.4",
        "plan_git_commit": "14dd066099bba393cccf61a280243e43162eedc9",
        "plan_sha256": "78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713",
        "plan_raw_sha256": "a5a679297167c37845fbacf0cdf895cad4fb2900c09c1e94e310319d3ae9118d",
        "plan_normalized_raw_sha256": "c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4",
        "candidate_code_sha": old_candidate,
        "protected_code_sha": "9" * 40,
        "operator": "pytest",
        "timestamps": {"completed_at": "2026-08-30T07:35:43Z"},
        "exact_commands": ["python laptop_backup_scheduled.py --check-only"],
        "action": "NO_BACKUP_DATA_WRITE",
        "result": "PASS",
        "detail": {},
        "deviations": [],
        "deviation_authorization": None,
    }
    expected = {
        "candidate_code_sha": "c" * 40,
        "protected_code_sha": "9" * 40,
        "operator": "pytest",
        "allowed_predecessor_candidates": (old_candidate,),
    }

    lineage._validate_owned_record(record, expected, predecessor=True)
    with pytest.raises(ValueError, match="candidate"):
        lineage._validate_owned_record(record, expected)
    record["plan_normalized_raw_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="plan identity"):
        lineage._validate_owned_record(record, expected, predecessor=True)
