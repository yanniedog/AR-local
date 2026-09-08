"""Exercise capture boundaries without contacting production or starting a task."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
FOLDER = ROOT / "docs/evidence/runtime-boundaries-20260909"
PS = shutil.which("pwsh") or shutil.which("powershell")


def quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def shell(code):
    return subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", code],
                          capture_output=True, text=True, timeout=20)


@pytest.mark.skipif(not PS, reason="PowerShell unavailable")
def test_linked_output_parent_is_rejected(tmp_path):
    inside, outside = tmp_path / "inside", tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    link = inside / "link"
    if os.name == "nt":
        made = shell("New-Item -ItemType Junction -Path " + quote(link) + " -Target " + quote(outside))
        assert made.returncode == 0, made.stderr
    else:
        link.symlink_to(outside, target_is_directory=True)
    code = ". " + quote(FOLDER / "capture-paths.ps1") + "; AssertEvidenceParents " + quote(link / "new-output")
    result = shell(code)
    assert result.returncode != 0
    assert "link or reparse point" in result.stderr
    assert not list(outside.iterdir())


@pytest.mark.skipif(not PS, reason="PowerShell unavailable")
def test_existing_ordinary_output_parents_are_accepted(tmp_path):
    result = shell(". " + quote(FOLDER / "capture-paths.ps1") + "; AssertEvidenceParents " + quote(tmp_path / "new-output"))
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "new-output").exists()


@pytest.mark.skipif(not PS, reason="PowerShell unavailable")
def test_runtime_failure_payload_reaches_capture_assignment():
    source = (FOLDER / "runtime-identity-isolated.ps1").read_text(encoding="utf-8")
    branch = source[source.index("if($LASTEXITCODE -ne 0)"):source.index("$verified=")]
    # Execute the actual wrapper failure branch through the same assignment form
    # as the capture driver, with a controlled failing-reader output.
    code = """$ErrorActionPreference='Stop'
function RunFailedReader {
$raw=@('{"runtime_binding":"FAIL","error":"runtime checkout is dirty"}')
$LASTEXITCODE=1
""" + branch + """
throw 'Failure unexpectedly continued'
}
$rows=@(RunFailedReader)
$value=($rows -join "`n") | ConvertFrom-Json
if($value.runtime_binding -cne 'FAIL' -or $value.error -cne 'runtime checkout is dirty'){throw 'Failure payload was lost'}
"""
    result = shell(code)
    assert result.returncode == 0, result.stderr
