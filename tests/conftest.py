"""Keep Drive unit-test controls independent of the operator's real host hold."""
from pathlib import Path

import pytest


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
