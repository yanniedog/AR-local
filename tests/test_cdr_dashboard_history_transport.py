"""Transport controls only; synthetic markers are not financial acceptance data."""
import copy
import json
import subprocess
import shutil
from pathlib import Path

import pytest

import cdr_dashboard_history_transport as transport
import cdr_dashboard_server as server
from tests.test_cdr_dashboard_history_coverage import files, handler


def payload():
    first = {"run_date": "2001-01-01", "provider": "Protocol €", "product_key": "fixture",
             "rate": "0.0100", "unknown": None, "empty": "", "zero": 0, "flag": False}
    return {"run_dates": ["2001-01-01", "2001-01-02"], "section": "Savings",
            "rates": [first, {**first, "run_date": "2001-01-02", "carry_forward": "1"},
                      {"run_date": "2001-01-02", "provider": "Protocol €", "rate": "0.0200"}],
            "carry_forward_count": 1, "history_coverage": {"historical_completeness": "not_established"}}


def test_actual_js_decoder_preserves_every_value_absence_order_and_metadata(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("Node is required for the actual dashboard decoder contract")
    original = payload()
    body = transport.encode(original)
    value = json.loads(body)
    transport.validate(value, "Savings", "2001-01-02")
    assert len(value["templates"]) == 2
    script = "const fs=require('fs'),d=require('./dashboard/history-transport.js');process.stdout.write(JSON.stringify(d.decode(JSON.parse(fs.readFileSync(process.argv[1],'utf8')))))"
    path = tmp_path / "transport.json"
    path.write_bytes(body)
    result = subprocess.run(["node", "-e", script, str(path)], capture_output=True, check=True, timeout=30,
                            cwd=Path(__file__).resolve().parents[1])
    assert json.loads(result.stdout) == original


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(format="unknown"), lambda p: p.update(row_count=True),
    lambda p: p.update(row_count=0), lambda p: p["observations"][0].__setitem__(0, -1),
    lambda p: p["templates"][0].__setitem__(0, 999999),
    lambda p: p["columns"].append("run_date"), lambda p: p.update(carry_forward_count=0),
    lambda p: p.update(run_dates=["2001-01-01"]), lambda p: p["values"].append({}),
])
def test_bad_reference_count_or_provenance_refuses(mutation):
    value = json.loads(transport.encode(payload()))
    mutation(value)
    with pytest.raises(ValueError):
        transport.validate(value, "Savings", "2001-01-02")


@pytest.mark.parametrize("limit", ["MAX_ROWS", "MAX_COLUMNS", "MAX_VALUES", "MAX_TEMPLATES", "MAX_BYTES"])
def test_resource_limits_refuse_without_partial_transport(monkeypatch, limit):
    monkeypatch.setattr(transport, limit, 0)
    with pytest.raises(ValueError):
        transport.encode(payload())


def test_actual_legacy_and_series_routes_have_independent_cache_and_equal_rows(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    paths = files(root, 2)
    rows = payload()["rates"]
    monkeypatch.setattr(server, "read_bank_history_db", lambda path, *_: copy.deepcopy(
        [row for row in rows if row["run_date"] == path.parent.parent.name and "carry_forward" not in row]))
    instance = handler(root, tmp_path)
    query = {"date": ["2001-12-31"], "section": ["Savings"]}
    raw = instance.route("/api/banks/history/section", query)[0]
    encoded = instance.route("/api/banks/history/section/series", query)[0]
    value = json.loads(encoded)
    assert value["format"] == transport.FORMAT
    assert "format" not in json.loads(raw)
    assert instance.route("/api/banks/history/section", query)[0] == raw
    assert instance.route("/api/banks/history/section/series", query)[0] == encoded
    transport.validate(value, "Savings", "2001-12-31")
    assert value["row_count"] == len(json.loads(raw)["rates"])
    paths[0].write_bytes(b"changed inventory marker")
    assert instance.route("/api/banks/history/section/series", query)[0] == encoded


def test_encoder_rejects_non_json_values():
    for value in (float("nan"), float("inf"), {}, []):
        source = payload()
        source["rates"][0]["bad"] = value
        with pytest.raises(ValueError):
            transport.encode(source)


def test_dashboard_decoder_failure_and_prototype_controls():
    if shutil.which("node") is None:
        pytest.skip("Node is required for the dashboard decoder controls")
    result = subprocess.run(["node", "--test", "--test-reporter=tap", "tests/js/dashboard_history_transport.test.cjs"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# pass 4" in result.stdout and "# fail 0" in result.stdout
