"""Tests for ar_local_pi_ssh (roadmap-sourced SSH config install + smoke check)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ar_local_pi_ssh as pi_ssh  # noqa: E402

ROADMAP_BLOCK = """Host ar-local-pi5-lan
  HostName 192.168.20.19
  User pi
  IdentityFile ~/.ssh/pi5
  IdentitiesOnly yes
  HostKeyAlias 10.0.0.92

Host ar-local-pi5
  HostName 100.78.28.10
  User pi
"""


def write_roadmap(tmp_path: Path, block: str, heading: str = pi_ssh.ROADMAP_HEADING) -> Path:
    roadmap = tmp_path / "UNIVERSAL_ROADMAP.md"
    roadmap.write_text(
        "# Roadmap\n\n"
        "### Unrelated section\n\n```sshconfig\nHost decoy\n```\n\n"
        f"{heading}\n\nSome prose.\n\n```sshconfig\n{block}```\n\nMore prose.\n",
        encoding="utf-8",
    )
    return roadmap


def test_repo_roadmap_defines_the_lan_alias():
    block = pi_ssh.read_roadmap_ssh_block()
    aliases = pi_ssh.host_aliases(block)
    assert pi_ssh.DEFAULT_HOST in aliases
    assert "ar-local-pi5" in aliases


def test_read_roadmap_takes_the_block_under_the_ssh_heading(tmp_path):
    block = pi_ssh.read_roadmap_ssh_block(write_roadmap(tmp_path, ROADMAP_BLOCK))
    assert "Host decoy" not in block
    assert "HostName 192.168.20.19" in block


def test_read_roadmap_rejects_a_block_without_the_lan_alias(tmp_path):
    roadmap = write_roadmap(tmp_path, "Host somewhere-else\n  HostName 10.0.0.1\n")
    with pytest.raises(pi_ssh.ConfigError, match="does not define Host"):
        pi_ssh.read_roadmap_ssh_block(roadmap)


def test_read_roadmap_rejects_a_missing_heading(tmp_path):
    roadmap = write_roadmap(tmp_path, ROADMAP_BLOCK, heading="### Something else")
    with pytest.raises(pi_ssh.ConfigError, match="missing section"):
        pi_ssh.read_roadmap_ssh_block(roadmap)


def test_install_creates_config_with_restricted_permissions(tmp_path):
    path = tmp_path / ".ssh" / "config"
    pi_ssh.install_config(ROADMAP_BLOCK, path=path)
    text = path.read_text(encoding="utf-8")
    assert pi_ssh.BLOCK_BEGIN in text and pi_ssh.BLOCK_END in text
    assert "Host ar-local-pi5-lan" in text
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_install_is_idempotent_and_preserves_unrelated_entries(tmp_path):
    path = tmp_path / "config"
    path.write_text("Host github.com\n  User git\n", encoding="utf-8")
    pi_ssh.install_config(ROADMAP_BLOCK, path=path)
    first = path.read_text(encoding="utf-8")
    pi_ssh.install_config(ROADMAP_BLOCK, path=path)
    second = path.read_text(encoding="utf-8")
    assert first == second
    assert second.count(pi_ssh.BLOCK_BEGIN) == 1
    assert "Host github.com" in second


def test_install_refreshes_a_stale_managed_block(tmp_path):
    path = tmp_path / "config"
    pi_ssh.install_config("Host ar-local-pi5-lan\n  HostName 10.0.0.92\n", path=path)
    pi_ssh.install_config(ROADMAP_BLOCK, path=path)
    text = path.read_text(encoding="utf-8")
    assert "HostName 192.168.20.19" in text
    assert "10.0.0.92" not in text.split(pi_ssh.BLOCK_BEGIN)[1].split("HostKeyAlias")[0]


def test_install_refuses_to_shadow_an_existing_alias(tmp_path):
    path = tmp_path / "config"
    path.write_text("Host ar-local-pi5-lan\n  HostName 10.9.9.9\n", encoding="utf-8")
    with pytest.raises(pi_ssh.ConfigError, match="outside the managed block"):
        pi_ssh.install_config(ROADMAP_BLOCK, path=path)
    assert "10.9.9.9" in path.read_text(encoding="utf-8")


def test_install_force_overrides_the_conflict_guard(tmp_path):
    path = tmp_path / "config"
    path.write_text("Host ar-local-pi5-lan\n  HostName 10.9.9.9\n", encoding="utf-8")
    pi_ssh.install_config(ROADMAP_BLOCK, path=path, force=True)
    assert pi_ssh.BLOCK_BEGIN in path.read_text(encoding="utf-8")


def test_install_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "config"
    rendered = pi_ssh.install_config(ROADMAP_BLOCK, path=path, dry_run=True)
    assert "Host ar-local-pi5-lan" in rendered
    assert not path.exists()


def test_missing_identity_files_reports_absent_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert pi_ssh.missing_identity_files(ROADMAP_BLOCK) == ["~/.ssh/pi5"]
    key = tmp_path / ".ssh" / "pi5"
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text("key", encoding="utf-8")
    assert pi_ssh.missing_identity_files(ROADMAP_BLOCK) == []


def test_check_command_is_batch_mode_and_non_interactive():
    cmd = pi_ssh.check_command("ar-local-pi5-lan")
    assert cmd[0] == "ssh"
    assert "BatchMode=yes" in cmd
    assert cmd[-2] == "ar-local-pi5-lan"
    assert cmd[-1] == pi_ssh.CHECK_REMOTE_COMMAND


def test_ssh_config_path_honours_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AR_PI_SSH_CONFIG", str(tmp_path / "custom_config"))
    assert pi_ssh.ssh_config_path() == tmp_path / "custom_config"


def test_check_maps_transport_failure_to_exit_3(monkeypatch):
    class Proc:
        returncode = pi_ssh.SSH_TRANSPORT_EXIT
        stdout = ""
        stderr = "ssh: connect to host 192.168.20.19 port 22: Connection timed out"

    monkeypatch.setattr(pi_ssh.subprocess, "run", lambda *a, **k: Proc())
    assert pi_ssh.run_check("ar-local-pi5-lan") == pi_ssh.EXIT_SSH


def test_check_maps_remote_command_failure_to_exit_1(monkeypatch):
    class Proc:
        returncode = 7
        stdout = "pi5"
        stderr = "boom"

    monkeypatch.setattr(pi_ssh.subprocess, "run", lambda *a, **k: Proc())
    assert pi_ssh.run_check("ar-local-pi5-lan") == pi_ssh.EXIT_CHECK_FAIL


def test_check_success_returns_zero(monkeypatch):
    class Proc:
        returncode = 0
        stdout = "pi5\n192.168.20.19 100.78.28.10\n"
        stderr = ""

    monkeypatch.setattr(pi_ssh.subprocess, "run", lambda *a, **k: Proc())
    assert pi_ssh.run_check("ar-local-pi5-lan") == pi_ssh.EXIT_OK


def test_main_print_does_not_touch_the_config(monkeypatch, tmp_path, capsys):
    path = tmp_path / "config"
    monkeypatch.setenv("AR_PI_SSH_CONFIG", str(path))
    assert pi_ssh.main(["--print"]) == pi_ssh.EXIT_OK
    assert "Host ar-local-pi5-lan" in capsys.readouterr().out
    assert not path.exists()


def test_main_install_writes_the_override_path(monkeypatch, tmp_path):
    path = tmp_path / "nested" / "config"
    monkeypatch.setenv("AR_PI_SSH_CONFIG", str(path))
    assert pi_ssh.main(["--install"]) == pi_ssh.EXIT_OK
    assert "Host ar-local-pi5-lan" in path.read_text(encoding="utf-8")


def test_main_requires_an_action():
    with pytest.raises(SystemExit):
        pi_ssh.main([])
