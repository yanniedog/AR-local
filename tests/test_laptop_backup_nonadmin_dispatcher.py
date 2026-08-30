from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install_laptop_backup_nonadmin_dispatcher.ps1"
CORE = ROOT / "install_laptop_backup_nonadmin_dispatcher_core.ps1"
SHARED_CORE = ROOT / "install_laptop_backup_dispatcher_core.ps1"
TEMPLATE = ROOT / "run_laptop_backup_nonadmin_dispatcher.ps1"
REPAIR = ROOT / "repair_laptop_backup_restricted_runner.ps1"
REPAIR_CORE = ROOT / "repair_laptop_backup_restricted_runner_core.ps1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def powershell5() -> str:
    if os.name != "nt":
        pytest.skip("Windows PowerShell integration is Windows-only")
    path = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not path.is_file():
        pytest.skip("Windows PowerShell 5.1 is unavailable")
    return str(path)


def run_ps(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [powershell5(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )


def ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def test_installer_never_mutates_or_triggers_task_scheduler() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    for prohibited in (
        "Register-ScheduledTask",
        "Unregister-ScheduledTask",
        "Start-ScheduledTask",
        "Enable-ScheduledTask",
        "Disable-ScheduledTask",
        "SetSecurityDescriptor",
    ):
        assert prohibited not in source
    assert "D-009 transition must run without administrator elevation" in source
    assert "New-ArLfRemoteScript" in source
    assert "Install-ArManagedRunnerAtomic" in source
    assert "Restore-ArManagedRunnerAtomic" in source
    assert "ControlRoot must be exactly Target\\dispatcher-control" in source
    assert "$script:manifest.scheduled_plan_git_commit -cne $ScheduledPlanGitCommit" in source


def test_runner_fails_closed_and_binds_every_dependency() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert source.count("__AR_CONFIG_SHA256__") == 1
    assert source.count("__AR_RESTRICTED_LAUNCHER_SHA256__") == 1
    assert "Managed dispatcher configuration is absent" in source
    assert "implementation checkout is not exact, clean and detached" in source
    assert "dispatcher dependency hash mismatch" in source
    assert "laptop_backup_dispatcher.py" in source
    assert "laptop_backup_atomic.py" in source
    assert "laptop_backup_restricted_process.py" in source
    assert "restricted_launcher_sha256" in source
    assert "AR_LOCAL_BACKUP_DISPATCHER_MODE" in source
    assert "Start-ScheduledTask" not in source


def test_repair_never_mutates_or_triggers_task_scheduler() -> None:
    source = REPAIR.read_text(encoding="utf-8")
    for prohibited in (
        "Register-ScheduledTask",
        "Unregister-ScheduledTask",
        "Start-ScheduledTask",
        "Enable-ScheduledTask",
        "Disable-ScheduledTask",
        "SetSecurityDescriptor",
    ):
        assert prohibited not in source
    assert "D-009 repair must run without administrator elevation" in source
    assert "Install-ArManagedFileAtomic" in source
    assert "Restore-ArManagedFileAtomic" in source
    assert "restricted-probe-$probeNumber.json" in source
    assert "task_triggered = $false" in source


def test_core_emits_lf_only_remote_program() -> None:
    script = (
        f". {ps_quote(CORE)}; "
        "$value=New-ArLfRemoteScript -Lines @('set -eu','cd /srv/ar-local/AR-local'); "
        "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($value))"
    )
    result = run_ps(script)
    assert result.returncode == 0, result.stderr
    payload = base64.b64decode(result.stdout.strip())
    assert payload == b"set -eu\ncd /srv/ar-local/AR-local\n"
    assert b"\r" not in payload


def test_atomic_runner_replace_and_exact_restore(tmp_path: Path) -> None:
    runner = tmp_path / "run.ps1"
    runner.write_text("old runner\n", encoding="utf-8", newline="")
    backup = tmp_path / "evidence/legacy.ps1"
    backup.parent.mkdir()
    failed = tmp_path / "evidence/failed.ps1"
    config_hash = "a" * 64
    launcher_hash = "b" * 64
    rendered_bytes = (
        TEMPLATE.read_bytes()
        .replace(b"__AR_CONFIG_SHA256__", config_hash.encode())
        .replace(b"__AR_RESTRICTED_LAUNCHER_SHA256__", launcher_hash.encode())
    )
    rendered = rendered_bytes.decode("utf-8")
    old_hash = sha256(runner)
    new_hash = hashlib.sha256(rendered_bytes).hexdigest()
    script = (
        f". {ps_quote(SHARED_CORE)}; . {ps_quote(CORE)}; "
        f"$text=New-ArManagedRunnerText -TemplatePath {ps_quote(TEMPLATE)} -ConfigSha256 '{config_hash}' "
        f"-RestrictedLauncherSha256 '{launcher_hash}'; "
        f"Install-ArManagedRunnerAtomic -RunnerPath {ps_quote(runner)} -RunnerText $text "
        f"-BackupPath {ps_quote(backup)} -ExpectedOldSha256 '{old_hash}' -ExpectedNewSha256 '{new_hash}'; "
        f"Restore-ArManagedRunnerAtomic -RunnerPath {ps_quote(runner)} -BackupPath {ps_quote(backup)} "
        f"-FailedRunnerPath {ps_quote(failed)} -ExpectedOldSha256 '{old_hash}'; "
        f"@((Get-ArSha256 {ps_quote(runner)}),(Get-ArSha256 {ps_quote(backup)}),(Get-ArSha256 {ps_quote(failed)})) -join ','"
    )
    result = run_ps(script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{old_hash},{old_hash},{new_hash}"


def test_atomic_managed_file_replace_and_exact_restore(tmp_path: Path) -> None:
    destination = tmp_path / "live.json"
    source = tmp_path / "new.json"
    backup = tmp_path / "evidence/old.json"
    failed = tmp_path / "evidence/failed.json"
    backup.parent.mkdir()
    destination.write_bytes(b"old\n")
    source.write_bytes(b"new\n")
    old_hash = sha256(destination)
    new_hash = sha256(source)
    script = (
        f". {ps_quote(SHARED_CORE)}; . {ps_quote(CORE)}; . {ps_quote(REPAIR_CORE)}; "
        f"Install-ArManagedFileAtomic -DestinationPath {ps_quote(destination)} -SourcePath {ps_quote(source)} "
        f"-BackupPath {ps_quote(backup)} -ExpectedOldSha256 '{old_hash}' -ExpectedNewSha256 '{new_hash}'; "
        f"Restore-ArManagedFileAtomic -DestinationPath {ps_quote(destination)} -BackupPath {ps_quote(backup)} "
        f"-FailedPath {ps_quote(failed)} -ExpectedOldSha256 '{old_hash}' -ExpectedFailedSha256 '{new_hash}'; "
        f"@((Get-ArSha256 {ps_quote(destination)}),(Get-ArSha256 {ps_quote(backup)}),(Get-ArSha256 {ps_quote(failed)})) -join ','"
    )
    result = run_ps(script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{old_hash},{old_hash},{new_hash}"


def test_repair_scripts_parse_under_windows_powershell_51() -> None:
    for path in (REPAIR, REPAIR_CORE, TEMPLATE):
        script = (
            f"$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile("
            f"{ps_quote(path)},[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count-ne 0){$errors|ForEach-Object{[Console]::Error.WriteLine($_.Message)};exit 1}"
        )
        result = run_ps(script)
        assert result.returncode == 0, f"{path}: {result.stderr}"


def create_fake_implementation(path: Path) -> tuple[str, str, str, str]:
    path.mkdir()
    dispatcher = path / "laptop_backup_dispatcher.py"
    dispatcher.write_text(
        "import json,sys\nprint(json.dumps({'ok': True, 'result': 'PASS', 'mode': sys.argv[1]}))\n",
        encoding="utf-8",
        newline="",
    )
    atomic = path / "laptop_backup_atomic.py"
    atomic.write_text("# fixed dependency\n", encoding="utf-8", newline="")
    restricted = path / "laptop_backup_restricted_process.py"
    restricted.write_bytes((ROOT / "laptop_backup_restricted_process.py").read_bytes())
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(path), "checkout", "--detach", "-q", commit], check=True)
    return commit, sha256(dispatcher), sha256(atomic), sha256(restricted)


@pytest.mark.skipif(
    os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin()),
    reason="PR581 user-writable elevated-parent route is quarantined",
)
def test_rendered_runner_executes_hash_bound_detached_dispatcher(tmp_path: Path) -> None:
    implementation = tmp_path / "implementation"
    commit, dispatcher_hash, atomic_hash, restricted_hash = create_fake_implementation(implementation)
    target = tmp_path / "target"
    control = target / "dispatcher-control"
    control.mkdir(parents=True)
    config = {
        "schema_version": 2,
        "implementation_root": str(implementation),
        "implementation_commit": commit,
        "dispatcher_sha256": dispatcher_hash,
        "atomic_module_sha256": atomic_hash,
        "restricted_launcher_sha256": restricted_hash,
        "python_path": sys.executable,
        "python_sha256": sha256(Path(sys.executable)),
        "control_root": str(control),
    }
    config_path = control / "runner-config.json"
    config_path.write_text(json.dumps(config, separators=(",", ":")) + "\n", encoding="utf-8", newline="")
    rendered = (
        TEMPLATE.read_bytes()
        .replace(b"__AR_CONFIG_SHA256__", sha256(config_path).encode())
        .replace(b"__AR_RESTRICTED_LAUNCHER_SHA256__", restricted_hash.encode())
    )
    runner = tmp_path / "managed.ps1"
    runner.write_bytes(rendered)
    env = os.environ.copy()
    env["AR_LOCAL_BACKUP_DISPATCHER_MODE"] = "probe"
    args = [
        powershell5(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(runner), "-PythonPath", sys.executable, "-ScriptPath", str(runner),
        "-Target", str(target), "-RecoveryImage", str(target), "-CandidateCodeSha", "a" * 40,
        "-ProtectedCodeSha", "b" * 40, "-PlanGitCommit", "c" * 40, "-Operator", "test",
    ]
    result = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mode"] == "probe"

    config_path.write_text(config_path.read_text(encoding="utf-8") + " ", encoding="utf-8", newline="")
    drifted = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
    assert drifted.returncode == 1
