from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_dispatcher_installer_powershell_contract() -> None:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("PowerShell is unavailable")
    subprocess.run(
        (pwsh, "-NoProfile", "-File", str(ROOT / "tests/test_laptop_backup_dispatcher_installer.ps1")),
        check=True,
    )
