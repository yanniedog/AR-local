"""Trusted subprocess helpers for the local launcher (argv from repo + literals only; never shell=True)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence


def run_checked(
    argv: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    r = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        env=merged,
        shell=False,
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(r.returncode)


def run_capture(argv: Sequence[str], cwd: Optional[Path] = None) -> str:
    r = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        shell=False,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}")
    return (r.stdout or "").strip()


def run_git(args: Sequence[str], repo_root: Path) -> str:
    return run_capture(["git", *args], cwd=repo_root)
