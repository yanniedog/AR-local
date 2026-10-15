"""Exercise real calculator candidate selection in Node, including public CDR rows."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_dashboard_calculator_eligibility_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for dashboard calculator tests")
    result = subprocess.run(
        [node, "--test", "--test-reporter=tap", "scripts/calculator-eligibility.test.mjs"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        timeout=30, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# pass 4" in result.stdout and "# fail 0" in result.stdout, result.stdout
