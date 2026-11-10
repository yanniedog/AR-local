"""Drive-evidence deployment gate: admits only on a current day archive plus a fresh, Drive-verified backup."""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import pi_drive_evidence_gate as gate

P, C = "a" * 40, "b" * 40
NOW = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)  # 22:00 Hobart, 10 Nov


def _setup(tmp_path: Path, archive_date: str = "2026-11-10") -> dict:
    spool = tmp_path / "spool"
    (spool / "meta").mkdir(parents=True)
    row = {"kind": "day", "date": archive_date, "coverage": "wire_raw", "bytes": 5, "remote_name": f"{archive_date}.tar.zst",
           "generation_id": "g", "recorded_at": "x"}
    (spool / "meta" / "raw-progress.jsonl").write_text("not json\n" + json.dumps(row) + "\n", encoding="utf-8")
    env = tmp_path / "day-archive.env"
    env.write_text(f'AR_LOCAL_DAY_ARCHIVE_SPOOL={spool}\nAR_LOCAL_DAY_ARCHIVE_REMOTE="r:Root Folder/daily"\n'
                   f"RCLONE_CONFIG={tmp_path / 'rclone.conf'}\n", encoding="utf-8")
    repo, site, data = tmp_path / "repo", tmp_path / "site", tmp_path / "data"
    for path in (repo, site, data / "state"):
        path.mkdir(parents=True)
        (path / "f.txt").write_text(path.name, encoding="utf-8")
    return {"env": env, "spool": spool, "repo": repo, "site": site, "data": data}


def _runner(fail: str | None = None, corrupt_readback: bool = False):
    calls = []

    def run(argv, timeout):
        calls.append(list(argv))
        if argv[0] == "tar":
            Path(argv[argv.index("-cf") + 1]).write_bytes(b"archive")
            return subprocess.CompletedProcess(argv, 0, "", "")
        verb = argv[3]
        if verb == fail:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        out = ""
        if verb == "cat":
            staged = Path(calls[-3][-2]) / "manifest.json"
            out = staged.read_text(encoding="utf-8") + ("x" if corrupt_readback else "")
        return subprocess.CompletedProcess(argv, 0, out, "")

    run.calls = calls
    return run


def _backup(ctx, run=None, now=NOW, monkeypatch=None):
    return gate.create_backup(ctx["repo"], ctx["site"], ctx["data"], P, C, env_path=ctx["env"], run=run or _runner(), now=now)


@pytest.fixture(autouse=True)
def _free_space(monkeypatch):
    monkeypatch.setattr(gate, "MIN_FREE_BYTES", 0)


def test_backup_then_gate_and_record_pass(tmp_path):
    ctx = _setup(tmp_path)
    run = _runner()
    receipt = _backup(ctx, run)
    assert receipt["ok"] and receipt["remote"].startswith("r:Root Folder/pre-deploy-backups/")
    assert [call[3] for call in run.calls if call[0] == "rclone"] == ["copy", "check", "cat"]
    assert not any((ctx["spool"] / "pre-deploy" / "staging").iterdir())
    report = gate.gate(P, C, env_path=ctx["env"], now=NOW + timedelta(hours=1))
    assert report["ok"] and report["restore_drill"] == "NOT_TESTED"
    assert gate.record("deployment", P, C, ["cmd"], env_path=ctx["env"], now=NOW)["result"] == "PASS"


@pytest.mark.parametrize("fail", ["copy", "check", "cat"])
def test_backup_blocks_when_drive_step_fails(tmp_path, fail):
    ctx = _setup(tmp_path)
    with pytest.raises(gate.Blocked):
        _backup(ctx, _runner(fail=fail))
    assert not (ctx["spool"] / "pre-deploy" / "latest.json").exists()


def test_backup_blocks_on_readback_mismatch(tmp_path):
    ctx = _setup(tmp_path)
    with pytest.raises(gate.Blocked, match="read-back"):
        _backup(ctx, _runner(corrupt_readback=True))


def test_stale_day_archive_blocks_backup_and_gate(tmp_path):
    ctx = _setup(tmp_path, archive_date="2026-11-08")
    with pytest.raises(gate.Blocked, match="2026-11-09 or later"):
        _backup(ctx)
    assert any(item.startswith("day_archive") for item in gate.gate(P, C, env_path=ctx["env"], now=NOW)["findings"])


def test_gate_rejects_other_commits_stale_backup_and_missing_receipt(tmp_path):
    ctx = _setup(tmp_path)
    assert "backup_receipt_missing_or_invalid" in gate.gate(P, C, env_path=ctx["env"], now=NOW)["findings"]
    _backup(ctx)
    assert "current_production_sha_not_backed_up" in gate.gate(C, C, env_path=ctx["env"], now=NOW)["findings"]
    assert "backup_bound_to_other_candidate" in gate.gate(P, P, env_path=ctx["env"], now=NOW)["findings"]
    assert "backup_stale_or_future" in gate.gate(P, C, env_path=ctx["env"], now=NOW + timedelta(hours=7))["findings"]
    with pytest.raises(gate.Blocked):
        gate.record("deployment", C, P, [], env_path=ctx["env"])


def test_tampered_latest_receipt_is_rejected(tmp_path):
    ctx = _setup(tmp_path)
    _backup(ctx)
    latest = ctx["spool"] / "pre-deploy" / "latest.json"
    value = json.loads(latest.read_text(encoding="utf-8"))
    value["protected_code_sha"] = C
    latest.write_text(json.dumps(value), encoding="utf-8")
    assert "backup_receipt_mismatch" in gate.gate(C, C, env_path=ctx["env"], now=NOW)["findings"]


def test_rejects_bad_sha_and_remote(tmp_path):
    ctx = _setup(tmp_path)
    with pytest.raises(gate.Blocked):
        gate.gate("abc", C, env_path=ctx["env"])
    ctx["env"].write_text(ctx["env"].read_text(encoding="utf-8").replace("r:Root Folder/daily", "r:daily"), encoding="utf-8")
    with pytest.raises(gate.Blocked, match="dedicated Drive root"):
        gate.gate(P, C, env_path=ctx["env"])
