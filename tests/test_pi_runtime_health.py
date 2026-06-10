"""Unit tests for pi_runtime_health.py (mocked probes, no live HTTP)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_runtime_health  # noqa: E402


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(pi_runtime_health, "data_state_root", lambda _repo: state_dir)
    monkeypatch.setattr(pi_runtime_health, "ensure_runtime_data_writable", lambda _repo: None)
    return state_dir


def _ns(**kwargs):
    class NS:
        pass

    ns = NS()
    for key, val in kwargs.items():
        setattr(ns, key, val)
    return ns


def test_check_ok_resets_fail_streak(isolated_state):
    with mock.patch.object(pi_runtime_health, "run_http_probes", return_value=(True, ["ok"])):
        rc = pi_runtime_health.cmd_check(_ns(check=True, check_tailscale=False, timeout=5.0, retries=0))
    assert rc == 0
    state = json.loads((isolated_state / "runtime_health.json").read_text(encoding="utf-8"))
    assert state["http_fail_streak"] == 0


def test_check_fail_increments_streak(isolated_state):
    with mock.patch.object(
        pi_runtime_health,
        "run_http_probes",
        return_value=(False, ["http://127.0.0.1/api/latest: timeout"]),
    ):
        rc = pi_runtime_health.cmd_check(_ns(check=True, check_tailscale=False, timeout=5.0, retries=0))
    assert rc == 1
    state = json.loads((isolated_state / "runtime_health.json").read_text(encoding="utf-8"))
    assert state["http_fail_streak"] == 1


def test_heal_restarts_at_threshold(isolated_state):
    state_path = isolated_state / "runtime_health.json"
    state_path.write_text(json.dumps({"http_fail_streak": 2, "tailscale_fail_streak": 0}) + "\n", encoding="utf-8")
    with mock.patch.object(pi_runtime_health, "run_http_probes", side_effect=[(False, ["fail"]), (True, ["ok"])]):
        with mock.patch.object(pi_runtime_health, "check_tailscale", return_value=(True, ["tailnet ok"])):
            with mock.patch.object(pi_runtime_health, "restart_dashboard_and_nginx", return_value=0) as heal_mock:
                rc = pi_runtime_health.cmd_heal(
                    _ns(
                        dry_run=False,
                        timeout=5.0,
                        retries=0,
                        fail_threshold=3,
                        tailscale_fail_threshold=2,
                        heal_cooldown=300,
                        tailscale_heal_cooldown=600,
                    ),
                )
    assert rc == 0
    heal_mock.assert_called_once()


def test_probe_urls_include_nginx_and_backend():
    urls = pi_runtime_health.probe_urls()
    assert "http://127.0.0.1/api/latest" in urls
    assert "http://127.0.0.1:8808/api/latest" in urls
