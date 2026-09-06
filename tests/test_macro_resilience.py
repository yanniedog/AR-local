"""Transport/schema faults around captured official observations."""
import json
import sqlite3
import subprocess
import urllib.error
import csv
import io
import hashlib
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import app_payload_v2
import cdr_economic_local as local
import cdr_macro_freshness as freshness
import cdr_macro_http as http
import cdr_macro_ingest as ingest
import cdr_macro_refresh as refresh
import pi_daily_sync
from cdr_macro_sources import ABS_CPI_M_SERIES, ABS_LF_HOURS_SERIES, RBA_H5_COLUMNS
from cdr_macro_store import read_store

FIXTURES = Path(__file__).parent / "fixtures" / "macro_official_20260907"
NOW = "2026-09-07T00:00:00Z"


def captured(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def retired_cpi_store(path, monkeypatch):
    con = ingest.open_store(path)
    old_url = "https://data.api.abs.gov.au/rest/data/CPI_M/all?format=csv"
    old_filters = {sid: dict(filt) for sid, filt in ABS_CPI_M_SERIES.items()}
    old_filters["monthly_trimmed_mean_cpi"].update(INDEX="999905", TSEST="10")
    monkeypatch.setattr(ingest, "_now_iso", lambda: NOW)
    monkeypatch.setattr(ingest, "_fetch_url", lambda *a, **k: captured("abs_cpi_retired.csv"))
    ingest._ingest_abs_sdmx_csv(con, old_url, old_filters)
    return con, old_url


def seed_store(path, monkeypatch):
    monkeypatch.setattr(ingest, "_now_iso", lambda: NOW)
    monkeypatch.setattr(ingest, "_fetch_url", lambda *a, **k: captured("rba_h5.csv"))
    con = ingest.open_store(path)
    ingest.ingest_rba_h5(con)
    con.close()


def test_rba_identifies_series_after_title_change():
    text = captured("rba_h5.csv")
    expected = ingest.parse_rba_csv(text, RBA_H5_COLUMNS)
    assert expected["unemployment_rate"][-1][:2] == ("2026-07-31", 4.5)
    changed = text.replace("Unemployment rate", "Edited title")
    assert ingest.parse_rba_csv(changed, RBA_H5_COLUMNS) == expected


def test_rba_does_not_guess_when_stable_identity_or_units_change():
    text = captured("rba_h5.csv")
    assert "unemployment_rate" not in ingest.parse_rba_csv(text.replace("GLFSURSA", "REMOVED"), RBA_H5_COLUMNS)
    assert not ingest.parse_rba_csv(text.replace("Per cent", "Basis points"), RBA_H5_COLUMNS)


def test_current_cpi_codes_are_not_the_retired_indicator():
    parsed = ingest.parse_abs_sdmx_csv(captured("abs_cpi_current.csv"), ABS_CPI_M_SERIES)
    assert parsed["monthly_cpi_indicator"][-1][:2] == ("2026-07-31", 3.5)
    assert parsed["monthly_trimmed_mean_cpi"][-1][:2] == ("2026-07-31", 3.6)


def test_failed_cpi_transition_never_relabels_retired_observations(tmp_path, monkeypatch):
    store = tmp_path / "macro.sqlite"
    con, old_url = retired_cpi_store(store, monkeypatch)
    original = con.execute("SELECT * FROM series_observations").fetchall()
    monkeypatch.setattr(ingest, "_fetch_url", lambda *a, **k: "Unavailable")
    ingest.ingest_abs_cpi_m(con)
    assert con.execute("SELECT source_url FROM ingest_runs LIMIT 1").fetchone()[0] == old_url
    assert con.execute("SELECT * FROM series_observations").fetchall() == original
    con.close()
    rows = {row["id"]: row for row in app_payload_v2.build_economic_outlook(store, generated_at=NOW)["series"]}
    assert rows["monthly_cpi_indicator"]["freshness"]["status"] == "error"
    assert rows["monthly_cpi_indicator"]["observations"] == []


def test_successful_cpi_transition_archives_exact_predecessor_and_replaces_membership(tmp_path, monkeypatch):
    store = tmp_path / "macro.sqlite"
    con, _ = retired_cpi_store(store, monkeypatch)
    before = con.execute("SELECT * FROM series_observations ORDER BY series_id, observation_date").fetchall()
    metadata = con.execute("SELECT * FROM ingest_runs ORDER BY series_id").fetchall()
    monkeypatch.setattr(ingest, "_fetch_url", lambda *a, **k: captured("abs_cpi_current.csv"))
    assert all(row["status"] == "ok" for row in ingest.ingest_abs_cpi_m(con).values())
    preserved, preserved_metadata = [], []
    for count, snapshot, digest in con.execute("SELECT observation_count,snapshot_json,snapshot_sha256 FROM series_definition_archive ORDER BY series_id"):
        assert hashlib.sha256(snapshot.encode()).hexdigest() == digest
        value = json.loads(snapshot)
        assert count == len(value["observations"])
        preserved.extend(tuple(row[column] for column in ["series_id", "observation_date", "raw_value", "release_date"]) for row in value["observations"])
        preserved_metadata.extend(tuple(row[column] for column in ["series_id", "last_checked_at", "last_success_at", "last_observation_date", "last_value", "status", "message", "source_url"]) for row in value["ingest_runs"])
    assert preserved == before
    assert preserved_metadata == metadata
    expected = ingest.parse_abs_sdmx_csv(captured("abs_cpi_current.csv"), ABS_CPI_M_SERIES)
    for sid, rows in expected.items():
        assert con.execute("SELECT observation_date,raw_value,release_date FROM series_observations WHERE series_id=? ORDER BY observation_date", (sid,)).fetchall() == rows
    ingest.ingest_abs_cpi_m(con)
    assert con.execute("SELECT count(*) FROM series_definition_archive").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        con.execute("UPDATE series_definition_archive SET snapshot_json='{}'")
    con.close()
    observed = local._read_observations(store, "monthly_trimmed_mean_cpi", freshness.parse_timestamp(NOW).date())
    assert [(row[0].isoformat(), row[1]) for row in observed] == [(row[0], row[1]) for row in expected["monthly_trimmed_mean_cpi"]]
    assert len(app_payload_v2.build_economic_outlook(store, generated_at=NOW)["series"]) == 29


def test_cpi_install_failure_rolls_back_archives_and_both_series(tmp_path, monkeypatch):
    con, old_url = retired_cpi_store(tmp_path / "macro.sqlite", monkeypatch)
    before = con.execute("SELECT * FROM series_observations ORDER BY series_id,observation_date").fetchall()
    con.execute("""CREATE TRIGGER reject_current_cpi BEFORE INSERT ON series_observations
        WHEN NEW.series_id = 'monthly_trimmed_mean_cpi' AND NEW.observation_date >= '2026-01-01'
        BEGIN SELECT RAISE(ABORT, 'injected database write failure'); END""")
    con.commit()
    monkeypatch.setattr(ingest, "_fetch_url", lambda *a, **k: captured("abs_cpi_current.csv"))
    result = ingest.ingest_abs_cpi_m(con)
    assert all(row["status"] == "error" for row in result.values())
    assert con.execute("SELECT * FROM series_observations ORDER BY series_id,observation_date").fetchall() == before
    assert con.execute("SELECT count(*) FROM series_definition_archive").fetchone()[0] == 0
    assert con.execute("SELECT DISTINCT last_success_at,source_url FROM ingest_runs").fetchall() == [(NOW, old_url)]
    con.close()


def test_abs_bad_unit_isolates_only_the_affected_series(tmp_path, monkeypatch):
    rows = list(csv.reader(io.StringIO(captured("abs_cpi_current.csv"))))
    for row in rows[1:]:
        if row[2] == "999902":
            row[8] = "HR"
    text = io.StringIO()
    csv.writer(text).writerows(rows)
    monkeypatch.setattr(ingest, "_fetch_url", lambda *a, **k: text.getvalue())
    con = ingest.open_store(tmp_path / "macro.sqlite")
    result = ingest.ingest_abs_cpi_m(con)
    assert result["monthly_cpi_indicator"]["status"] == "ok"
    assert result["monthly_trimmed_mean_cpi"]["status"] == "error"
    assert con.execute("SELECT DISTINCT series_id FROM series_observations").fetchall() == [("monthly_cpi_indicator",)]
    con.close()


def test_rba_bad_numeric_isolates_only_the_affected_series(tmp_path, monkeypatch):
    rows = list(csv.reader(io.StringIO(captured("rba_h5.csv"))))
    column = next(row for row in rows if row and row[0] == "Series ID").index("GLFSPRSA")
    rows[-1][column] = "NaN"
    text = io.StringIO()
    csv.writer(text).writerows(rows)
    monkeypatch.setattr(ingest, "_fetch_url", lambda *a, **k: text.getvalue())
    con = ingest.open_store(tmp_path / "macro.sqlite")
    result = ingest.ingest_rba_h5(con)
    assert result["unemployment_rate"]["status"] == "ok"
    assert result["participation_rate"]["status"] == "error"
    assert con.execute("SELECT DISTINCT series_id FROM series_observations").fetchall() == [("unemployment_rate",)]
    con.close()


def test_hours_scale_is_validated_and_converted_consistently():
    text = captured("abs_lf_hours.csv")
    parsed = ingest.parse_abs_sdmx_csv(text, ABS_LF_HOURS_SERIES)
    raw = parsed["hours_worked"][-1][1]
    assert freshness.observation_value("hours_worked", raw) == pytest.approx(1997.86882584)
    with pytest.raises(ValueError, match="source unit changed"):
        ingest.parse_abs_sdmx_csv(text.replace(",HR,3,", ",HR,6,"), ABS_LF_HOURS_SERIES)


def test_parse_failure_does_not_advance_success_or_erase_observations(tmp_path, monkeypatch):
    store = tmp_path / "macro.sqlite"
    seed_store(store, monkeypatch)
    con = ingest.open_store(store)
    before = con.execute("SELECT * FROM series_observations").fetchall()
    monkeypatch.setattr(ingest, "_now_iso", lambda: "2026-09-08T00:00:00Z")
    monkeypatch.setattr(ingest, "_fetch_url", lambda *a, **k: "<html>Unavailable</html>")
    result = ingest.ingest_rba_h5(con)
    assert all(row["status"] == "error" for row in result.values())
    row = con.execute("SELECT last_checked_at,last_success_at,status FROM ingest_runs LIMIT 1").fetchone()
    assert row == ("2026-09-08T00:00:00Z", NOW, "error")
    assert con.execute("SELECT * FROM series_observations").fetchall() == before
    con.close()


def test_live_macro_reader_sees_committed_wal_rows(tmp_path):
    store = tmp_path / "macro.sqlite"
    writer = ingest.open_store(store)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE sentinel(value TEXT)")
    writer.execute("INSERT INTO sentinel VALUES ('committed')")
    writer.commit()
    assert store.with_name(store.name + "-wal").stat().st_size > 0
    with read_store(store) as reader:
        assert reader.execute("SELECT value FROM sentinel").fetchone() == ("committed",)
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("DELETE FROM sentinel")
    writer.close()


def test_old_success_is_stale_in_v2_and_catalog(tmp_path, monkeypatch):
    store = tmp_path / "macro.sqlite"
    seed_store(store, monkeypatch)
    payload = app_payload_v2.build_economic_outlook(store, generated_at="2026-09-10T00:00:00Z")
    series = {row["id"]: row for row in payload["series"]}
    assert series["unemployment_rate"]["freshness"]["status"] == "stale"
    assert series["unemployment_rate"]["freshness"]["last_success_at"] == NOW
    assert series["hours_worked"]["freshness"]["status"] == "missing"
    monkeypatch.setattr(local, "_MACRO_STORE_PATH", tmp_path / "missing.sqlite")
    catalog = json.loads(local.economic_catalog_payload()[0])
    assert all(row["freshness"]["status"] != "ok" for group in catalog["categories"] for row in group["series"])


def test_unavailable_series_is_explicit_and_does_not_fall_back_to_vendored_data(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "_MACRO_STORE_PATH", tmp_path / "missing.sqlite")
    payload = json.loads(local.economic_series_payload(["unemployment_rate"], None, None)[0])
    assert payload["series"][0]["points"] == []
    assert payload["series"][0]["freshness"]["status"] == "missing"
    assert json.loads(local.economic_health_payload()[0])["ok"] is False


@pytest.mark.parametrize("store_state", ["absent", "unreadable", "empty"])
def test_missing_cpi_store_is_missing_in_every_public_reader(tmp_path, monkeypatch, store_state):
    store = tmp_path / "macro.sqlite"
    if store_state == "unreadable":
        store.write_bytes(b"not a SQLite database")
    elif store_state == "empty":
        ingest.open_store(store).close()
    monkeypatch.setattr(local, "_MACRO_STORE_PATH", store)
    payload = app_payload_v2.build_economic_outlook(store, generated_at=NOW)
    series = {row["id"]: row for row in payload["series"]}
    catalog = json.loads(local.economic_catalog_payload()[0])
    catalog_series = {row["id"]: row for group in catalog["categories"] for row in group["series"]}
    health = json.loads(local.economic_health_payload()[0])
    for sid in ABS_CPI_M_SERIES:
        assert series[sid]["freshness"]["status"] == "missing"
        assert series[sid]["observations"] == []
        assert catalog_series[sid]["freshness"]["status"] == "missing"
        assert health["series_status"][sid] == "missing"
    assert health["freshness_counts"]["error"] == 0
    assert health["ok"] is False
    if store_state == "absent":
        assert not store.exists()


@pytest.mark.parametrize("stored", [
    None, {},
    {"status": "ok", "source_url": "https://data.api.abs.gov.au/rest/data/CPI_M/all?format=csv"},
    {"status": "ok", "last_checked_at": NOW, "last_success_at": NOW, "last_observation_date": "2026-07-31"},
])
def test_incomplete_cpi_metadata_cannot_prove_a_retired_definition(stored):
    for sid in ABS_CPI_M_SERIES:
        result = freshness.assess_freshness(sid, stored, frequency="monthly", now=NOW)
        assert result["status"] == "missing"
        assert "retired" not in result["message"]


def test_fresh_check_cannot_make_retired_or_overdue_observations_current():
    stored = {"last_checked_at": NOW, "last_success_at": NOW, "last_observation_date": "2025-09-30", "status": "ok"}
    result = freshness.assess_freshness("unemployment_rate", stored, frequency="monthly", now=NOW)
    assert result["status"] == "stale" and result["observation_overdue"]
    stored["source_url"] = "https://data.api.abs.gov.au/rest/data/CPI_M/all?format=csv"
    assert freshness.assess_freshness("monthly_cpi_indicator", stored, frequency="monthly", now=NOW)["status"] == "error"


def test_refresh_timeout_keeps_cooldown_and_releases_lock(tmp_path, monkeypatch):
    calls = []
    def timeout(*args, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(refresh.subprocess, "run", timeout)
    store = tmp_path / "macro.sqlite"
    assert refresh.refresh_macro_store(store, repo_root=tmp_path)["status"] == "timeout"
    assert refresh.refresh_macro_store(store, repo_root=tmp_path)["status"] == "cooldown"
    assert len(calls) == 1 and calls[0]["timeout"] == 180
    lock = tmp_path / "macro-refresh-status.lock"
    assert lock.exists()
    with refresh._refresh_lock(lock) as acquired:
        assert acquired


def test_old_lock_file_is_never_reclaimed_and_only_one_caller_launches(tmp_path, monkeypatch):
    lock = tmp_path / "macro-refresh-status.lock"
    lock.write_bytes(b"0")
    old_time = time.time() - 7200
    os.utime(lock, (old_time, old_time))
    original = lock.stat()
    acquired, release = threading.Event(), threading.Event()
    save = refresh._save
    calls = []
    def paused_save(path, value):
        if value["status"] == "running":
            acquired.set()
            assert release.wait(5)
        save(path, value)
    monkeypatch.setattr(refresh, "_save", paused_save)
    monkeypatch.setattr(refresh.subprocess, "run", lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0, stdout='{"source": {}}', stderr=""))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(refresh.refresh_macro_store, tmp_path / "macro.sqlite", repo_root=tmp_path)
        try:
            assert acquired.wait(5)
            assert refresh.refresh_macro_store(tmp_path / "macro.sqlite", repo_root=tmp_path)["status"] == "busy"
        finally:
            release.set()
        assert first.result()["status"] == "ok"
    assert len(calls) == 1
    assert lock.stat().st_ino == original.st_ino
    assert lock.stat().st_mtime_ns == original.st_mtime_ns


def test_refresh_partial_result_is_not_success(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout='{"source": {}}', stderr="upstream failure"))
    result = refresh.refresh_macro_store(tmp_path / "macro.sqlite", repo_root=tmp_path)
    assert result["status"] == "partial" and result["returncode"] == 1


def test_daily_hook_uses_canonical_store_and_propagates_nonfatal_status(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pi_daily_sync, "refresh_macro_store", lambda store, **kwargs: calls.append((store, kwargs)) or {"status": "partial"})
    assert pi_daily_sync.refresh_economic_data(tmp_path)["status"] == "partial"
    assert calls == [(pi_daily_sync.DEFAULT_MACRO_STORE_PATH, {"repo_root": tmp_path})]


def test_daily_macro_failure_does_not_fail_bank_capture(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("macro store unavailable")
    monkeypatch.setattr(pi_daily_sync, "refresh_macro_store", fail)
    assert pi_daily_sync.refresh_economic_data(tmp_path)["status"] == "error"


@pytest.mark.parametrize("url", ["http://www.rba.gov.au/a", "https://localhost/a", "https://www.rba.gov.au:123/a", "https://user:token@www.rba.gov.au/a"])
def test_transport_rejects_untrusted_endpoints(url):
    with pytest.raises(ValueError, match="approved"):
        http.fetch_url(url)


def test_transport_caps_response_size(monkeypatch):
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size):
            calls.append(size)
            return b"x" * size
    monkeypatch.setattr(http.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=lambda *a, **k: Response()))
    monkeypatch.setattr(http, "MAX_RESPONSE_BYTES", 16)
    with pytest.raises(ValueError, match="byte budget"):
        http.fetch_url("https://www.rba.gov.au/data.csv")
    assert calls == [17]


@pytest.mark.parametrize("code,attempts", [(429, 2), (503, 2), (404, 1)])
def test_transport_retries_only_transient_failures(monkeypatch, code, attempts):
    calls, sleeps = [], []
    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise urllib.error.HTTPError("https://www.rba.gov.au/data.csv", code, "upstream", {"Retry-After": "9999"}, None)
    monkeypatch.setattr(http.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=fail))
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    with pytest.raises(urllib.error.HTTPError):
        http.fetch_url("https://www.rba.gov.au/data.csv")
    assert len(calls) == attempts
    assert sleeps == ([5] if attempts == 2 else [])
