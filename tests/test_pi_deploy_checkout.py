"""Raw checkout binding rejects masked files without running Git filters."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pi_deploy_checkout import checkout_binding, inline_program


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "core.autocrlf", "false")
    git(tmp_path, "config", "core.filemode", "false" if os.name == "nt" else "true")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "runtime.py").write_bytes(b"checked source\n")
    git(tmp_path, "add", "runtime.py")
    git(tmp_path, "commit", "-m", "source")
    return tmp_path


def metadata(repo):
    return {str(p.relative_to(repo)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in (repo / ".git").rglob("*") if p.is_file()}


def test_clean_binding_preserves_all_git_metadata(repo):
    before = metadata(repo)
    assert checkout_binding(repo) == {"head": git(repo, "rev-parse", "HEAD").decode().strip(),
                                    "tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip(), "clean": True}
    assert metadata(repo) == before


def test_inline_observer_supports_old_checkout_without_helper(repo):
    assert not (repo / "pi_deploy_checkout.py").exists()
    before = metadata(repo)
    observed = subprocess.run([sys.executable, "-I", "-B", "-c", inline_program(), str(repo)],
                              check=True, capture_output=True, text=True, timeout=25)
    assert '"clean":true' in observed.stdout
    assert metadata(repo) == before
    assert not (repo / "__pycache__").exists()


@pytest.mark.parametrize("mutation", ["dirty", "staged", "untracked", "assume-unchanged", "skip-worktree", "deleted"])
def test_incomplete_or_masked_checkout_rejected(repo, mutation):
    if mutation in {"dirty", "staged"}:
        (repo / "runtime.py").write_bytes(b"different\n")
        if mutation == "staged": git(repo, "add", "runtime.py")
    if mutation == "untracked": (repo / "unknown.py").write_bytes(b"new")
    if mutation in {"assume-unchanged", "skip-worktree"}: git(repo, "update-index", "--" + mutation, "runtime.py")
    if mutation == "deleted": (repo / "runtime.py").unlink()
    with pytest.raises((ValueError, OSError)):
        checkout_binding(repo)


def test_external_clean_filter_is_never_invoked(repo):
    (repo / ".gitattributes").write_bytes(b"runtime.py filter=trap\n")
    git(repo, "add", ".gitattributes")
    git(repo, "commit", "-m", "attributes")
    git(repo, "config", "filter.trap.clean", "touch FILTER_RAN")
    git(repo, "config", "filter.trap.required", "true")
    (repo / "runtime.py").write_bytes(b"different\n")
    with pytest.raises(ValueError, match="tracked bytes"):
        checkout_binding(repo)
    assert not (repo / "FILTER_RAN").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file and symlink mode contract")
def test_symlink_and_executable_modes_are_verified(repo):
    os.symlink("runtime.py", repo / "link")
    (repo / "runtime.py").chmod(0o755)
    git(repo, "add", "runtime.py", "link")
    git(repo, "commit", "-m", "modes")
    assert checkout_binding(repo)["clean"]
    (repo / "runtime.py").chmod(0o644)
    with pytest.raises(ValueError, match="executable"):
        checkout_binding(repo)
