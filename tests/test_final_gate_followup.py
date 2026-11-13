"""Exercise delayed admission, CLI pin propagation and hosted midnight dates."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import pi_cdr_quality_activate as activate
import pi_cdr_quality_window as window
import pi_deploy_verify as deploy
import pi_live_financial_capture as live
from tests.test_cdr_quality_canary_unit import canary_args
from tests.test_pi_deploy_verify import _verified_sync_snapshot

TZ = ZoneInfo("Australia/Hobart")


@pytest.mark.parametrize("hour,minute", [(0,30), (1,0), (3,29)])
def test_deadline_never_renews_inside_quiet_window(hour, minute):
    with pytest.raises(ValueError, match="quiet window"):
        window.deadline(datetime(2026,11,14,hour,minute,tzinfo=TZ), None)


@pytest.mark.parametrize("hour,minute,day", [(0,29,14), (3,30,15), (23,59,15)])
def test_valid_maintenance_deadline_keeps_immediate_cutoff(hour, minute, day):
    assert window.deadline(datetime(2026,11,14,hour,minute,tzinfo=TZ), None) == datetime(2026,11,day,0,30,tzinfo=TZ)


@pytest.mark.parametrize("later", [(0,30), (3,30)])
def test_canary_preparation_cannot_roll_admission_into_next_window(canary_args, monkeypatch, later):
    # Even preparation spanning the whole quiet interval retains the original cutoff.
    values = iter([datetime(2026,11,14,0,29,tzinfo=TZ),
                   datetime(2026,11,14,*later,tzinfo=TZ)])
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return next(values)
    monkeypatch.setattr(activate, "datetime", Clock)
    monkeypatch.setattr(activate, "operation_guard", lambda *a: None)
    monkeypatch.setattr(activate, "run", lambda *a, **k: pytest.fail("late canary must not launch"))
    with pytest.raises(ValueError, match="quiet window|insufficient time"):
        activate.canary(canary_args)
    assert not canary_args.operation.exists()


def test_verify_cli_mismatched_pin_refuses_before_pi_contact(monkeypatch):
    monkeypatch.setattr(deploy, "origin_main_sha_local", lambda: "b" * 40)
    monkeypatch.setattr(deploy, "pi_remote_snapshot", lambda **kw: pytest.fail("pin mismatch contacted Pi"))
    args = deploy.build_parser().parse_args(["--verify", "--expected-commit", "a" * 40, "--dry-run"])
    assert deploy.cmd_verify(args) == deploy.EXIT_CONFIG


@pytest.mark.parametrize("extra", [[], ["--expected-commit", ""], ["--expected-commit", "a" * 40]])
def test_verify_cli_optional_or_matching_pin_reaches_verification(monkeypatch, extra):
    monkeypatch.setattr(deploy, "origin_main_sha_local", lambda: "a" * 40)
    calls = []
    def snapshot(**kwargs):
        calls.append(kwargs)
        return _verified_sync_snapshot("a" * 40)
    monkeypatch.setattr(deploy, "pi_remote_snapshot", snapshot)
    args = deploy.build_parser().parse_args(["--verify", "--dry-run", *extra])
    assert deploy.cmd_verify(args) == deploy.EXIT_OK
    assert calls == [{"dry_run": True, "fetch": False}]


def test_live_capture_and_failed_stage_copy_keep_original_cutoff(tmp_path, monkeypatch):
    cutoff = datetime(2026, 11, 14, 0, 30, tzinfo=TZ)
    args = SimpleNamespace(admission_cutoff=cutoff, expected_commit="a" * 40, operation=tmp_path)
    later = datetime(2026, 11, 14, 3, 30, tzinfo=TZ)
    closing = live.admitted_deadline(args, later)
    assert closing == cutoff
    with pytest.raises(ValueError, match="insufficient time"):
        live.remaining_budget(5400, closing, later)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return later
    monkeypatch.setattr(live, "datetime", Clock)
    source = tmp_path / "stage"
    source.mkdir()
    (source / "evidence").write_bytes(b"original retained bytes")
    with pytest.raises(TimeoutError, match="cutoff"):
        live.preserve_failed_stage(source, tmp_path / "failed", closing)
    assert (source / "evidence").read_bytes() == b"original retained bytes"
    assert (tmp_path / "failed/evidence").read_bytes() == b""


@pytest.mark.parametrize("name", ["pi_deploy_checkout.py", "pi_deploy_documentation.py"])
def test_imported_observer_helpers_require_deployment(name):
    assert deploy.paths_touch_pi_deploy([name])


@pytest.mark.skipif(os.name == "nt", reason="hosted canary uses Linux shell/date")
@pytest.mark.parametrize("clock,completed,code", [("0015","2026-11-13",0), ("0015","2026-11-14",1),
    ("0330","2026-11-14",0), ("2200","2026-11-14",0), ("2359","2026-11-13",1)])
def test_hosted_canary_compares_latest_due_date(clock, completed, code):
    source = (Path(__file__).parents[1] / ".github/workflows/pi-quality-canary.yml").read_text()
    start = source.index('          D_NOW=')
    end = source.index('          # Parents must', start)
    snippet = source[start:end]
    fake_date = ('date() { if [ "$*" = "+%F %H%M" ]; then printf "2026-11-14 ' + clock
                 + '\\n"; else command date "$@"; fi; }\n')
    # Earlier admission can predate midnight; the due-date check samples afresh.
    result = subprocess.run(["bash", "-c", fake_date + f"NOW_HM=2359; D_DAY={completed}; D_EXIT=fixture\n" + snippet],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == code, result.stderr
