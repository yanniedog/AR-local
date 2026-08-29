"""Windows command adapter for the controlled laptop-backup transition."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

import laptop_backup_scheduled as scheduled


HOBART = ZoneInfo("Australia/Hobart")


class OpsConfig(Protocol):
    target: Path
    recovery_image: Path
    receiver: Path
    old_receiver: Path
    old_task_xml: Path
    candidate_code_sha: str
    old_candidate_code_sha: str
    protected_code_sha: str
    plan_git_commit: str
    expected_observation_date: str
    operator: str
    python_path: Path
    old_python_path: Path
    task_name: str
    deadline: datetime
    host: str


@dataclass(frozen=True)
class CommandOutput:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def checked(
    command: Sequence[str], *, cwd: Path | None = None, timeout: int = 300
) -> CommandOutput:
    completed = subprocess.run(
        tuple(command), cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False
    )
    result = CommandOutput(tuple(command), completed.returncode, completed.stdout, completed.stderr)
    if result.returncode:
        raise RuntimeError(
            f"native command failed ({result.returncode}): "
            f"{subprocess.list2cmdline(result.command)}\n{result.stderr or result.stdout}"
        )
    return result


class WindowsOps:
    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parent
        self.task_script = self.root / "laptop_backup_task_transition.ps1"
        self._commands: list[str] = []
        self._installer_stdout = ""

    def _task_command(
        self,
        action: str,
        config: OpsConfig,
        old_xml: Path | None,
        transition_id: str | None = None,
    ) -> list[str]:
        command = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(self.task_script), "-Action", action, "-TaskName", config.task_name,
        ]
        if action == "Install":
            if not transition_id:
                raise ValueError("task install lacks transition identity")
            command.extend((
                "-Receiver", str(config.receiver), "-Target", str(config.target),
                "-RecoveryImage", str(config.recovery_image), "-CandidateCodeSha",
                config.candidate_code_sha, "-ProtectedCodeSha", config.protected_code_sha,
                "-PlanGitCommit", config.plan_git_commit, "-Operator", config.operator,
                "-PythonPath", str(config.python_path), "-TransitionId", transition_id,
            ))
        if action == "RestoreDisabled":
            if old_xml is None:
                raise ValueError("task restore lacks preserved XML")
            command.extend(("-OldTaskXmlPath", str(old_xml)))
        return command

    def task(
        self,
        action: str,
        config: OpsConfig,
        old_xml: Path | None = None,
        transition_id: str | None = None,
    ) -> Mapping[str, object]:
        command = self._task_command(action, config, old_xml, transition_id)
        self._commands.append(subprocess.list2cmdline(command))
        result = checked(command, timeout=600)
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("task helper returned invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise ValueError("task helper returned a non-object")
        if action == "Install":
            task, output = value.get("task"), value.get("installer_stdout")
            if not isinstance(task, Mapping) or not isinstance(output, str):
                raise ValueError("installer helper result is incomplete")
            self._installer_stdout = output
            return task
        return value

    def source_listing(self, config: OpsConfig) -> Mapping[str, object]:
        namespace = argparse.Namespace(
            target=config.target, host=config.host,
            source_helper=config.receiver / "pi_laptop_backup_source.py",
            recovery_image=config.recovery_image, candidate_code_sha=config.candidate_code_sha,
            protected_code_sha=config.protected_code_sha, plan_git_commit=config.plan_git_commit,
            operator=config.operator,
        )
        self._commands.append(
            f"invoke_receiver preflight --host {config.host} "
            f"--candidate-code-sha {config.candidate_code_sha}"
        )
        code, stdout, stderr = scheduled.invoke_receiver(namespace, "preflight")
        if code:
            raise RuntimeError(f"Pi backup preflight failed: {stderr or stdout}")
        value = json.loads(stdout)
        if not isinstance(value, Mapping):
            raise ValueError("Pi backup preflight returned a non-object")
        return value

    def run_scheduled(
        self, config: OpsConfig, *, check_only: bool, transition_id: str
    ) -> CommandOutput:
        command = self._scheduled_command(
            config, check_only=check_only, transition_id=transition_id
        )
        self._commands.append(subprocess.list2cmdline(command))
        timeout = max(1, min(5400, int((config.deadline - self.now()).total_seconds())))
        return checked(command, cwd=config.receiver, timeout=timeout)

    def _scheduled_command(
        self, config: OpsConfig, *, check_only: bool, transition_id: str
    ) -> list[str]:
        command = [
            str(config.python_path), str(config.receiver / "laptop_backup_scheduled.py"),
            "--target", str(config.target), "--host", config.host, "--recovery-image",
            str(config.recovery_image), "--candidate-code-sha", config.candidate_code_sha,
            "--protected-code-sha", config.protected_code_sha, "--plan-git-commit",
            config.plan_git_commit, "--operator", config.operator, "--transition-id", transition_id,
        ]
        if check_only:
            command.append("--check-only")
        return command

    def active_backup_processes(self) -> Sequence[Mapping[str, object]]:
        script = (
            "$p=@(Get-CimInstance Win32_Process -ErrorAction Stop | "
            "Where-Object {$_.ProcessId -ne $PID -and $_.CommandLine -match "
            "'laptop_backup_scheduled|laptop_pull_backup|run_laptop_backup_task'} | "
            "ForEach-Object {[ordered]@{pid=$_.ProcessId;command_line=$_.CommandLine}});"
            "$p|ConvertTo-Json -Depth 4 -Compress"
        )
        command = ("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script)
        self._commands.append(subprocess.list2cmdline(command))
        result = checked(command)
        if not result.stdout.strip():
            return []
        value = json.loads(result.stdout)
        if isinstance(value, Mapping):
            return [value]
        if not isinstance(value, list):
            raise ValueError("process inventory is invalid")
        return value

    def installer_output(self) -> str:
        return self._installer_stdout

    def command_log(self) -> Sequence[str]:
        return tuple(self._commands)

    def planned_commands(self, config: OpsConfig, transition_id: str) -> Sequence[str]:
        commands = [
            self._task_command("Snapshot", config, None),
            self._task_command("Disable", config, None),
            self._scheduled_command(config, check_only=False, transition_id=transition_id),
            self._task_command("Install", config, None, transition_id),
            self._scheduled_command(config, check_only=True, transition_id=transition_id),
            self._task_command("RestoreDisabled", config, config.old_task_xml),
            self._task_command("Enable", config, None),
        ]
        return tuple(subprocess.list2cmdline(value) for value in commands)

    def now(self) -> datetime:
        return datetime.now(HOBART)
