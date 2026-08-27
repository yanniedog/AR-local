import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_task_registration_and_read_back_fail_closed() -> None:
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "PowerShell 7 is required to test the Windows task installer"
    subprocess.run(
        [pwsh, "-NoProfile", "-File", str(ROOT / "tests/test_laptop_backup_task_installer.ps1")],
        cwd=ROOT,
        check=True,
    )
