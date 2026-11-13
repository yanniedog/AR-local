"""Drive-evidence deployment gate: admits only on a current day archive plus a fresh, Drive-verified backup."""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import pi_drive_evidence_gate as gate

P, C = "a" * 40, "b" * 40
NOW = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)  # 22:00 Hobart, 10 Nov


def _row(date: str, *, result: str = "PASS", coverage: str = "wire_raw", remote_name: str | None = None) -> dict:
    return {
        "kind": "day",
        "date": date,
        "result": result,
        "coverage": coverage,
        "bytes": 5,
        "remote_name": f"{date}.tar.zst" if remote_name is None else remote_name,
        "generation_id": "g",
        "recorded_at": "x",
    }


def _setup(tmp_path: Path, archive_date: str = "2026-11-10", extra_rows: list[dict] | None = None) -> dict:
    spool = tmp_path / "spool"
    (spool / "meta").mkdir(parents=True)
    lines = ["not json", json.dumps(_row(archive_date))]
    for item in extra_rows or []:
        lines.append(json.dumps(item))
    (spool / "meta" / "raw-progress.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = tmp_path / "day-archive.env"
    env.write_text(f'AR_LOCAL_DAY_ARCHIVE_SPOOL={spool}\nAR_LOCAL_DAY_ARCHIVE_REMOTE="r:Root Folder/daily"\n'
                   f"RCLONE_CONFIG={tmp_path / 'rclone.conf'}\n", encoding="utf-8")
    repo, site, data = tmp_path / "repo", tmp_path / "site", tmp_path / "data"
    for path in (repo, site, data / "state"):
        path.mkdir(parents=True)
        (path / "f.txt").write_text(path.name, encoding="utf-8")
    return {"env": env, "spool": spool, "repo": repo, "site": site, "data": data}


def _runner(fail: str | None = None, corrupt_readback: bool = False, tar_exit: int = 0, git_head: str = P):
    calls = []

    def run(argv, timeout):
        calls.append(list(argv))
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 0, git_head + "\n", "")
        if argv[0] == "tar":
            if tar_exit == 0:
                Path(argv[argv.index("-cf") + 1]).write_bytes(b"archive")
            return subprocess.CompletedProcess(argv, tar_exit, "", "" if tar_exit == 0 else "changed")
        verb = next(arg for arg in argv[3:] if arg in ("copy", "check", "cat"))
        if verb == fail:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        out = ""
        if verb == "cat":
            staged = Path(calls[-3][calls[-3].index("copy") + 2]) / "manifest.json"
            out = staged.read_text(encoding="utf-8") + ("x" if corrupt_readback else "")
        return subprocess.CompletedProcess(argv, 0, out, "")

    run.calls = calls
    return run


def _backup(ctx, run=None, now=NOW):
    return gate.create_backup(ctx["repo"], ctx["site"], ctx["data"], P, C, env_path=ctx["env"], run=run or _runner(), now=now)


@pytest.fixture(autouse=True)
def _isolated_hold_and_space(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "MIN_FREE_BYTES", 0)
    monkeypatch.setenv("AR_LOCAL_DRIVE_BACKUP_SPOOL", str(tmp_path / "no-backup-spool"))


def test_backup_then_gate_and_record_pass(tmp_path):
    ctx = _setup(tmp_path)
    run = _runner()
    receipt = _backup(ctx, run)
    assert receipt["ok"] and receipt["remote"].startswith("r:Root Folder/pre-deploy-backups/")
    tar_calls = [call for call in run.calls if call[0] == "tar"]
    assert [(call[-2], call[-1]) for call in tar_calls] == [
        (str(ctx["repo"].parent), ctx["repo"].name),
        (str(ctx["site"].parent), ctx["site"].name),
        (str(ctx["data"]), "state"),
    ]
    assert all("--exclude=.env" in call and "--exclude=.env.*" in call for call in tar_calls)
    assert [call[3] for call in run.calls if call[0] == "rclone"] == ["copy", "check", "cat"]
    assert not any((ctx["spool"] / "pre-deploy" / "staging").iterdir())
    report = gate.gate(P, C, env_path=ctx["env"], now=NOW + timedelta(hours=1))
    assert report["ok"] and report["restore_drill"] == "NOT_TESTED"
    recorded = gate.record("deployment", P, C, ["cmd"], env_path=ctx["env"], now=NOW)
    assert recorded["result"] == "PASS"
    files = list((ctx["spool"] / "pre-deploy" / "deployment-records").glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text(encoding="utf-8")) == recorded


@pytest.mark.parametrize("fail", ["copy", "check", "cat"])
def test_backup_blocks_when_drive_step_fails(tmp_path, fail):
    ctx = _setup(tmp_path)
    with pytest.raises(gate.Blocked):
        _backup(ctx, _runner(fail=fail))
    assert not (ctx["spool"] / "pre-deploy" / "latest.json").exists()


def test_backup_blocks_on_nonzero_tar_or_wrong_head(tmp_path):
    ctx = _setup(tmp_path)
    with pytest.raises(gate.Blocked, match="tar failed"):
        _backup(ctx, _runner(tar_exit=1))
    with pytest.raises(gate.Blocked, match="HEAD"):
        _backup(ctx, _runner(git_head=C))


def test_backup_blocks_on_readback_mismatch(tmp_path):
    ctx = _setup(tmp_path)
    with pytest.raises(gate.Blocked, match="read-back"):
        _backup(ctx, _runner(corrupt_readback=True))


def test_stale_day_archive_and_non_pass_or_partial_rows(tmp_path):
    ctx = _setup(tmp_path, archive_date="2026-11-08")
    with pytest.raises(gate.Blocked, match="2026-11-09"):
        _backup(ctx)
    assert any(item.startswith("day_archive") for item in gate.gate(P, C, env_path=ctx["env"], now=NOW)["findings"])

    # DRY_RUN / FAIL / exports_only / future rows for today must not displace yesterday's valid PASS wire_raw row.
    ctx_mixed = _setup(
        tmp_path / "mixed",
        archive_date="2026-11-09",
        extra_rows=[
            _row("2026-11-10", result="DRY_RUN", remote_name=""),
            _row("2026-11-10", result="FAIL"),
            _row("2026-11-10", coverage="exports_only"),
            _row("2026-11-11", result="PASS"),
        ],
    )
    assert _backup(ctx_mixed)["day_archive"]["date"] == "2026-11-09"


def test_gate_rejects_other_commits_stale_backup_and_missing_receipt(tmp_path):
    ctx = _setup(tmp_path)
    assert "backup_receipt_missing_or_invalid" in gate.gate(P, C, env_path=ctx["env"], now=NOW)["findings"]
    _backup(ctx)
    assert "current_production_sha_not_backed_up" in gate.gate(C, C, env_path=ctx["env"], now=NOW)["findings"]
    assert "backup_bound_to_other_candidate" in gate.gate(P, P, env_path=ctx["env"], now=NOW)["findings"]
    assert "backup_stale_or_future" in gate.gate(P, C, env_path=ctx["env"], now=NOW + timedelta(hours=7))["findings"]
    with pytest.raises(gate.Blocked):
        gate.record("deployment", C, P, [], env_path=ctx["env"])
    with pytest.raises(gate.Blocked, match="active checkout HEAD"):
        gate.record("deployment", P, C, [], env_path=ctx["env"], now=NOW, repo=ctx["repo"], run=_runner(git_head=P))


def test_tampered_latest_receipt_is_rejected(tmp_path):
    ctx = _setup(tmp_path)
    _backup(ctx)
    latest = ctx["spool"] / "pre-deploy" / "latest.json"
    value = json.loads(latest.read_text(encoding="utf-8"))
    value["protected_code_sha"] = C
    latest.write_text(json.dumps(value), encoding="utf-8")
    assert "backup_receipt_mismatch" in gate.gate(C, C, env_path=ctx["env"], now=NOW)["findings"]


def test_hold_marker_and_bad_remote_and_sha_block(tmp_path):
    ctx = _setup(tmp_path)
    (ctx["spool"] / "write-hold.json").write_text("{}", encoding="utf-8")
    with pytest.raises(gate.Blocked, match="held"):
        _backup(ctx)
    assert any(item.startswith("drive_write_hold:") for item in gate.gate(P, C, env_path=ctx["env"], now=NOW)["findings"])
    (ctx["spool"] / "write-hold.json").unlink()

    with pytest.raises(gate.Blocked):
        gate.gate("abc", C, env_path=ctx["env"])
    ctx["env"].write_text(ctx["env"].read_text(encoding="utf-8").replace("r:Root Folder/daily", "r:daily"), encoding="utf-8")
    with pytest.raises(gate.Blocked, match="dedicated Drive root"):
        gate.gate(P, C, env_path=ctx["env"])
    ctx["env"].write_text(ctx["env"].read_text(encoding="utf-8").replace("r:daily", "r:Root/../other/daily"), encoding="utf-8")
    with pytest.raises(gate.Blocked, match="dedicated Drive root"):
        gate.gate(P, C, env_path=ctx["env"])


def test_root_folder_id_pin_is_forwarded_to_rclone(tmp_path):
    ctx = _setup(tmp_path)
    ctx["env"].write_text(
        ctx["env"].read_text(encoding="utf-8") + "AR_LOCAL_DRIVE_ROOT_FOLDER_ID=1AbCdEfGhIjKlMnOp\n",
        encoding="utf-8",
    )
    run = _runner()
    _backup(ctx, run)
    rclone_calls = [call for call in run.calls if call[0] == "rclone"]
    assert all("--drive-root-folder-id" in call and "1AbCdEfGhIjKlMnOp" in call for call in rclone_calls)


def test_hold_installed_mid_capture_blocks_before_rclone(tmp_path):
    ctx = _setup(tmp_path)
    base_run = _runner()

    def run_with_mid_hold(argv, timeout):
        res = base_run(argv, timeout)
        if argv[0] == "tar":
            (ctx["spool"] / "write-hold.json").write_text("{}", encoding="utf-8")
        return res

    with pytest.raises(gate.Blocked, match="held"):
        _backup(ctx, run_with_mid_hold)
    assert not any(call[0] == "rclone" for call in base_run.calls)
