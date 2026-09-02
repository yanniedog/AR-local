"""Focused A3 selective-diagnostic and process-safety tests."""

from __future__ import annotations

import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import laptop_backup_scheduled as scheduled
import laptop_pull_backup as receiver


CANDIDATE = "c" * 40
PROTECTED = "9" * 40


def test_scheduled_receiver_selects_only_stale_diagnostics(tmp_path: Path) -> None:
    args = Namespace(
        target=tmp_path,
        host="192.168.20.19",
        ssh_user="pi",
        ssh_port=22,
        ssh_path=r"C:\Windows\System32\OpenSSH\ssh.exe",
        ssh_sha256="a" * 64,
        scp_path=r"C:\Windows\System32\OpenSSH\scp.exe",
        scp_sha256="b" * 64,
        ssh_identity=r"C:\Program Files\AR-local\ssh\id",
        ssh_known_hosts=r"C:\Program Files\AR-local\ssh\known_hosts",
        recovery_image=tmp_path / "image",
        candidate_code_sha=CANDIDATE,
        protected_code_sha=PROTECTED,
        plan_git_commit=receiver.PLAN_GIT_COMMIT,
        source_helper=None,
        operator="pytest",
    )
    values = scheduled.receiver_arguments(
        args,
        "backup-latest",
        include_diagnostic_dates=["2026-08-22"],
    )
    assert values[-3:] == [
        "--select-diagnostics", "--include-diagnostic-date", "2026-08-22"
    ]


def test_backup_jobs_can_exclude_already_verified_diagnostics() -> None:
    retained = [
        {"date": "2026-08-22", "status": "diagnostic"},
        {"date": "2026-08-29", "status": "completed"},
    ]
    _latest, selected = receiver.backup_jobs(
        retained,
        "backup-latest",
        "2026-05-21",
        include_diagnostic_dates=[],
    )
    assert selected == [
        ("observation", "2026-08-29"),
        ("control", None),
        ("macro", None),
    ]


def test_windows_process_liveness_probe_does_not_terminate_target() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert receiver.process_alive(child.pid)
        assert child.poll() is None
        assert receiver.process_descends_from(child.pid, os.getpid())
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_process_ancestry_accepts_live_grandchild_without_signalling() -> None:
    script = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "print(p.pid,flush=True); "
        "\ntry: time.sleep(30)\nfinally: p.terminate(); p.wait()"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        grandchild_pid = int(child.stdout.readline().strip())
        assert receiver.process_descends_from(grandchild_pid, os.getpid())
        assert receiver.process_alive(grandchild_pid)
    finally:
        child.terminate()
        child.wait(timeout=10)
