from __future__ import annotations

import json
from pathlib import Path

import pytest

import laptop_backup_transition as transition
from test_laptop_backup_transition_contract import listing, task_snapshot
from test_laptop_backup_transition_flow import FakeOps, config, patch_flow


def test_recovery_quiesces_enabled_old_task_even_before_disable_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value = config(tmp_path)
    ops = FakeOps(value)
    patch_flow(monkeypatch, value)
    evidence = transition.Evidence(
        value, "pre-disable-recovery", resume=False, commands=["pytest pre-disable recovery"]
    )
    transition.write_prestate(
        evidence,
        value,
        task_snapshot(transition.task_expectation(value, old=True, enabled=True)),
        listing(),
    )
    evidence.bind_prestate()
    pointer_before = (value.target / "catalog/latest-scheduled.json").read_bytes()

    recovered = transition.recover(value, ops, evidence)

    assert recovered["restored"] == ["task"]
    assert ops.calls.index("task:RestoreDisabled") < ops.calls.index("task:Enable")
    assert ops.calls.index("task:RestoreDisabled") < ops.calls.index("processes")
    assert json.loads(
        (value.target / "catalog/latest-scheduled.json").read_text(encoding="utf-8")
    ) == json.loads(pointer_before)
