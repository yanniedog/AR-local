"""Break-glass + audit controls on the destructive cleanup utility.

cleanup_removed_cdr_sector rmtree/unlink/DROP-TABLEs inside finalized partition
dirs, so --apply must be guarded (two-factor) and audited per the ledger invariant.
"""

import json

import pytest

import cleanup_removed_cdr_sector as cc

ENV = cc.BREAK_GLASS_ENV


@pytest.mark.parametrize(
    "apply,break_glass,env,expected",
    [
        (False, False, None, True),   # dry-run always allowed
        (False, True, "1", True),     # dry-run ignores the flags
        (True, False, "1", False),    # --apply without the flag
        (True, True, None, False),    # --apply without the env
        (True, True, "0", False),     # env not exactly "1"
        (True, True, "1", True),      # both factors present
    ],
)
def test_breakglass_authorized(apply, break_glass, env, expected):
    authorized, _reason = cc.breakglass_authorized(apply, break_glass, env)
    assert authorized is expected


def test_main_refuses_apply_without_breakglass(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    (tmp_path / "runs").mkdir()
    rc = cc.main(["--apply", "--data-root", str(tmp_path)])
    assert rc == 2
    assert not (tmp_path / cc.AUDIT_LOG_NAME).exists()


def test_main_refuses_apply_with_env_but_no_breakglass(tmp_path, monkeypatch):
    # The env factor alone must not authorize a destructive run.
    monkeypatch.setenv(ENV, "1")
    (tmp_path / "runs").mkdir()
    rc = cc.main(["--apply", "--data-root", str(tmp_path)])
    assert rc == 2
    assert not (tmp_path / cc.AUDIT_LOG_NAME).exists()


def test_main_refuses_apply_with_flag_but_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    (tmp_path / "runs").mkdir()
    rc = cc.main(["--apply", "--break-glass", "--data-root", str(tmp_path)])
    assert rc == 2


def test_main_dry_run_ok(tmp_path):
    (tmp_path / "runs").mkdir()
    assert cc.main(["--data-root", str(tmp_path)]) == 0


def test_main_apply_authorized_ok(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    (tmp_path / "runs").mkdir()
    # No retired-sector artifacts present -> 0 actions, exit 0, no audit log.
    assert cc.main(["--apply", "--break-glass", "--data-root", str(tmp_path)]) == 0
    assert not (tmp_path / cc.AUDIT_LOG_NAME).exists()


def test_main_apply_writes_audit_log_end_to_end(tmp_path, monkeypatch):
    # A retired-sector artifact yields a real destructive action; the run must
    # apply it AND leave an "applied" audit entry (preceded by a "planned" one).
    monkeypatch.setenv(ENV, "1")
    energy_dir = tmp_path / "runs" / "2026-05-13" / cc.REMOVED
    energy_dir.mkdir(parents=True)
    (energy_dir / "f.json").write_text("{}", encoding="utf-8")
    rc = cc.main(["--apply", "--break-glass", "--data-root", str(tmp_path)])
    assert rc == 0
    assert not energy_dir.exists()  # destructive action actually applied
    entries = [
        json.loads(line)
        for line in (tmp_path / cc.AUDIT_LOG_NAME).read_text(encoding="utf-8").strip().splitlines()
    ]
    phases = [e["phase"] for e in entries]
    assert "planned" in phases  # preflight intent recorded before mutation
    applied = [e for e in entries if e["phase"] == "applied"]
    assert len(applied) == 1
    assert applied[0]["success"] is True and applied[0]["action_count"] >= 1


def test_write_audit_log_appends_json_line(tmp_path):
    log = cc.write_audit_log(tmp_path, ["remove x", "migrate y"], phase="applied")
    cc.write_audit_log(tmp_path, ["remove z"], phase="applied", success=False)
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["action_count"] == 2 and first["actions"] == ["remove x", "migrate y"]
    assert first["tool"] == "cleanup_removed_cdr_sector"
    assert first["phase"] == "applied" and first["success"] is True
    assert json.loads(lines[1])["success"] is False
