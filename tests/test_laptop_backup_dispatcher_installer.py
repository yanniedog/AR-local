from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_dispatcher_installer_powershell_contract() -> None:
    if os.name != "nt":
        pytest.skip("Task Scheduler contract is Windows-only")
    hosts = list(dict.fromkeys(filter(None, (shutil.which("powershell"), shutil.which("pwsh")))))
    if not hosts:
        pytest.skip("PowerShell is unavailable")
    for host in hosts:
        subprocess.run(
            (host, "-NoProfile", "-File", str(ROOT / "tests/test_laptop_backup_dispatcher_installer.ps1")),
            check=True,
        )


def test_elevated_installer_uses_windows_powershell_51_json_contract() -> None:
    source = (ROOT / "install_laptop_backup_dispatcher.ps1").read_text(encoding="utf-8")
    assert "ConvertFrom-Json -AsHashtable" not in source
