from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import argparse
import zipfile

import pytest

from laptop_backup_trusted_package import build


ROOT = Path(__file__).resolve().parents[1]


def test_trusted_installer_is_fail_closed_and_never_starts_production_task() -> None:
    source = (ROOT / "install_laptop_backup_trusted_dispatcher.ps1").read_text(encoding="utf-8")
    core = (ROOT / "install_laptop_backup_trusted_dispatcher_core.ps1").read_text(encoding="utf-8")
    assert "Start-ScheduledTask -TaskName $TaskName" not in source
    assert "Start-ScheduledTask -TaskName $probeName" in source
    assert "Restore-ArTrustedPriorTask" in source
    assert "ExpectedOldTaskXmlSha256" in source
    assert "ExpectedOldTaskSddlSha256" in source
    assert "ExpectedOldTaskSddlSemanticSha256" in source
    assert "PlanGitCommit" in source
    assert "PlanSha256" in source
    assert "HandoffSha256" in source
    assert "[IO.FileShare]::Read" in core
    assert "$stream.Position = 0" in core
    assert "ZipArchive" in core
    assert "Set-ArTrustedTaskSddl" in source
    assert "Assert-ArTrustedChildConfiguration" in source
    assert "EvidenceRoot must be below Program Files" in source
    assert "InstallRoot is not exactly content-addressed by candidate and authority" in source
    assert "EvidenceRoot is not exactly content-addressed by candidate and authority" in source
    assert "AR-local-backup-trusted-" in source
    assert "AR-local-backup-evidence-" in source
    assert "Set-ArTrustedRootAcl -Root $script:executionRoot" in source
    assert "SSH host must be one strict hostname" in core
    assert "New-ScheduledTaskPrincipal -UserId $Principal -LogonType S4U -RunLevel Limited" in source
    assert "ConvertFrom-Json -AsHashtable" not in source + core
    assert "finalize.enabled" in source
    assert "Protected semantic-finalization result is invalid" in source
    assert "& $python -B -s -E $dispatcher activate" in source
    assert "[ScriptBlock]::Create($coreText)" in source
    assert "FileShare]::Read" in source
    assert "ALREADY_INSTALLED" in source
    assert "Restore-ArTrustedControlRootAtomic" in source
    assert "rollbackErrors.Add" in source
    assert "PRESTATE_REJECTED" in source
    assert "GIT_CONFIG_VALUE_0" in source
    task_runner = (ROOT / "run_laptop_backup_task.ps1").read_text(encoding="utf-8")
    assert "& $PythonPath -B $ScriptPath" in task_runner


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell contract")
def test_trusted_installer_windows_powershell_contract() -> None:
    host = shutil.which("powershell")
    if not host:
        pytest.skip("Windows PowerShell is unavailable")
    subprocess.run(
        (host, "-NoProfile", "-File", str(ROOT / "tests/test_laptop_backup_trusted_dispatcher_installer.ps1")),
        check=True,
    )


def test_package_builder_exposes_only_authenticated_archive_inputs() -> None:
    source = (ROOT / "laptop_backup_trusted_package.py").read_text(encoding="utf-8")
    assert "--candidate-sha" in source
    assert "--authority-sha" in source
    assert "--operator-sid" in source
    assert "package-manifest.json" in source
    assert "case-insensitive duplicate package path" in source
    assert "is_symlink()" in source
    assert "CANONICAL_ORIGIN" in source


def test_package_builder_makes_standalone_exact_checkouts(tmp_path: Path) -> None:
    def repo(name: str) -> tuple[Path, str]:
        path = tmp_path / name
        path.mkdir()
        subprocess.run(("git", "init", "-q", str(path)), check=True)
        subprocess.run(("git", "-C", str(path), "config", "user.email", "test@example.invalid"), check=True)
        subprocess.run(("git", "-C", str(path), "config", "user.name", "test"), check=True)
        for filename in ("run_laptop_backup_trusted_child.ps1", "laptop_backup_dispatcher.py", "laptop_backup_atomic.py"):
            (path / filename).write_text(f"# {filename}\n", encoding="utf-8")
        subprocess.run(("git", "-C", str(path), "add", "."), check=True)
        subprocess.run(("git", "-C", str(path), "commit", "-qm", "test"), check=True)
        commit = subprocess.check_output(("git", "-C", str(path), "rev-parse", "HEAD"), text=True).strip()
        subprocess.run(("git", "-C", str(path), "checkout", "-q", "--detach", commit), check=True)
        return path, commit

    candidate, candidate_sha = repo("candidate")
    authority, authority_sha = repo("authority")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python.exe").write_bytes(b"python")
    (runtime / "unsafe.pth").write_text("import attacker\n", encoding="ascii")
    (runtime / "sitecustomize.py").write_text("raise SystemExit(1)\n", encoding="ascii")
    launcher = tmp_path / "launcher.exe"
    launcher.write_bytes(b"launcher")
    dispatcher_manifest = tmp_path / "dispatcher-manifest.json"
    dispatcher_manifest.write_text("{}\n", encoding="ascii")
    tools = []
    for name in ("git", "ssh", "scp", "whoami"):
        path = tmp_path / f"{name}.exe"
        path.write_bytes(name.encode())
        tools.append(path)
    output = tmp_path / "trusted.zip"
    result = build(argparse.Namespace(
        candidate_repo=str(candidate), candidate_sha=candidate_sha,
        authority_repo=str(authority), authority_sha=authority_sha,
        python_root=str(runtime), launcher=str(launcher), dispatcher_manifest=str(dispatcher_manifest),
        install_root=str(tmp_path / "installed"), control_root=str(tmp_path / "control"),
        operator_sid="S-1-5-21-1-2-3-1001", git=str(tools[0]), ssh=str(tools[1]), scp=str(tools[2]),
        whoami=str(tools[3]), output=str(output),
    ))
    assert result["sha256"]
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        package = json.loads(archive.read("package-manifest.json"))
        assert "receiver/.git/HEAD" in names
        assert "authority/.git/HEAD" in names
        assert "python/unsafe.pth" not in names
        assert "python/sitecustomize.py" not in names
        assert package["candidate_code_sha"] == candidate_sha
        assert package["authority_commit"] == authority_sha
        assert set(package["files"]) == names - {"package-manifest.json"}
