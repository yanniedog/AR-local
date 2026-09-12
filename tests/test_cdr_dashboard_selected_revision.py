"""Dashboard selection over finalized exports of retained, real CDR rows."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import cdr_dashboard_server as server
from ar_local_pi_runtime import latest_exports_root, selected_exports_root
from cdr_finalization import finalize_observation


@pytest.fixture(scope="module")
def captured():
    evidence = Path(__file__).parents[1] / "docs/evidence/backup-observation-20260911/publication/v1-core.json.gz"
    core = json.loads(gzip.decompress(evidence.read_bytes()))
    rows = {}
    for row in core["sections"]["Savings"]["rates"]:
        if row.get("category") == "TRANS_AND_SAVINGS_ACCOUNTS":
            rows.setdefault(row["product_key"], row)
        if len(rows) == 2:
            break
    assert len(rows) == 2
    return core["run_date"], list(rows.values())


def export(root, day, rows):
    cache = root / "dashboard-cache"
    (cache / day).mkdir(parents=True)
    counts = {"products": len(rows), "rates": len(rows)}
    (cache / "latest.json").write_text(json.dumps({"run_date": day, "banks_counts": counts}))
    (cache / day / "banks.json").write_text(json.dumps({"run_date": day, "rates": rows}))
    # Fixture finalization is explicitly partial: it does not claim ingest proof.
    (root / "ingest-status.json").write_text(json.dumps({
        "total": 0, "incomplete": True, "failure_provenance_complete": False,
    }))
    with sqlite3.connect(root / "local-cdr.sqlite") as db:
        db.execute("CREATE TABLE bank_products (run_date TEXT, dataset TEXT, product_key TEXT, provider TEXT, product_id TEXT, category TEXT, details_json TEXT DEFAULT '{}')")
        db.execute("CREATE TABLE bank_rates (run_date TEXT, dataset TEXT, product_key TEXT, provider TEXT, product_id TEXT, product_name TEXT, rate TEXT, rate_family TEXT, rate_type TEXT)")
        for row in rows:
            db.execute("INSERT INTO bank_products (run_date,dataset,product_key,provider,product_id,category) VALUES (?,?,?,?,?,?)",
                       (day, "Savings", row["product_key"], row["provider"], row["product_id"], row["category"]))
            db.execute("INSERT INTO bank_rates VALUES (?,?,?,?,?,?,?,?,?)",
                       (day, "Savings", row["product_key"], row["provider"], row["product_id"], row["product_name"],
                        row["rate"], "deposit", row.get("rate_type")))


def finalize(root, state, day, name, parent=None):
    return finalize_observation(root, state, state / f"{day}.{name}.json", observation_date=day,
                                result={"run_date": day}, parent_generation_id=parent)


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_current_routes_switch_to_selected_revision_and_preserve_primary(tmp_path, captured):
    day, rows = captured
    runs, state = tmp_path / "runs", tmp_path / "state"
    primary = runs / day / "_exports"
    export(primary, day, rows[:1])
    first = finalize(primary, state, day, "done")
    original = snapshot(primary)
    resolver = server.ExportResolver("latest", runs)
    assert resolver.root() == primary
    revision = runs / day / "_revisions" / "r1" / "_exports"
    export(revision, day, rows)
    finalize(revision, state, day, "revision.r1", first["generation_id"])
    resolver.cached_until = 0  # Existing five-second discovery cache expires.
    assert resolver.root() == resolver.root_for_date(day) == revision
    handler = object.__new__(server.make_handler(resolver, tmp_path / "site", False))
    latest = json.loads(handler.route("/api/latest", {})[0])
    assert latest["banks_counts"]["rates"] == 2
    expected = {row["product_id"] for row in rows}
    for route in ("/api/banks", "/api/banks/section", "/api/banks/history/section"):
        body = json.loads(handler.route(route, {"date": [day], "section": ["Savings"]})[0])
        assert {row["product_id"] for row in body["rates"]} == expected
    assert snapshot(primary) == original


def test_rejected_revision_does_not_replace_selected_primary(tmp_path, captured):
    day, rows = captured
    runs, state = tmp_path / "runs", tmp_path / "state"
    primary = runs / day / "_exports"
    export(primary, day, rows)
    first = finalize(primary, state, day, "done")
    revision = runs / day / "_revisions" / "r1" / "_exports"
    export(revision, day, rows[:1])
    finalize(revision, state, day, "revision.r1", first["generation_id"])
    assert latest_exports_root(runs) == primary
    assert server.ExportResolver("latest", runs).root_for_date(day) == primary


def test_legacy_and_older_dates_keep_primary_discovery(tmp_path, captured):
    day, rows = captured
    runs, state = tmp_path / "runs", tmp_path / "state"
    primary = runs / day / "_exports"
    export(primary, day, rows)
    unselected = runs / day / "_revisions" / "unfinalized" / "_exports"
    export(unselected, day, rows)
    assert latest_exports_root(runs) == primary
    # Date remapping only exercises the resolver's metadata routing.
    next_day = "2026-09-12"
    current = runs / next_day / "_exports"
    export(current, next_day, rows)
    finalize(current, state, next_day, "done")
    assert latest_exports_root(runs) == current
    assert selected_exports_root(runs, day) is None
    assert server.ExportResolver("latest", runs).root_for_date(day) == primary
    assert server.ExportResolver(str(primary), runs).root() == primary


@pytest.mark.parametrize("fault", ["not_object", "wrong_schema", "traversal", "wrong_generation", "manifest", "marker", "oversized"])
def test_invalid_selection_never_falls_back_to_primary(tmp_path, captured, fault):
    day, rows = captured
    runs, state = tmp_path / "runs", tmp_path / "state"
    primary = runs / day / "_exports"
    export(primary, day, rows)
    marker = finalize(primary, state, day, "done")
    pointer_path = state / "observation-pointers-v2" / "latest-observation.json"
    pointer = json.loads(pointer_path.read_bytes())
    if fault == "manifest":
        (primary / "dashboard-cache" / "latest.json").write_text("{}")
    elif fault == "marker":
        (state / pointer["marker_path"]).write_text(json.dumps(dict(marker, ledger_event_digest="0" * 64)))
    elif fault == "oversized":
        pointer_path.write_text(" " * (64 * 1024 + 1))
    else:
        if fault == "wrong_schema":
            pointer["schema_version"] = 1
        elif fault == "traversal":
            pointer["marker_path"] = "../outside.json"
        elif fault == "wrong_generation":
            pointer["generation_id"] = "unverified"
        pointer_path.write_text(json.dumps([] if fault == "not_object" else pointer))
    with pytest.raises(ValueError):
        latest_exports_root(runs)
    with pytest.raises(ValueError):
        server.ExportResolver("latest", runs).root_for_date(day)
    assert server.ExportResolver(str(primary), runs).root_for_date(day) == primary


@pytest.mark.parametrize("location", ["other-runs/2026-09-11/_exports", "runs/arbitrary/_exports"])
def test_verified_pointer_cannot_select_outside_configured_dated_runs(tmp_path, captured, location):
    day, rows = captured
    outside = tmp_path / location
    export(outside, day, rows)
    finalize(outside, tmp_path / "state", day, "done")
    with pytest.raises(ValueError):
        latest_exports_root(tmp_path / "runs")
