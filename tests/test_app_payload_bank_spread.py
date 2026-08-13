import json
import gzip
from pathlib import Path

import app_payload_bank_spread as spread
import app_payload_build


FIXTURE = Path(__file__).parent / "fixtures" / "bank_spread_rows_2026-05-19.json"


def test_real_fixture_builds_mean_per_product_then_provider(tmp_path: Path) -> None:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8"))
    day = captured["run_date"]
    banks = tmp_path / "dashboard-cache" / day / "banks.json"
    banks.parent.mkdir(parents=True)
    banks.write_text(json.dumps({"rates": captured["rates"]}), encoding="utf-8")

    payload = spread.build_bank_spread_history(
        tmp_path,
        run_date=day,
        history_dates=lambda *_: [day],
        banks_path=lambda root, date: root / "dashboard-cache" / date / "banks.json",
        load_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
    )

    bank = payload["banks"]["Macquarie Bank Limited"]
    assert bank["mortgage_count"] == [2]
    assert bank["savings_count"] == [2]
    assert bank["mortgage_mean"] == [0.061775]
    assert bank["savings_mean"] == [0.030625]
    assert bank["gap"] == [0.03115]
    assert bank["quality"] == ["complete"]
    assert len(bank["mortgage_hash"][0]) == 16


def test_real_fixture_excludes_fixed_conditional_and_term_deposit_rows() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rates"]
    mortgage = spread._provider_cohort(rows, spread._mortgage_member)["Macquarie Bank Limited"]
    savings = spread._provider_cohort(rows, spread._savings_member)["Macquarie Bank Limited"]
    assert mortgage["count"] == 2
    assert savings["count"] == 2


def test_exact_one_percent_is_normalized_as_a_percentage() -> None:
    assert spread._rate({"rate": 1}) == 0.01
    assert spread._rate({"rate": 0.85}) is None


def test_missing_side_is_explicit_and_never_manufactures_a_gap(tmp_path: Path) -> None:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8"))
    day = captured["run_date"]
    mortgage_only = [row for row in captured["rates"] if row["dataset"] == "Mortgage"]
    banks = tmp_path / "dashboard-cache" / day / "banks.json"
    banks.parent.mkdir(parents=True)
    banks.write_text(json.dumps({"rates": mortgage_only}), encoding="utf-8")
    payload = spread.build_bank_spread_history(
        tmp_path, run_date=day, history_dates=lambda *_: [day],
        banks_path=lambda root, date: root / "dashboard-cache" / date / "banks.json",
        load_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
    )
    bank = payload["banks"]["Macquarie Bank Limited"]
    assert bank["gap"] == [None]
    assert bank["quality"] == ["missing_savings"]


def test_spread_asset_is_manifested_only_on_rolling_release(tmp_path: Path) -> None:
    asset = {
        "schema_version": 1,
        "run_date": "2026-05-19",
        "run_dates": ["2026-05-19"],
        "method": "mean_rate_rows_per_product_then_mean_products_per_provider",
        "cohorts": {"mortgage": "mortgage", "savings": "savings"},
        "banks": {"Macquarie Bank Limited": {"gap": [0.03]}},
    }
    common = dict(
        core={"run_date": "2026-05-19"}, details={"products": []},
        run_date="2026-05-19", repo="example/repo", counts={},
        bank_spread_history=asset,
    )
    rolling = app_payload_build._package(
        out_dir=tmp_path / "rolling", tag=app_payload_build.DEFAULT_TAG, **common,
    )
    dated = app_payload_build._package(
        out_dir=tmp_path / "dated", tag="app-payload-2026-05-19", **common,
    )
    entry = rolling["files"]["bank_spread_history"]
    decoded = json.loads(gzip.decompress((tmp_path / "rolling" / entry["name"]).read_bytes()))
    assert decoded == asset
    assert "bank_spread_history" not in dated["files"]
