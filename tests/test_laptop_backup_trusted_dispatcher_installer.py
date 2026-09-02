from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import argparse
import zipfile

import pytest

import laptop_backup_trusted_package as trusted_package
from laptop_backup_trusted_package import build


ROOT = Path(__file__).resolve().parents[1]


def test_trusted_installer_is_fail_closed_and_never_starts_production_task() -> None:
    source = (ROOT / "install_laptop_backup_trusted_dispatcher.ps1").read_text(encoding="utf-8")
    core = (ROOT / "install_laptop_backup_trusted_dispatcher_core.ps1").read_text(encoding="utf-8")
    ssh_boundary = (ROOT / "install_laptop_backup_trusted_dispatcher_ssh.ps1").read_text(encoding="utf-8")
    combined = source + core + ssh_boundary
    assert "Start-ScheduledTask -TaskName $TaskName" not in source
    assert "Start-ScheduledTask -TaskName $probeName" in source
    assert "Restore-ArTrustedPriorTask" in source
    assert "ExpectedOldTaskXmlSha256" in source
    assert "ExpectedOldTaskSddlSha256" in source
    assert "ExpectedOldTaskSddlSemanticSha256" in source
    assert "ExpectedCatalogSha256" in source
    assert "ExpectedAcceptedReceiptSha256" in source
    assert "ExpectedAcceptedCatalogEntrySha256" in source
    assert "ExpectedAcceptedArchiveSize" in source
    assert "PreExecutionManifestPath" in source
    assert "PreExecutionManifestSha256" in source
    assert "RecoveryImage" in source
    assert "PlanGitCommit" in source
    assert "PlanSha256" in source
    assert "HandoffSha256" in source
    assert "[IO.FileShare]::Read" in core
    assert "$stream.Position = 0" in core
    assert "ZipArchive" in core
    assert "Set-ArTrustedTaskSddl" in source
    assert "Assert-ArTrustedChildConfiguration" in source
    assert "dispatcher_security_path" in core and "dispatcher_security_sha256" in core
    assert "laptop_backup_dispatcher_security.py" in core
    assert "EvidenceRoot must be below Program Files" in source
    assert "InstallRoot is not exactly content-addressed by candidate and authority" in source
    assert "EvidenceRoot is not exactly content-addressed by candidate and authority" in source
    assert "AR-local-backup-trusted-" in source
    assert "AR-local-backup-evidence-" in source
    assert "Set-ArTrustedRootAcl -Root $script:executionRoot" in source
    assert "SSH host must be one strict hostname" in ssh_boundary
    for option in (
        "-F NUL", "IdentitiesOnly=yes", "IdentityAgent=none", "PasswordAuthentication=no",
        "KbdInteractiveAuthentication=no", "StrictHostKeyChecking=yes", "UserKnownHostsFile=",
        "GlobalKnownHostsFile=NUL", "UpdateHostKeys=no", "VerifyHostKeyDNS=no",
        "ForwardAgent=no", "ClearAllForwardings=yes", "RequestTTY=no",
    ):
        assert option in combined
    assert "SshIdentityPath" in source and "SshIdentitySha256" in source
    assert "SshKnownHostsPath" not in source
    assert "$script:trustedSshConfig" in source
    assert "-IdentityPath ([string]$config.ssh_identity_path)" in source
    assert "-KnownHostsPath ([string]$config.ssh_known_hosts_path)" in source
    assert "Trusted SSH executable ACL owner or inheritance is invalid" in ssh_boundary
    assert "Assert-ArTrustedSinglePathAcl -Path $SshIdentityPath" not in combined
    assert "CREATE_PROTECTED_SSH_INPUT" in ssh_boundary
    assert "REMOVE_PROTECTED_SSH_INPUT" in ssh_boundary
    assert "Set-ArTrustedRootAcl -Root $inputRoot" in ssh_boundary
    assert "Assert-ArTrustedRootAcl -Root $inputRoot" in ssh_boundary
    assert "Protected SSH identity input cleanup failed" in ssh_boundary
    assert "RECOVERY_REMOVE_PROTECTED_SSH_INPUT" in ssh_boundary
    assert "Remove-ArTrustedOrphanedSshInputs -OperatorSid $OperatorSid" in source
    assert "Wait-ArTrustedProcess" in ssh_boundary and "TerminateJobObject" in ssh_boundary
    assert "Wait-ArTrustedRedirectedTasks" in ssh_boundary
    assert "ArTrustedJobObject" in ssh_boundary and "0x00002000" in ssh_boundary
    assert "AssignProcessToJobObject" in ssh_boundary and "TerminateJobObject" in ssh_boundary
    assert "SshBoundarySha256" in source
    assert "New-ScheduledTaskPrincipal -UserId $Principal -LogonType S4U -RunLevel Limited" in source
    assert "ConvertFrom-Json -AsHashtable" not in combined
    assert "finalize.enabled" in source
    assert "Protected semantic-finalization result is invalid" in source
    assert "$probe.token_elevation -ne $false" in source
    assert "$probe.token_elevation_type -notin @('Default','Limited')" in source
    assert "$probe.token_has_restrictions -ne $true" in source
    assert "$probe.ssh_preflight -cne 'PASS'" in source
    assert "verify-active --control-root $ControlRoot" in source
    assert "active-control-validation.json" in source
    assert "terminal-quiescence.json" in source
    assert "Assert-ArTrustedBackupQuiescence -RequireReadyTask" in source
    assert "Global\\ARLocalTrustedBootstrapGate" in source
    assert "Enter-ArTrustedBootstrapGate" in source
    assert "bootstrap_gate_held = $true" in source
    assert "AR_LOCAL_TRUSTED_BOOTSTRAP_READY_V2" in source
    assert '$expectedReady = "AR_LOCAL_TRUSTED_BOOTSTRAP_READY_V2`n$fixedResultSha256`n"' in source
    assert "PUBLISH_TERMINAL_BOOTSTRAP_READINESS" in source
    assert "-AllowedRuntimeFiles @('ssh\\id','bootstrap.ready','bootstrap.ready.pending','bootstrap-result.json','bootstrap-result.json.pending','installed-task-sddl-semantic.sha256')" in source
    assert source.index("post-bootstrap-catalog.json") < source.index("terminal-quiescence.json")
    assert source.count("Invoke-ArTrustedPiIdleCheck") >= 3
    assert source.index("PUBLISH_PROTECTED_ROOT") < source.index("Invoke-ArTrustedPiIdleCheck -Phase 'protected-package preflight'")
    assert source.index("Invoke-ArTrustedPiIdleCheck -Phase 'immediate pre-mutation'") < source.index("Disable-ScheduledTask -TaskName $TaskName")
    result_writer = source[source.index("function Write-ArTrustedResult"):source.index("function Enter-ArTrustedBootstrapGate")]
    assert "Get-ChildItem -LiteralPath $script:executionRoot" in result_writer
    assert "ssh_identity_path" not in result_writer
    assert "Stop-ScheduledTask -TaskName $probeName" in source
    assert source.index("Stop-ArTrustedProbeAndAwait") < source.index("Unregister-ScheduledTask -TaskName $probeName", source.index("rollbackMayMutate"))
    assert "task/control/root rollback withheld because probe quiescence was not proven" in source
    assert "if ($rollbackMayMutate -and $controlChanged)" in source
    assert "if ($rollbackMayMutate -and $mutated)" in source
    assert "& $python -B -s -E $dispatcher activate" in source
    assert "[ScriptBlock]::Create($coreText)" in source
    assert "FileShare]::Read" in source
    assert "ALREADY_INSTALLED" in source
    assert "Restore-ArTrustedControlRootAtomic" in source
    assert "rollbackErrors.Add" in source
    assert "PRESTATE_REJECTED" in source
    assert "rollback-task.sddl" in source
    assert "pre-bootstrap-control.sddl" in source
    assert "pre-execution-observed.json" in source
    assert "post-bootstrap-catalog.json" in source
    assert "invocation_contract_sha256" in source
    assert "RESTORE_TASK_CONTROL_AND_QUARANTINE_V1" in source
    assert "Set-ArTrustedDeviationAuthorization" in source
    assert "deviations = @($script:authorizedDeviations)" in source
    assert "ExpectedControlSddlSha256" in source
    assert "ROLLBACK_QUARANTINE_NEW_ROOT" in source
    assert "Join-Path $env:ProgramFiles ('ARLBS-'" in source
    assert source.count("Move-ArTrustedFailedRootToQuarantine -Path") >= 2
    assert "PUBLISH_SHORT_PROTECTED_QUARANTINE" in core
    assert "Set-ArTrustedRootAcl -Root $path -OperatorSid $OperatorSid" in core
    assert core.index("'/grant:r' $treeGrants") < core.index("'/inheritance:r' '/T' '/C'")
    assert "Assert-ArTrustedShortQuarantineState" in source
    assert "Short quarantine reconciliation requires the global bootstrap gate" in core
    assert "RECOVERY_QUARANTINE_ORPHANED_STAGING" in core
    gate_after_evidence = source.index("Enter-ArTrustedBootstrapGate", source.index("$preservedPreExecution"))
    assert gate_after_evidence < source.index("Assert-ArTrustedShortQuarantineState")
    assert source.count("Enter-ArTrustedBootstrapGate") == 2
    assert "RECOVERY_COMPLETE_SHORT_PROTECTED_QUARANTINE" in core
    assert "Unjournaled short bootstrap or quarantine root exists" in core
    assert "Short quarantine source and destination both exist" in core
    assert "source_journal_prefix_sha256" in core
    assert "source_journal_prefix_bytes" in core
    assert "RECOVERY_SEAL_LEGACY_JOURNAL" in core
    assert "RECOVERY_SEAL_ORPHANED_STAGING" in core
    assert "legacy_closed_staging" in core
    assert "Legacy long staging source still exists" in core
    assert "short-quarantine-reconciliation.json" in core
    assert "quarantined-root-" in core
    assert "Write-ArTrustedFailureObserved" in core
    assert "failed-protected-root-" not in source
    assert core.count("failed-protected-root-") == 1
    assert "ROLLBACK_REMOVE_NEW_ROOT" not in source
    assert "Backup lock, transition lease, or partial residue exists" in source
    assert "dispatcherManifest.allowed_target_root" in source
    assert "dispatcherManifest.allowed_recovery_root" in source
    assert "dispatcher validate --control-root $ControlRoot --manifest" in source
    assert source.index("dispatcher validate --control-root $ControlRoot --manifest") < source.index("Disable-ScheduledTask -TaskName $TaskName")
    assert source.index("$catalogBaseline = Assert-ArTrustedCatalogBaseline") < source.index("Disable-ScheduledTask -TaskName $TaskName")
    assert source.count("Assert-ArTrustedCatalogBaseline @catalogArguments") >= 3
    assert source.index("Assert-ArTrustedBackupQuiescence -RequireReadyTask") < source.index("Write-ArTrustedResult -Result 'PASS'", source.index("ENABLE_PRODUCTION_TASK_WITHOUT_START"))
    assert gate_after_evidence < source.index("Enable-ScheduledTask -TaskName $TaskName")
    terminal_pass = source.index("Write-ArTrustedResult -Result 'PASS'", source.index("ENABLE_PRODUCTION_TASK_WITHOUT_START"))
    assert source.index("Prepare-ArTrustedBootstrapPublication", source.index("ENABLE_PRODUCTION_TASK_WITHOUT_START")) < terminal_pass
    assert terminal_pass < source.index("Publish-ArTrustedBootstrapReadiness -ResultPath $result")
    assert "PUBLISH_DURABLE_BOOTSTRAP_RESULT" in source
    publish_function = source[source.index("function Publish-ArTrustedBootstrapReadiness"):source.index("function Assert-ArExactInstalledBootstrap")]
    assert "Write-ArMutationIntent" not in publish_function
    assert "bootstrap-result.json.pending" in source
    assert "bootstrap.ready.pending" in source
    assert "Move-ArTrustedFileWriteThrough -Source $pendingResult -Destination $fixedResult" in source
    assert "Move-ArTrustedFileWriteThrough -Source $pendingReady -Destination $readyMarker" in source
    assert "ArTrustedMoveFile" in core
    assert "0x00000008" in core
    assert "Assert-ArTrustedBootstrapResultIdentity" in source
    assert "Protected bootstrap readiness exists without its durable PASS result" in source
    assert source.count("Flush($true)") >= 4
    assert "installed-task-sddl-semantic.sha256" in source
    assert "Installed task SDDL differs from its protected semantic seal" in source
    assert "bootstrap.installing.json" in source
    assert "Read-ArTrustedInterruptedBootstrap" in source
    assert "RECOVERY_RESTORE_CONTROL_PRESTATE" in source
    assert "RECOVERY_RESTORE_PRODUCTION_TASK_PRESTATE" in source
    assert "RECOVERY_QUARANTINE_INTERRUPTED_ROOT" in source
    assert source.index("REMOVE_INTERRUPTED_RECOVERY_MARKER") < source.index(
        "Write-ArTrustedResult -Result 'PASS'", source.index("ENABLE_PRODUCTION_TASK_WITHOUT_START")
    )
    assert "Trusted operator lacks read and execute access" in core
    assert "Trusted administrator principal lacks full control" in core
    assert "Trusted package owner is not Administrators" in core
    assert "Catalog baseline entry digest is invalid" in core
    assert "GIT_CONFIG_VALUE_0" in source
    assert len((ROOT / "laptop_backup_dispatcher.py").read_text(encoding="utf-8").splitlines()) < 1000
    assert len((ROOT / "laptop_pull_backup.py").read_text(encoding="utf-8").splitlines()) < 1000
    assert len((ROOT / "laptop_backup_dispatcher_security.py").read_text(encoding="utf-8").splitlines()) < 800
    assert len((ROOT / "tests/test_laptop_pull_backup.py").read_text(encoding="utf-8").splitlines()) < 1000
    task_runner = (ROOT / "run_laptop_backup_task.ps1").read_text(encoding="utf-8")
    assert "& $PythonPath -B $ScriptPath" in task_runner


def test_short_protected_roots_fit_the_observed_package_under_legacy_max_path() -> None:
    source = (ROOT / "install_laptop_backup_trusted_dispatcher.ps1").read_text(encoding="utf-8")
    longest_observed_relative_path = PureWindowsPath(
        "python/Lib/site-packages/jsonschema_specifications/schemas/draft202012/"
        "vocabularies/format-annotation"
    )
    roots = (
        PureWindowsPath("C:/Program Files") / ("ARLBS-" + "0" * 32),
        PureWindowsPath("C:/Program Files") / ("ARLBQ-" + "0" * 32),
    )
    assert max(len(str(root / longest_observed_relative_path)) for root in roots) < 248
    assert "$InstallRoot + '.staging-'" not in source


@pytest.mark.skipif(os.name != "nt", reason="Windows write-through publication contract")
def test_core_write_through_move_is_executable(tmp_path: Path) -> None:
    source = tmp_path / "bootstrap-result.json.pending"
    destination = tmp_path / "bootstrap-result.json"
    source.write_bytes(b"PASS\n")
    core = str(ROOT / "install_laptop_backup_trusted_dispatcher_core.ps1").replace("'", "''")
    source_arg = str(source).replace("'", "''")
    destination_arg = str(destination).replace("'", "''")
    command = (
        f". '{core}'; "
        f"Move-ArTrustedFileWriteThrough -Source '{source_arg}' -Destination '{destination_arg}'"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], check=True)
    assert not source.exists()
    assert destination.read_bytes() == b"PASS\n"


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
    assert "FIXED_SSH_HOST_KEY_SHA256" in source


def test_package_builder_makes_standalone_exact_checkouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def repo(name: str) -> tuple[Path, str]:
        path = tmp_path / name
        path.mkdir()
        subprocess.run(("git", "init", "-q", str(path)), check=True)
        subprocess.run(("git", "-C", str(path), "config", "user.email", "test@example.invalid"), check=True)
        subprocess.run(("git", "-C", str(path), "config", "user.name", "test"), check=True)
        for filename in (
            "run_laptop_backup_trusted_child.ps1", "laptop_backup_dispatcher.py",
            "laptop_backup_dispatcher_security.py", "laptop_backup_atomic.py",
        ):
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
    identity = tmp_path / "id"
    identity.write_bytes(
        b"-----BEGIN OPENSSH PRIVATE KEY-----\nTEST\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("192.168.20.19 ssh-ed25519 QUJDRA==\n", encoding="ascii")
    monkeypatch.setattr(
        trusted_package, "FIXED_SSH_HOST_KEY_SHA256",
        trusted_package.hashlib.sha256(b"192.168.20.19 ssh-ed25519 QUJDRA==\n").hexdigest(),
    )
    output = tmp_path / "trusted.zip"
    result = build(argparse.Namespace(
        candidate_repo=str(candidate), candidate_sha=candidate_sha,
        authority_repo=str(authority), authority_sha=authority_sha,
        python_root=str(runtime), launcher=str(launcher), dispatcher_manifest=str(dispatcher_manifest),
        install_root=str(tmp_path / "installed"), control_root=str(tmp_path / "control"),
        operator_sid="S-1-5-21-1-2-3-1001", git=str(tools[0]), ssh=str(tools[1]), scp=str(tools[2]),
        whoami=str(tools[3]), ssh_host="192.168.20.19", ssh_user="pi", ssh_port=22,
        ssh_identity=str(identity), ssh_known_hosts=str(known_hosts), output=str(output),
    ))
    assert result["sha256"]
    second = tmp_path / "trusted-second.zip"
    second_result = build(argparse.Namespace(
        candidate_repo=str(candidate), candidate_sha=candidate_sha,
        authority_repo=str(authority), authority_sha=authority_sha,
        python_root=str(runtime), launcher=str(launcher), dispatcher_manifest=str(dispatcher_manifest),
        install_root=str(tmp_path / "installed"), control_root=str(tmp_path / "control"),
        operator_sid="S-1-5-21-1-2-3-1001", git=str(tools[0]), ssh=str(tools[1]), scp=str(tools[2]),
        whoami=str(tools[3]), ssh_host="192.168.20.19", ssh_user="pi", ssh_port=22,
        ssh_identity=str(identity), ssh_known_hosts=str(known_hosts), output=str(second),
    ))
    assert second_result["sha256"] == result["sha256"]
    with pytest.raises(ValueError, match="fixed backup endpoint"):
        build(argparse.Namespace(
            candidate_repo=str(candidate), candidate_sha=candidate_sha,
            authority_repo=str(authority), authority_sha=authority_sha,
            python_root=str(runtime), launcher=str(launcher), dispatcher_manifest=str(dispatcher_manifest),
            install_root=str(tmp_path / "installed"), control_root=str(tmp_path / "control"),
            operator_sid="S-1-5-21-1-2-3-1001", git=str(tools[0]), ssh=str(tools[1]), scp=str(tools[2]),
            whoami=str(tools[3]), ssh_host="example.invalid", ssh_user="pi", ssh_port=22,
            ssh_identity=str(identity), ssh_known_hosts=str(known_hosts), output=str(tmp_path / "drift.zip"),
        ))
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        package = json.loads(archive.read("package-manifest.json"))
        assert "receiver/.git/HEAD" in names
        assert "authority/.git/HEAD" in names
        assert "python/unsafe.pth" not in names
        assert "python/sitecustomize.py" not in names
        assert package["candidate_code_sha"] == candidate_sha
        assert package["authority_commit"] == authority_sha
        trusted = json.loads(archive.read("trusted-child.json"))
        assert trusted["schema_version"] == 5
        assert trusted["ssh_host"] == "192.168.20.19"
        assert "laptop_backup_dispatcher_security.py" in names
        assert trusted["dispatcher_security_path"] == str(
            Path(tmp_path / "installed") / "laptop_backup_dispatcher_security.py"
        )
        assert trusted["dispatcher_security_sha256"] == package["files"]["laptop_backup_dispatcher_security.py"]
        assert "ssh/id" not in names
        assert all(b"OPENSSH PRIVATE KEY" not in archive.read(name) for name in names)
        assert archive.read("ssh/known_hosts") == b"192.168.20.19 ssh-ed25519 QUJDRA==\n"
        assert set(package["files"]) == names - {"package-manifest.json"}
