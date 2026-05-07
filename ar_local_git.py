"""Git fetch / upstream / pull helpers for the local launcher."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from ar_local_subprocess import run_capture, run_checked


def git_prep_fetch(repo_root: Path) -> Tuple[bool, str]:
    try:
        run_capture(["git", "rev-parse", "--git-dir"], cwd=repo_root)
    except RuntimeError:
        return False, "Not a git checkout."
    try:
        run_capture(["git", "remote", "get-url", "origin"], cwd=repo_root)
    except RuntimeError:
        return False, "No git remote 'origin'."
    try:
        proc = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "git fetch failed").strip()
            return False, msg
    except OSError as e:
        return False, f"git fetch failed: {e}"
    return True, ""


def git_status_dirty(repo_root: Path) -> bool:
    try:
        out = run_capture(["git", "status", "--porcelain"], cwd=repo_root)
    except RuntimeError:
        return True
    return bool(out.strip())


def git_default_remote_ref(repo_root: Path) -> Optional[str]:
    try:
        sym = run_capture(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_root).strip()
        if sym.startswith("refs/remotes/"):
            return sym.split("refs/remotes/", 1)[1]
    except RuntimeError:
        pass
    for candidate in ("origin/main", "origin/master"):
        try:
            subprocess.run(
                ["git", "rev-parse", candidate],
                cwd=str(repo_root),
                capture_output=True,
                check=True,
                shell=False,
            )
            return candidate
        except subprocess.CalledProcessError:
            continue
    return None


def git_compare_upstream(repo_root: Path) -> Tuple[Optional[int], Optional[str], str]:
    ok, err = git_prep_fetch(repo_root)
    if not ok:
        return None, None, err
    upstream: Optional[str] = None
    try:
        upstream = run_capture(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], cwd=repo_root)
    except RuntimeError:
        pass
    if not upstream or upstream == "HEAD":
        ref = git_default_remote_ref(repo_root)
        if not ref:
            return None, None, "Cannot determine origin default branch."
        upstream = ref
    try:
        behind_txt = run_capture(["git", "rev-list", "--count", f"HEAD..{upstream}"], cwd=repo_root)
        ahead_txt = run_capture(["git", "rev-list", "--count", f"{upstream}..HEAD"], cwd=repo_root)
        behind = int(behind_txt)
        ahead = int(ahead_txt)
    except (RuntimeError, ValueError) as e:
        return None, upstream, str(e)
    if behind == 0 and ahead == 0:
        return 0, upstream, f"Up to date with {upstream}."
    if behind > 0 and ahead == 0:
        return behind, upstream, f"Update available: {behind} commit(s) behind {upstream}."
    if ahead > 0 and behind == 0:
        return 0, upstream, f"Local branch is {ahead} commit(s) ahead of {upstream} (no pull needed)."
    return (
        behind,
        upstream,
        f"Diverged: {behind} behind, {ahead} ahead of {upstream}. git pull --ff-only may fail.",
    )


def git_pull_ff_only(repo_root: Path) -> None:
    if git_status_dirty(repo_root):
        print("Working tree is dirty. Commit or stash before updating.", file=sys.stderr)
        raise SystemExit(1)
    upstream: Optional[str] = None
    try:
        upstream = run_capture(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], cwd=repo_root)
    except RuntimeError:
        upstream = None
    if not upstream or upstream == "HEAD":
        ref = git_default_remote_ref(repo_root)
        if not ref:
            print("No upstream branch; set branch tracking or pull manually.", file=sys.stderr)
            raise SystemExit(1)
        run_checked(
            ["git", "pull", "--ff-only", "origin", ref.split("/", 1)[-1]],
            cwd=repo_root,
        )
        return
    run_checked(["git", "pull", "--ff-only"], cwd=repo_root)
