"""Disposable inventory/cohort mechanisms, not financial acceptance fixtures."""
from datetime import date, timedelta
import copy
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

import cdr_dashboard_server as server
from cdr_dashboard_history_coverage import history_inventory, read_selected_history
from cdr_ribbon_normalize import aggregate_ribbon, compact_history


def files(root, count):
    result = []
    for offset in range(count):
        day = (date(2001, 1, 1) + timedelta(days=offset)).isoformat()
        path = root / day / "_exports" / "local-cdr.sqlite"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"inventory marker, deliberately not a database")
        result.append(path)
    return result


def handler(root, tmp_path, fixed=None):
    resolver = server.ExportResolver(str(fixed) if fixed else "latest", root)
    return object.__new__(server.make_handler(resolver, tmp_path / "site", False))


def payload(instance, compact=False, nonstandard=False):
    query = {"date": ["2001-12-31"], "section": ["Savings"]}
    if nonstandard:
        query["include_non_standard"] = ["1"]
    suffix = "/compact" if compact else ""
    return json.loads(instance.route("/api/banks/history/section" + suffix, query)[0])


def test_inventory_caps_reads_without_opening_omitted_files(tmp_path, monkeypatch):
    paths = files(tmp_path, 91)
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("inventory opened file bytes"))
    inventory = history_inventory(tmp_path, None, "2001-12-31", 90)
    assert [path for path, _ in inventory.selected] == paths[1:]
    assert inventory.metadata["available_run_file_count"] == 91
    assert inventory.metadata["selected_run_file_count"] == 90
    assert inventory.metadata["omitted_run_file_count"] == 1
    assert inventory.metadata["truncated"] is True
    reads = []

    def read(path, maximum, section):
        reads.append(path)
        return []

    rows, dates, coverage = read_selected_history(inventory, read, "2001-12-31", "Savings")
    assert reads == paths[1:]
    assert rows == dates == []
    assert coverage["empty_selected_run_file_count"] == 90
    assert coverage["observed_date_count"] == 0
    assert coverage["historical_completeness"] == "not_established"


@pytest.mark.parametrize("compact", [False, True])
def test_actual_route_cache_tracks_older_omitted_files(tmp_path, monkeypatch, compact):
    root = tmp_path / "runs"
    paths = files(root, 91)
    reads = []
    monkeypatch.setattr(server, "read_bank_history_db", lambda path, *a: reads.append(path) or [])
    instance = handler(root, tmp_path)
    first = payload(instance, compact)
    assert len(reads) == 90
    assert payload(instance, compact) == first
    assert len(reads) == 90
    paths[0].write_bytes(b"older omitted file changed")
    assert payload(instance, compact) == first
    assert len(reads) == 180  # Same selected 90; complete inventory invalidated cache.
    assert paths[0] not in reads
    older = root / "2000-12-31" / "_exports" / "local-cdr.sqlite"
    older.parent.mkdir(parents=True)
    older.write_bytes(b"new older inventory marker")
    updated = payload(instance, compact)["history_coverage"]
    assert (updated["available_run_file_count"], updated["omitted_run_file_count"]) == (92, 2)
    assert len(reads) == 270 and older not in reads


def test_inventory_sidecars_missing_maximum_and_selected_revision(tmp_path):
    paths = files(tmp_path, 3)
    paths[0].unlink()
    (tmp_path / "not-a-day").mkdir()
    revision = tmp_path / "2001-01-02" / "_revisions" / "r1" / "_exports"
    revision.mkdir(parents=True)
    (revision / "local-cdr.sqlite").write_bytes(b"revision marker")
    first = history_inventory(tmp_path, None, "2001-01-02", 90, revision)
    assert first.selected == [((revision / "local-cdr.sqlite").resolve(), "2001-01-02")]
    assert first.metadata["candidate_run_file_count"] == 2
    assert first.metadata["missing_run_file_dates"] == ["2001-01-01"]
    Path(str(revision / "local-cdr.sqlite") + "-wal").write_bytes(b"sidecar marker")
    assert history_inventory(tmp_path, None, "2001-01-02", 90, revision).signature != first.signature


def test_read_errors_empty_files_and_row_dates_are_distinct(tmp_path):
    paths = files(tmp_path, 3)
    inventory = history_inventory(tmp_path, None, "2001-12-31", 90)

    def read(path, *args):
        if path == paths[0]:
            raise sqlite3.DatabaseError("private path must not be exposed")
        if path == paths[1]:
            return []
        return [{"run_date": "2000-12-20"}, {"run_date": "2000-12-21"}]

    _, dates, coverage = read_selected_history(inventory, read, "2001-12-31", "Savings")
    assert dates == ["2000-12-20", "2000-12-21"]  # Never inferred from filenames.
    assert coverage["observed_date_count"] == 2
    assert coverage["successful_selected_run_file_count"] == 2
    assert coverage["empty_selected_run_file_dates"] == ["2001-01-02"]
    assert coverage["unreadable_selected_run_files"] == [
        {"run_file_date": "2001-01-01", "reason": "DatabaseError"}]
    assert coverage["partial"] is True


def test_actual_unreadable_sqlite_is_reported_without_modification(tmp_path):
    path = files(tmp_path / "runs", 1)[0]
    before = path.read_bytes()
    result = payload(handler(tmp_path / "runs", tmp_path), compact=True)
    assert result["run_dates"] == []
    assert result["history_coverage"]["unreadable_selected_run_file_count"] == 1
    assert result["history_coverage"]["observed_date_count"] == 0
    assert path.read_bytes() == before


def test_fixed_root_can_return_multiple_dates_and_missing_root_is_empty(tmp_path, monkeypatch):
    root = tmp_path / "fixed"
    root.mkdir()
    (root / "local-cdr.sqlite").write_bytes(b"fixed inventory marker")
    monkeypatch.setattr(server, "read_bank_history_db", lambda *a: [
        {"run_date": "2001-01-01"}, {"run_date": "2001-01-02"}])
    result = payload(handler(tmp_path / "absent", tmp_path, fixed=root))
    coverage = result["history_coverage"]
    assert coverage["scope"] == "fixed_root"
    assert coverage["selected_run_file_dates"] == [None]
    assert coverage["selected_run_file_count"] == 1
    assert coverage["observed_date_count"] == 2
    empty = payload(handler(tmp_path / "absent", tmp_path))
    assert empty["run_dates"] == []
    assert empty["history_coverage"]["available_run_file_count"] == 0
    assert empty["history_coverage"]["historical_completeness"] == "not_established"


def row(day, identity, **extra):
    # Numbers exercise the existing acceptance/count kernel, not bank rates.
    return {"run_date": day, "product_key": identity, "provider": "protocol-only",
            "dataset": "Savings", "rate": "0.01", **extra}


def test_opt_in_provenance_preserves_default_shape_and_numeric_results():
    rows = [row("2001-01-01", "a", carry_forward=flag) for flag in ("1", "0", 1, 0, True, None)]
    rows += [row("2001-01-01", "invalid", rate="unreadable", carry_forward="1")]
    before = copy.deepcopy(rows)
    default = aggregate_ribbon(rows, "Savings")
    enhanced = aggregate_ribbon(rows, "Savings", include_provenance=True)
    assert enhanced["counts"]["carry_forward_rates"] == 1
    assert enhanced["counts"]["observed_rates"] == 5
    assert enhanced["range"] == default["range"]
    assert rows == before
    stripped = copy.deepcopy(enhanced)
    for part in [stripped["counts"], *stripped["providers"]]:
        del part["observed_rates"], part["carry_forward_rates"]
    assert stripped == default
    baseline = compact_history(["2001-01-01", "2001-01-02"], {"2001-01-01": default})
    current = compact_history(["2001-01-01", "2001-01-02"], {"2001-01-01": enhanced}, include_provenance=True)
    for part in current["points"] + list(current["providers"][0]["by_date"].values()):
        del part["observed_count"], part["carry_forward_count"]
    assert current == baseline


def test_actual_compact_route_counts_after_current_cohort_and_standard_filter(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    paths = files(root, 3)
    days = [path.parent.parent.name for path in paths]
    source = {
        days[0]: [row(days[0], "current"), row(days[0], "discontinued"),
                  row(days[0], "special", account_class="non_standard"), row(days[0], "invalid", rate="bad")],
        days[1]: [row(days[1], "anchor-other"), row(days[1], "discontinued")],
        days[2]: [row(days[2], "current", carry_forward="0"), row(days[2], "anchor-other"),
                  row(days[2], "special", account_class="non_standard"), row(days[2], "invalid", rate="bad")],
    }
    before = copy.deepcopy(source)
    monkeypatch.setattr(server, "read_bank_history_db", lambda path, *a: source[path.parent.parent.name])
    instance = handler(root, tmp_path)
    result = payload(instance, compact=True)
    assert [(point["observed_count"], point["carry_forward_count"]) for point in result["points"]] == [(1, 0), (1, 1), (2, 0)]
    coverage = result["history_coverage"]
    assert coverage["returned_observed_rate_count"] == 4
    assert coverage["returned_carry_forward_rate_count"] == 1
    assert coverage["returned_observed_date_count"] == 3
    assert coverage["returned_carry_forward_date_count"] == 1
    assert coverage["observed_row_count"] == 10  # Pre-filter loaded observations, not returned contributions.
    included = payload(instance, compact=True, nonstandard=True)["history_coverage"]
    assert included["returned_carry_forward_rate_count"] == 2
    assert included["returned_observed_rate_count"] == 6
    assert source == before


def test_dashboard_history_coverage_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for dashboard history disclosure tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, "--test", "--test-reporter=tap", "tests/js/dashboard_history_coverage.test.cjs"],
                            cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# fail 0" in result.stdout and "# pass 8" in result.stdout, result.stdout


def test_page_loads_coverage_asset_before_app_and_route_serves_exact_bytes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    page = (root / "dashboard/index.html").read_text(encoding="utf-8")
    assert page.index('src="/assets/history-coverage.js"') < page.index('src="/assets/app.js"')
    served = handler(tmp_path / "absent", tmp_path).route("/assets/history-coverage.js", {})
    assert served[0] == (root / "dashboard/history-coverage.js").read_bytes()
    assert "javascript" in served[1]
