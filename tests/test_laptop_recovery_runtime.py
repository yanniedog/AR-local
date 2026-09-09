import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

import laptop_recovery_runtime as runtime


SOURCE = Path(runtime.__file__).resolve()


def test_msys_reader_changes_only_path_syntax_and_preserves_strict_auth(monkeypatch):
    pins = {'ssh_user': 'pi', 'ssh_port': 22, 'ssh_logical_host': 'ar-local-pi5',
            'ssh_null_device': '/dev/null'}
    for name in ('ssh', 'ssh_identity', 'ssh_known_hosts'):
        pins[name + '_path'] = 'C:\\private\\' + name
        pins[name + '_sha256'] = 'a' * 64
    monkeypatch.setattr(runtime, 'digest', lambda path: 'a' * 64)
    config = {'transport': pins, 'lan_fallback_ipv4': '192.168.20.19'}
    args = runtime.ssh_prefix(config)
    assert args[:3] == [pins['ssh_path'], '-F', '/dev/null']
    assert 'UserKnownHostsFile=C:/private/ssh_known_hosts' in args
    assert 'GlobalKnownHostsFile=/dev/null' in args
    assert 'StrictHostKeyChecking=yes' in args and 'IdentityAgent=none' in args
    pins['ssh_null_device'] = '/unexpected/config'
    with pytest.raises(ValueError, match='null device'):
        runtime.ssh_prefix(config)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "tracked").write_text("original")
    git(tmp_path, "add", "tracked")
    git(tmp_path, "commit", "-qm", "fixture")
    return git(tmp_path, "rev-parse", "HEAD")


def test_untracked_configuration_cannot_hide_a_dirty_checkout(tmp_path):
    head = repository(tmp_path)
    git(tmp_path, "config", "status.showUntrackedFiles", "no")
    (tmp_path / "unexpected.py").write_text("unexpected code")
    with pytest.raises(ValueError, match="dirty"):
        runtime.verify_git("git", str(tmp_path), head)


def test_status_does_not_refresh_index_even_with_stale_stat(tmp_path):
    head = repository(tmp_path)
    path = tmp_path / "tracked"
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))
    index = tmp_path / ".git/index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    assert runtime.verify_git("git", str(tmp_path), head) == head
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before


def test_git_environment_cannot_redirect_repository(tmp_path, monkeypatch):
    head = repository(tmp_path)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "missing.git"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "status.showUntrackedFiles")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "no")
    assert runtime.verify_git("git", str(tmp_path), head) == head


@pytest.mark.parametrize("observed", ["wrong commit", "dirty"])
def test_explicit_failures_survive_optimized_python(observed):
    code = '''import sys
scope = {"__name__": "runtime_test", "__file__": sys.argv[1]}
exec(compile(open(sys.argv[1], "rb").read(), sys.argv[1], "exec"), scope)
values = iter(["unused", "H tracked", "wrong" if sys.argv[2] == "wrong commit" else "expected", "?? dirty"])
try:
    scope["verify_git"]("git", "unused", "expected", lambda argv: next(values))
except ValueError:
    sys.exit(0)
sys.exit(7)
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-O", "-c", code,
                             str(SOURCE), observed], capture_output=True)
    assert result.returncode == 0, result.stderr


def test_entrypoint_ignores_receiver_bytecode_and_python_environment(tmp_path):
    import py_compile
    fake = tmp_path / "laptop_backup_user_session.py"
    fake.write_text("raise RuntimeError('unverified receiver executed')")
    py_compile.compile(str(fake), invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    config = tmp_path / "config.json"
    config.write_text("{}")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    env = dict(os.environ, PYTHONOPTIMIZE="2", PYTHONPATH=str(tmp_path))
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(SOURCE),
                             "--config", str(config), "--config-sha256", "0" * 64,
                             "--receiver-sha", "1" * 40, "--production-sha", "2" * 40],
                            env=env, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert '"runtime_binding": "FAIL"' in result.stdout
    assert "configuration changed" in result.stdout
    assert "unverified receiver" not in result.stderr
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_wrong_config_digest_fails_before_using_paths(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"receiver":"should never be read"}')
    with pytest.raises(ValueError, match="configuration changed"):
        runtime.verify(path, "0" * 64, "1" * 40, "2" * 40)


def test_repository_core_worktree_cannot_redirect_cleanliness(tmp_path):
    actual = tmp_path / "actual"
    other = tmp_path / "other"
    actual.mkdir()
    other.mkdir()
    head = repository(actual)
    (other / "tracked").write_text("original")
    git(actual, "config", "core.worktree", str(other))
    (actual / "tracked").write_text("changed")
    with pytest.raises(ValueError, match="worktree differs"):
        runtime.verify_git("git", str(actual), head)


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_index_flags_cannot_hide_tracked_changes(tmp_path, flag):
    head = repository(tmp_path)
    git(tmp_path, "update-index", flag, "tracked")
    (tmp_path / "tracked").write_text("changed")
    with pytest.raises(ValueError, match="index flags"):
        runtime.verify_git("git", str(tmp_path), head)
