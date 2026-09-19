"""Keep Drive unit-test controls independent of the operator's real host hold."""
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def isolated_backup_unit_capacity(request, monkeypatch):
    modules = {
        'test_laptop_backup_runtime_ancestry.py',
        'test_laptop_backup_transition_flow.py',
        'test_laptop_backup_transition_recovery.py',
        'test_laptop_backup_transition_quiescence.py',
    }
    if Path(str(request.node.path)).name not in modules:
        return
    import shutil

    # These tests use FakeOps and temporary evidence, not real backups. Give
    # them a controlled healthy capacity; explicit low-disk cases override it.
    # Production thresholds and the contract's capacity-boundary tests remain.
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(
        total=200 * 1024**3, used=100 * 1024**3, free=100 * 1024**3))


@pytest.fixture(autouse=True)
def isolated_drive_system_hold(request, monkeypatch):
    if not Path(str(request.node.path)).name.startswith("test_pi_drive"):
        return
    import pi_drive_backup_hold as hold

    # Exercise the real hold logic against per-test paths. Production retains
    # its hard-coded global marker; this changes no subprocess or host config.
    # Specific hold/barrier fixtures can install their own markers afterward.
    config = request.getfixturevalue("tmp_path") / "isolated-system-config"
    monkeypatch.setattr(hold, "SYSTEM_HOLD", config / "drive-write-hold.json")
