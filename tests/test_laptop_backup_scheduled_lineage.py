from __future__ import annotations

import json
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

import laptop_backup_scheduled as scheduled
import laptop_pull_backup as receiver


def _args() -> Namespace:
    return Namespace(
        plan_git_commit=receiver.PLAN_GIT_COMMIT,
        candidate_code_sha="c" * 40,
        protected_code_sha="9" * 40,
        operator="pytest",
    )


def _baseline(target: Path) -> dict[str, str]:
    root = target / "catalog/scheduled-runs"
    root.mkdir(parents=True)
    record = root / "baseline.json"
    record.write_text(json.dumps({"result": "PASS"}), encoding="utf-8")
    pointer = {
        "record_path": record.relative_to(target).as_posix(),
        "record_sha256": receiver.sha256_file(record),
        "result": "PASS",
    }
    (target / "catalog/latest-scheduled.json").write_bytes(
        receiver.canonical_json_bytes(pointer)
    )
    return pointer


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
        if path.name != "baseline.json"
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
