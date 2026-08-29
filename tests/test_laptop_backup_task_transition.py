import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_transition_helper_actions_and_failure_paths() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")
    subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-Command",
            "$TestDrive=Join-Path ([IO.Path]::GetTempPath()) ('ar-transition-' + [guid]::NewGuid()); "
            "New-Item -ItemType Directory -Path $TestDrive | Out-Null; "
            "try { & '"
            + str(ROOT / "tests/test_laptop_backup_task_transition.ps1").replace("'", "''")
            + "' } finally { Remove-Item -LiteralPath $TestDrive -Recurse -Force -ErrorAction SilentlyContinue }",
        ],
        cwd=ROOT,
        check=True,
    )
