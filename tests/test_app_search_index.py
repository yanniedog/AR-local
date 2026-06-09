from __future__ import annotations
import gzip, json, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app_payload, app_payload_mobile
SAMPLE = ROOT / "runs" / "2026-05-19" / "_exports"
HAS = (SAMPLE / "dashboard-cache" / "latest.json").exists()
KEY = "Westpac|HLSustainableUpgradesInvestment|RESIDENTIAL_MORTGAGES|Sustainable Upgrades Investment Loan"

def test_energy_in_index():
    idx = app_payload_mobile.build_search_index(
        [{"provider": "Westpac", "product_key": KEY, "product_name": "Sustainable Upgrades Investment Loan"}],
        {KEY: {"description": "fund energy efficiency upgrades"}}, run_date="2026-05-19")
    assert "energy" in idx["products"][KEY]

@pytest.mark.skipif(not HAS, reason="no sample export")
def test_manifest_assets(tmp_path):
    m = app_payload.build_payload(SAMPLE, tmp_path)
    assert "search_index" in m["files"] and "history_banks" in m["files"]
