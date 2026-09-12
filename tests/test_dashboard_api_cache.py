"""Run the real dashboard fetch-closure regressions in Node without a browser."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_dashboard_mutable_api_cache_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for dashboard JavaScript fetch-policy tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "--test-reporter=tap", "tests/js/dashboard_api_cache.test.cjs"], cwd=root,
        capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# pass 4" in result.stdout and "# fail 0" in result.stdout, result.stdout
