from datetime import datetime
from pathlib import Path
import json
import sqlite3
import shutil
import subprocess

import pytest

import laptop_backup_user_session as user
import laptop_backup_transport as transport
import laptop_pull_backup as receiver


@pytest.mark.parametrize("hour,allowed", [(0, False), (1, False), (5, False), (6, True),
                                        (13, True), (14, False), (22, False), (23, False)])
def test_start_window_leaves_runway(hour, allowed):
    assert user.allowed_start(datetime(2026, 9, 6, hour, tzinfo=user.HOBART)) is allowed


def test_utc_clock_is_converted_to_hobart():
    assert user.allowed_start(datetime.fromisoformat("2026-09-05T20:00:00+00:00"))
    assert not user.allowed_start(datetime.fromisoformat("2026-09-06T04:00:00+00:00"))


def test_targets_cannot_overlap(tmp_path):
    legacy = tmp_path / "legacy"
    for target in (legacy, legacy / "child", tmp_path):
        with pytest.raises(ValueError, match="disjoint"):
            user.separate_targets(target, legacy)
    user.separate_targets(tmp_path / "new", legacy)


@pytest.mark.parametrize("state", ["Unknown", "Queued", "Running", "", "Unexpected"])
def test_legacy_task_non_idle_states_block(state, monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setattr(user.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=state))
    with pytest.raises(ValueError, match="cannot be verified"):
        user.legacy_idle("legacy")


@pytest.mark.parametrize("state", ["Ready", "Disabled"])
def test_legacy_task_idle_states_are_accepted(state, monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setattr(user.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=state))
    user.legacy_idle("legacy")


def test_duplicate_config_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"schema":1,"schema":2}', object_pairs_hook=user.strict_pairs)


def test_transport_requires_a_verified_user_runner(monkeypatch):
    monkeypatch.delenv("AR_USER_BACKUP_CONFIG_SHA256", raising=False)
    with pytest.raises(ValueError, match="verified runner"):
        user.transport_contract()


def test_absent_protected_contract_still_fails_without_user_config(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "__file__", str(tmp_path / "source/laptop_backup_transport.py"))
    with pytest.raises(ValueError, match="unavailable"):
        transport._trusted_contract("nt")


def test_user_contract_does_not_override_invalid_protected_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "__file__", str(tmp_path / "source/laptop_backup_transport.py"))
    (tmp_path / "trusted-child.json").write_text('{}')
    (tmp_path / user.CONFIG_NAME).write_text('{}')
    monkeypatch.setattr(user, "transport_contract", lambda: pytest.fail("must not fall back"))
    with pytest.raises(ValueError, match="schema"):
        transport._trusted_contract("nt")


def test_sqlite_foreign_key_failure_is_not_accepted(tmp_path):
    with sqlite3.connect(tmp_path / "broken.sqlite") as db:
        db.executescript("CREATE TABLE p(id PRIMARY KEY); CREATE TABLE c(id REFERENCES p(id)); INSERT INTO c VALUES(4);")
    with pytest.raises(ValueError, match="foreign-key"):
        receiver.sqlite_checks(tmp_path)


def test_sqlite_all_checks_are_recorded(tmp_path):
    with sqlite3.connect(tmp_path / "valid.sqlite") as db:
        db.execute("CREATE TABLE p(id PRIMARY KEY)")
    report = receiver.sqlite_checks(tmp_path)[0]
    assert all(report[key] == "ok" for key in ("quick_check", "integrity_check", "foreign_key_check"))


def test_elevated_user_session_is_rejected(monkeypatch):
    # Exercise the identity gate without any Task Scheduler or token mutation.
    from types import SimpleNamespace
    monkeypatch.setattr(user.os, "name", "nt")
    monkeypatch.setattr(user.ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False)
    with pytest.raises(ValueError, match="elevated"):
        user.ordinary_identity()


@pytest.mark.parametrize("shell", ["powershell", "pwsh"])
def test_user_session_scripts_parse_in_available_powershell_hosts(shell, tmp_path):
    executable = shutil.which(shell)
    if not executable:
        pytest.skip(f"{shell} is unavailable on this platform")
    parser = tmp_path / "parse.ps1"
    parser.write_text("foreach($p in $args){$t=$null;$e=$null;"
                      "[Management.Automation.Language.Parser]::ParseFile($p,[ref]$t,[ref]$e)|Out-Null;"
                      "if($e.Count){$e|Out-String|Write-Error;exit 1}}", encoding="utf-8")
    root = Path(user.__file__).parent
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(parser),
                             str(root / "install_laptop_backup_user_session.ps1"),
                             str(root / "run_laptop_backup_user_session.ps1")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
