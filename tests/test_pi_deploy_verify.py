"""Regression tests for Pi deploy path classification."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pi_deploy_verify  # noqa: E402


def test_app_payload_changes_require_pi_deploy():
    assert pi_deploy_verify.paths_touch_pi_deploy(["app_payload.py"])


def test_non_pi_mobile_and_docs_changes_do_not_require_pi_deploy():
    assert not pi_deploy_verify.paths_touch_pi_deploy(
        ["docs/HANDOFF.md", "mobile/src/components/BankAvatar.tsx"]
    )


def test_empty_change_list_does_not_require_pi_deploy():
    assert not pi_deploy_verify.paths_touch_pi_deploy([])


def test_pi_runtime_health_changes_require_pi_deploy():
    assert pi_deploy_verify.paths_touch_pi_deploy(["pi_runtime_health.py"])
