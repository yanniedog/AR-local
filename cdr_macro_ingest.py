"""Ingest macro time series from public sources into a local SQLite store.

The Economic Data dashboard's ``/api/economic-data/series`` endpoint is being
migrated from a passthrough proxy to the australianrates upstream toward a
locally-served implementation. This module is the data half: it fetches
public CSV/JSON sources, parses them, and persists observations into
``state/local-macro.sqlite``. ``cdr_economic_local.economic_series_payload``
then reads from that store to build the wire response.

Each ingest source is registered in a per-family mapping
(``RBA_H5_COLUMNS``, ``ABS_CPI_M_SERIES``, ``ABS_LF_UNDER_SERIES``,
``ABS_LF_HOURS_SERIES`` etc.). PR1b shipped RBA H5 (unemployment_rate,
participation_rate); PR1c added ABS CPI_M (monthly_cpi_indicator,
monthly_trimmed_mean_cpi); PR1c.2 adds ABS labour-force coverage
(employment_to_population, underemployment_rate, underutilisation_rate,
hours_worked). PR1d/PR1e extend the same pattern.

Run standalone to populate the store:

    python cdr_macro_ingest.py                       # all sources
    python cdr_macro_ingest.py --source abs_lf_under

Or import ``ingest_rba_h5(con)`` / ``ingest_abs_cpi_m(con)`` /
``ingest_abs_lf_under(con)`` / ``ingest_abs_lf_hours(con)`` from
elsewhere (e.g. the daily timer script) to refresh just one source
family. The ingest is idempotent: rows are upserted by
``(series_id, observation_date)``, so re-running with no upstream
change is a no-op.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STORE_PATH = BASE_DIR / "state" / "local-macro.sqlite"

USER_AGENT = "Mozilla/5.0 (compatible; AR-local macro ingest)"
HTTP_TIMEOUT_SECONDS = 60.0

# Mapping from AR catalog series_id -> CSV column header in the RBA H5 table.
# RBA H5 ("Labour force") CSV column headers come from the "Title" header row.
# The dashboard catalog uses friendlier IDs (`unemployment_rate`,
# `participation_rate`) — those are the IDs the frontend sends. The CSV
# column header is what we look up inside the table.
RBA_H5_URL = "https://www.rba.gov.au/statistics/tables/csv/h5-data.csv"
RBA_H5_COLUMNS: dict[str, str] = {
    "unemployment_rate": "Unemployment rate",
    "participation_rate": "Participation rate",
}

# ABS Data API (SDMX), dataflow CPI_M (Monthly CPI Indicator). The "all"
# key fetches every series in the dataflow; we filter client-side against
# ``ABS_CPI_M_SERIES`` so the URL is stable even if dimension ordering
# changes. Codes verified against a live response from CPI_M v1.2.0:
#   MEASURE=3   Percentage change from corresponding month previous year
#   INDEX=10001  All groups CPI
#   INDEX=999905 Annual trimmed mean
#   TSEST=10    Original (only TSEST published for these % change measures)
#   REGION=50   Australia (the only REGION present in CPI_M)
#   FREQ=M      Monthly
# The dataflow identifier is bare ``CPI_M``; the fully-qualified form
# ``ABS,CPI_M,<version>`` 404s on the /rest/data endpoint. If upstream
# renames or removes a code, the affected series matches zero rows and
# ingest_runs.status flips to error -- same drift-detection pattern as
# RBA H5.
ABS_DATA_API_BASE = "https://data.api.abs.gov.au/rest/data"
ABS_CPI_M_URL = f"{ABS_DATA_API_BASE}/CPI_M/all?format=csv"
ABS_CPI_M_SERIES: dict[str, dict[str, str]] = {
    "monthly_cpi_indicator": {
        "MEASURE": "3",
        "INDEX": "10001",
        "TSEST": "10",
        "REGION": "50",
        "FREQ": "M",
    },
    "monthly_trimmed_mean_cpi": {
        "MEASURE": "3",
        "INDEX": "999905",
        "TSEST": "10",
        "REGION": "50",
        "FREQ": "M",
    },
}

# ABS Data API dataflow LF_UNDER (Labour Force: underemployment and
# underutilisation). Same dimension layout as LF but with PARM_ITEM
# instead of MEASURE for the measure axis; carries the standard M*
# labour codes (M16 employment-to-pop, M23 underemployment rate,
# M24 underutilisation rate). Codes verified against LF_UNDER v1.0.1.
ABS_LF_UNDER_URL = f"{ABS_DATA_API_BASE}/LF_UNDER/all?format=csv"
ABS_LF_UNDER_SERIES: dict[str, dict[str, str]] = {
    "employment_to_population": {
        "PARM_ITEM": "M16",
        "SEX": "3",  # Persons
        "AGE": "1599",  # Total
        "TSEST": "20",  # Seasonally Adjusted (headline reporting convention)
        "REGION": "AUS",
        "FREQ": "M",
    },
    "underemployment_rate": {
        "PARM_ITEM": "M23",
        "SEX": "3",
        "AGE": "1599",
        "TSEST": "20",
        "REGION": "AUS",
        "FREQ": "M",
    },
    "underutilisation_rate": {
        "PARM_ITEM": "M24",
        "SEX": "3",
        "AGE": "1599",
        "TSEST": "20",
        "REGION": "AUS",
        "FREQ": "M",
    },
}

# ABS Data API dataflow LF_HOURS (Hours worked by sector). Adds a
# HOURS dimension on top of LF's layout; we filter to HOURS=TOT
# (Industry Total). M18 = Employed Persons - Monthly hours worked
# in all jobs (the standard "hours worked" headline). Codes verified
# against LF_HOURS v1.0.0.
ABS_LF_HOURS_URL = f"{ABS_DATA_API_BASE}/LF_HOURS/all?format=csv"
ABS_LF_HOURS_SERIES: dict[str, dict[str, str]] = {
    "hours_worked": {
        "MEASURE": "M18",
        "SEX": "3",
        "AGE": "1599",
        "HOURS": "TOT",
        "TSEST": "20",
        "REGION": "AUS",
        "FREQ": "M",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _schema_sql() -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS series_observations (
            series_id TEXT NOT NULL,
            observation_date TEXT NOT NULL,
            raw_value REAL,
            release_date TEXT,
            PRIMARY KEY (series_id, observation_date)
        )""",
        """CREATE TABLE IF NOT EXISTS ingest_runs (
            series_id TEXT PRIMARY KEY,
            last_checked_at TEXT,
            last_success_at TEXT,
            last_observation_date TEXT,
            last_value REAL,
            status TEXT,
            message TEXT,
            source_url TEXT
        )""",
    ]


def open_store(store_path: Path = DEFAULT_STORE_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the local-macro SQLite store and ensure schema.

    Uses the URI form ``file:<resolved-path>`` (Gemini PR #118) so a path
    with reserved URI characters round-trips safely. The caller is
    responsible for ``con.close()``.
    """
    store_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(store_path.resolve().as_uri(), uri=True)
    con.execute("PRAGMA journal_mode=WAL")
    for stmt in _schema_sql():
        con.execute(stmt)
    con.commit()
    return con


def _parse_rba_date(raw: str) -> str | None:
    """RBA tables date column is DD/MM/YYYY. Return ISO YYYY-MM-DD or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _parse_publication_date(raw: str) -> str | None:
    """RBA tables publication date is DD-Mon-YYYY (e.g. 22-May-2026)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def parse_rba_csv(text: str, columns: dict[str, str]) -> dict[str, list[tuple[str, float | None, str | None]]]:
    """Parse an RBA statistical-tables CSV.

    Returns ``{series_id: [(observation_date, raw_value, release_date), ...]}``
    where ``columns`` maps the AR catalog ``series_id`` to the column header
    string in the CSV's ``Title`` row. Unknown / unmatched columns are
    skipped; the data half is left intact for the caller's filtering.
    """
    reader = csv.reader(io.StringIO(text))
    title_row: list[str] | None = None
    publication_row: list[str] | None = None
    for row in reader:
        if not row:
            continue
        first = (row[0] or "").strip()
        if first == "Title":
            title_row = row
        elif first == "Publication date":
            publication_row = row
        elif first == "Series ID":
            # Marker that the header section is over; the very next non-empty
            # row begins the data.
            break
    if title_row is None:
        raise ValueError("RBA CSV is missing a 'Title' header row")

    # Map AR series_id -> column index in the data rows.
    col_index_for: dict[str, int] = {}
    for series_id, header in columns.items():
        try:
            col_index_for[series_id] = title_row.index(header)
        except ValueError:
            continue  # column not present in this table — caller can detect

    # Map AR series_id -> publication date (release_date for every obs in the column).
    release_date_for: dict[str, str | None] = {}
    if publication_row is not None:
        for series_id, idx in col_index_for.items():
            release_date_for[series_id] = _parse_publication_date(
                publication_row[idx] if idx < len(publication_row) else ""
            )

    out: dict[str, list[tuple[str, float | None, str | None]]] = {sid: [] for sid in col_index_for}
    for row in reader:
        if not row:
            continue
        obs_date = _parse_rba_date(row[0])
        if not obs_date:
            continue
        for series_id, idx in col_index_for.items():
            if idx >= len(row):
                continue
            cell = (row[idx] or "").strip()
            if not cell:
                continue
            try:
                value = float(cell)
            except ValueError:
                continue
            out[series_id].append((obs_date, value, release_date_for.get(series_id)))
    return out


def _fetch_url(url: str, accept: str = "text/csv") -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return resp.read().decode("utf-8-sig")


def _parse_abs_period(raw: str) -> str | None:
    """SDMX TIME_PERIOD for monthly ABS data is ``YYYY-MM``.

    Returned as end-of-month ISO date so daily forward-fill (in
    ``cdr_economic_local._build_series_points``) doesn't surface a month's
    value before the month is even complete. Matches the RBA H5 convention.
    """
    raw = (raw or "").strip()
    if len(raw) != 7 or raw[4] != "-":
        return None
    try:
        year = int(raw[0:4])
        month = int(raw[5:7])
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-{last_day:02d}"
    except ValueError:
        return None


def parse_abs_sdmx_csv(
    text: str, series_filters: dict[str, dict[str, str]]
) -> dict[str, list[tuple[str, float | None, str | None]]]:
    """Parse an ABS Data API SDMX-CSV response.

    The header row contains both dimension columns (FREQ, MEASURE, INDEX, ...)
    and TIME_PERIOD + OBS_VALUE. For each filter in ``series_filters`` we
    accept any row whose dimension columns match every key/value pair.
    Unknown filter columns are treated as a non-match (drift detection:
    the caller will see zero rows and record an error).

    Release date is left as None -- the SDMX-CSV doesn't carry per-row
    release dates and the catalog metadata covers source attribution.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return {sid: [] for sid in series_filters}
    col_for = {name: idx for idx, name in enumerate(h.strip() for h in header)}
    if "TIME_PERIOD" not in col_for or "OBS_VALUE" not in col_for:
        return {sid: [] for sid in series_filters}
    time_idx = col_for["TIME_PERIOD"]
    value_idx = col_for["OBS_VALUE"]

    # Precompute per-series (column_index, expected_value) pairs; if any
    # filter column is missing from the response, that series cannot match.
    matchers: dict[str, list[tuple[int, str]] | None] = {}
    for sid, filt in series_filters.items():
        pairs: list[tuple[int, str]] = []
        ok = True
        for dim_name, expected in filt.items():
            idx = col_for.get(dim_name)
            if idx is None:
                ok = False
                break
            pairs.append((idx, expected))
        matchers[sid] = pairs if ok else None

    out: dict[str, list[tuple[str, float | None, str | None]]] = {sid: [] for sid in series_filters}
    for row in reader:
        if not row or len(row) <= max(time_idx, value_idx):
            continue
        obs_date = _parse_abs_period(row[time_idx])
        if not obs_date:
            continue
        cell = (row[value_idx] or "").strip()
        if not cell:
            continue
        try:
            value = float(cell)
        except ValueError:
            continue
        for sid, pairs in matchers.items():
            if pairs is None:
                continue
            if all(idx < len(row) and (row[idx] or "").strip() == expected for idx, expected in pairs):
                out[sid].append((obs_date, value, None))
    for sid in out:
        out[sid].sort(key=lambda r: r[0])
    return out


def _ingest_abs_sdmx_csv(
    con: sqlite3.Connection,
    source_url: str,
    series_filters: dict[str, dict[str, str]],
) -> dict[str, dict[str, object]]:
    """Common ingest loop for any ABS Data API SDMX-CSV dataflow.

    Fetches ``source_url``, runs ``parse_abs_sdmx_csv`` against the
    provided per-series dimension filters, upserts observations, and
    records freshness rows. On fetch/parse failure every expected
    series_id is marked errored (same shape as RBA H5).
    """
    results: dict[str, dict[str, object]] = {}
    try:
        text = _fetch_url(source_url, accept="text/csv, application/vnd.sdmx.data+csv")
        parsed = parse_abs_sdmx_csv(text, series_filters)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        message = f"fetch or parse failed: {exc}"
        for series_id in series_filters:
            record_run(
                con,
                series_id,
                status="error",
                message=message,
                source_url=source_url,
                success=False,
            )
            results[series_id] = {"status": "error", "message": message, "rows": 0}
        con.commit()
        return results

    for series_id in series_filters:
        rows = parsed.get(series_id, [])
        if not rows:
            message = "no rows matched filter (upstream schema or codes may have changed)"
            record_run(con, series_id, status="error", message=message, source_url=source_url, success=False)
            results[series_id] = {"status": "error", "message": message, "rows": 0}
            continue
        upsert_observations(con, series_id, rows)
        last_obs_date, last_value, _ = rows[-1]
        record_run(
            con,
            series_id,
            status="ok",
            message=f"Source checked; {len(rows)} observations ingested.",
            source_url=source_url,
            last_observation_date=last_obs_date,
            last_value=last_value,
            success=True,
        )
        results[series_id] = {
            "status": "ok",
            "rows": len(rows),
            "last_observation_date": last_obs_date,
            "last_value": last_value,
        }
    con.commit()
    return results


def ingest_abs_cpi_m(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS CPI_M dataflow and upsert series mapped in ``ABS_CPI_M_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_CPI_M_URL, ABS_CPI_M_SERIES)


def ingest_abs_lf_under(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS LF_UNDER and upsert series mapped in ``ABS_LF_UNDER_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_LF_UNDER_URL, ABS_LF_UNDER_SERIES)


def ingest_abs_lf_hours(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS LF_HOURS and upsert series mapped in ``ABS_LF_HOURS_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_LF_HOURS_URL, ABS_LF_HOURS_SERIES)


def upsert_observations(
    con: sqlite3.Connection,
    series_id: str,
    rows: Iterable[tuple[str, float | None, str | None]],
) -> int:
    """Upsert series rows; returns row count inserted/updated."""
    payload = [(series_id, obs_date, value, release_date) for obs_date, value, release_date in rows]
    if not payload:
        return 0
    con.executemany(
        """INSERT INTO series_observations (series_id, observation_date, raw_value, release_date)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(series_id, observation_date) DO UPDATE SET
             raw_value = excluded.raw_value,
             release_date = excluded.release_date""",
        payload,
    )
    return len(payload)


def record_run(
    con: sqlite3.Connection,
    series_id: str,
    *,
    status: str,
    message: str,
    source_url: str,
    last_observation_date: str | None = None,
    last_value: float | None = None,
    success: bool,
) -> None:
    now = _now_iso()
    con.execute(
        """INSERT INTO ingest_runs (
              series_id, last_checked_at, last_success_at,
              last_observation_date, last_value, status, message, source_url
           )
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(series_id) DO UPDATE SET
              last_checked_at = excluded.last_checked_at,
              last_success_at = CASE
                  WHEN excluded.status = 'ok' THEN excluded.last_checked_at
                  ELSE ingest_runs.last_success_at
              END,
              last_observation_date = COALESCE(excluded.last_observation_date, ingest_runs.last_observation_date),
              last_value = COALESCE(excluded.last_value, ingest_runs.last_value),
              status = excluded.status,
              message = excluded.message,
              source_url = excluded.source_url""",
        (
            series_id,
            now,
            now if success else None,
            last_observation_date,
            last_value,
            status,
            message,
            source_url,
        ),
    )


def ingest_rba_h5(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA H5 and upsert the columns mapped in ``RBA_H5_COLUMNS``."""
    results: dict[str, dict[str, object]] = {}
    try:
        text = _fetch_url(RBA_H5_URL)
        parsed = parse_rba_csv(text, RBA_H5_COLUMNS)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # Wrap parse alongside fetch (Gemini PR #118): a malformed CSV
        # should surface as ingest errors for every expected series, not
        # crash the script with an unhandled exception.
        message = f"fetch or parse failed: {exc}"
        for series_id in RBA_H5_COLUMNS:
            record_run(
                con,
                series_id,
                status="error",
                message=message,
                source_url=RBA_H5_URL,
                success=False,
            )
            results[series_id] = {"status": "error", "message": message, "rows": 0}
        con.commit()
        return results

    # Schema-drift detection (Codex P2 PR #118): if the upstream CSV
    # renames or removes a column we expected, parse_rba_csv silently omits
    # that series_id from `parsed`. Surface it as an ingest error rather
    # than letting the dashboard keep serving stale prior-run data.
    missing_columns = set(RBA_H5_COLUMNS) - set(parsed)
    for series_id in missing_columns:
        message = f"upstream column missing: {RBA_H5_COLUMNS[series_id]!r}"
        record_run(con, series_id, status="error", message=message, source_url=RBA_H5_URL, success=False)
        results[series_id] = {"status": "error", "message": message, "rows": 0}

    for series_id, rows in parsed.items():
        if not rows:
            message = "column present but no rows parsed"
            record_run(con, series_id, status="error", message=message, source_url=RBA_H5_URL, success=False)
            results[series_id] = {"status": "error", "message": message, "rows": 0}
            continue
        upsert_observations(con, series_id, rows)
        last_obs_date, last_value, _ = rows[-1]
        record_run(
            con,
            series_id,
            status="ok",
            message=f"Source checked; {len(rows)} observations ingested.",
            source_url=RBA_H5_URL,
            last_observation_date=last_obs_date,
            last_value=last_value,
            success=True,
        )
        results[series_id] = {
            "status": "ok",
            "rows": len(rows),
            "last_observation_date": last_obs_date,
            "last_value": last_value,
        }
    con.commit()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest macro time series into state/local-macro.sqlite")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH, help="Path to the local-macro SQLite store")
    parser.add_argument(
        "--source",
        choices=["rba_h5", "abs_cpi_m", "abs_lf_under", "abs_lf_hours", "all"],
        default="all",
        help="Which source family to ingest (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    con = open_store(args.store)
    try:
        report: dict[str, object] = {}
        if args.source in ("rba_h5", "all"):
            report["rba_h5"] = ingest_rba_h5(con)
        if args.source in ("abs_cpi_m", "all"):
            report["abs_cpi_m"] = ingest_abs_cpi_m(con)
        if args.source in ("abs_lf_under", "all"):
            report["abs_lf_under"] = ingest_abs_lf_under(con)
        if args.source in ("abs_lf_hours", "all"):
            report["abs_lf_hours"] = ingest_abs_lf_hours(con)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
