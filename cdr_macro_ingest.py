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
hours_worked); PR1c.3 adds household_spending_indicator (HSI_M, monthly)
and lending_indicator_housing (LEND_HOUSING, quarterly); PR1c.4 adds
building_approvals_abs (BA_GCCSA, monthly, fetched via an SDMX REST
key-filtered URL because the unfiltered dataflow is ~3.6 GB); PR1b.x
adds RBA H3 (dwelling_approvals, consumer_sentiment, business_conditions);
PR1c.5 adds ABS WPI + JV (abs_wage_price_index, job_vacancies); PR1b.y
adds RBA G1 + G3 (trimmed_mean_cpi, inflation_expectations); PR1b.z
adds RBA H4 (wage_growth) and H2 (household_consumption, public_demand);
PR1b.aa adds RBA F1.1 (bank_bill_30d/90d/180d), F11 (aud_twi), I2
(commodity_prices), and D1 (housing_credit_growth); PR1b.bb adds RBA
J1 star-variables (neutral_rate, capacity_utilisation_proxy). PR1d/PR1e
extend the same pattern.

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
import math
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from concurrent.futures import ThreadPoolExecutor

from cdr_macro_http import HTTP_TIMEOUT_SECONDS, USER_AGENT, fetch_url
from cdr_macro_sources import RBA_SERIES_CODES, RBA_UNITS, SOURCE_FAMILIES
from cdr_macro_transition import archive_cpi_predecessor, archive_schema_sql

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STORE_PATH = BASE_DIR / "state" / "local-macro.sqlite"

from cdr_macro_sources import (
    RBA_H5_URL,
    RBA_H5_COLUMNS,
    RBA_H3_URL,
    RBA_H3_COLUMNS,
    RBA_G1_URL,
    RBA_G1_COLUMNS,
    RBA_G3_URL,
    RBA_G3_COLUMNS,
    RBA_H4_URL,
    RBA_H4_COLUMNS,
    RBA_H2_URL,
    RBA_H2_COLUMNS,
    RBA_F1_1_URL,
    RBA_F1_1_COLUMNS,
    RBA_F11_URL,
    RBA_F11_COLUMNS,
    RBA_I2_URL,
    RBA_I2_COLUMNS,
    RBA_D1_URL,
    RBA_D1_COLUMNS,
    RBA_J1_URL,
    RBA_J1_COLUMNS,
    ABS_DATA_API_BASE,
    ABS_CPI_M_URL,
    ABS_CPI_M_SERIES,
    ABS_LF_UNDER_URL,
    ABS_LF_UNDER_SERIES,
    ABS_LF_HOURS_URL,
    ABS_LF_HOURS_SERIES,
    ABS_HSI_M_URL,
    ABS_HSI_M_SERIES,
    ABS_LEND_HOUSING_URL,
    ABS_LEND_HOUSING_SERIES,
    ABS_BA_GCCSA_URL,
    ABS_BA_GCCSA_SERIES,
    ABS_WPI_URL,
    ABS_WPI_SERIES,
    ABS_JV_URL,
    ABS_JV_SERIES,
)


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
    ] + archive_schema_sql()


def open_store(store_path: Path = DEFAULT_STORE_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the local-macro SQLite store and ensure schema.

    Uses the URI form ``file:<resolved-path>`` (Gemini PR #118) so a path
    with reserved URI characters round-trips safely. The caller is
    responsible for ``con.close()``.
    """
    store_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(store_path.resolve().as_uri(), uri=True, timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL")
    for stmt in _schema_sql():
        con.execute(stmt)
    con.commit()
    return con


_MONTH_ABBR = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_dd_mon_yyyy(raw: str) -> str | None:
    """Parse a strict ``DD-Mon-YYYY`` token (e.g. ``22-May-2026``) to ISO.

    Enforces 1–2 digit day, 3-letter English month, 4-digit year — so
    inputs like ``22-May-26`` or ``22-May-+2026`` (which ``strptime`` would
    also reject) are returned as None instead of silently producing
    ``0026-05-22``. Month-abbrev lookup is hand-rolled (not strptime
    ``%b``) so non-English ``LC_TIME`` hosts still parse the English RBA
    month names — Codex P2 locale-safety lesson from PR #129.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    parts = raw.split("-")
    if len(parts) != 3:
        return None
    day_str, mon_str, year_str = parts
    if not (1 <= len(day_str) <= 2 and day_str.isdigit()):
        return None
    if len(mon_str) != 3:
        return None
    if len(year_str) != 4 or not year_str.isdigit():
        return None
    month = _MONTH_ABBR.get(mon_str.capitalize())
    if month is None:
        return None
    try:
        return date(int(year_str), month, int(day_str)).isoformat()
    except ValueError:
        return None


def _parse_rba_date(raw: str) -> str | None:
    """Parse an RBA tables date column.

    Most RBA statistical tables use ``DD/MM/YYYY`` for the obs-date
    column. A handful (e.g. F11 exchange rates) instead use
    ``DD-Mon-YYYY`` -- the same format the header-row publication date
    uses. Try both. Returns ISO ``YYYY-MM-DD`` or None.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
    except ValueError:
        pass
    return _parse_dd_mon_yyyy(raw)


def _parse_publication_date(raw: str) -> str | None:
    """RBA tables publication date is DD-Mon-YYYY (e.g. 22-May-2026)."""
    return _parse_dd_mon_yyyy(raw)


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
    series_row: list[str] | None = None
    units_row: list[str] | None = None
    for row in reader:
        if not row:
            continue
        first = (row[0] or "").strip()
        if first == "Title":
            title_row = row
        elif first == "Publication date":
            publication_row = row
        elif first == "Units":
            units_row = row
        elif first == "Series ID":
            # Marker that the header section is over; the very next non-empty
            # row begins the data.
            series_row = row
            break
    if title_row is None:
        raise ValueError("RBA CSV is missing a 'Title' header row")

    # Map AR series_id -> column index in the data rows.
    col_index_for: dict[str, int] = {}
    for series_id, header in columns.items():
        code = RBA_SERIES_CODES.get(series_id)
        candidates = series_row if code and series_row else title_row
        selector = code if code and series_row else header
        if candidates.count(selector) != 1:
            continue  # absent or ambiguous identity; never guess a neighbour
        idx = candidates.index(selector)
        if code:
            expected_unit = RBA_UNITS[series_id]
            unit = units_row[idx].strip() if units_row and idx < len(units_row) else ""
            if unit != expected_unit and not (expected_unit == "Index" and unit.startswith("Index,")):
                continue  # scale drift is an error for this series only
        col_index_for[series_id] = idx

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
                raise ValueError(f"invalid numeric observation for {series_id} at {obs_date}")
            if not math.isfinite(value):
                raise ValueError(f"non-finite observation for {series_id} at {obs_date}")
            out[series_id].append((obs_date, value, release_date_for.get(series_id)))
    for rows in out.values():
        rows.sort(key=lambda row: row[0])
    return out


def _fetch_url(url: str, accept: str = "text/csv") -> str:
    return fetch_url(url, accept)


def _parse_abs_period(raw: str) -> str | None:
    """SDMX TIME_PERIOD for ABS data: monthly ``YYYY-MM`` or quarterly
    ``YYYY-Qn``.

    Returned as end-of-period ISO date so daily forward-fill (in
    ``cdr_economic_local._build_series_points``) doesn't surface a
    period's value before the period is complete. Matches the RBA H5
    convention. Quarter endings: Q1=Mar 31, Q2=Jun 30, Q3=Sep 30,
    Q4=Dec 31.
    """
    raw = (raw or "").strip()
    if len(raw) != 7 or raw[4] != "-":
        return None
    try:
        year = int(raw[0:4])
    except ValueError:
        return None
    if raw[5] == "Q":
        try:
            quarter = int(raw[6])
        except ValueError:
            return None
        if quarter not in (1, 2, 3, 4):
            return None
        end_month = quarter * 3
        last_day = calendar.monthrange(year, end_month)[1]
        return f"{year:04d}-{end_month:02d}-{last_day:02d}"
    try:
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
            if dim_name.startswith("UNIT_"):
                continue
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
        for sid, pairs in matchers.items():
            if pairs is None:
                continue
            if all(idx < len(row) and (row[idx] or "").strip() == expected for idx, expected in pairs):
                for name, expected in series_filters[sid].items():
                    if not name.startswith("UNIT_"):
                        continue
                    idx = col_for.get(name)
                    if idx is None or idx >= len(row) or row[idx].strip() != expected:
                        raise ValueError(f"source unit changed for {sid}: expected {name}={expected}")
                try:
                    value = float(cell)
                except ValueError:
                    raise ValueError(f"invalid numeric observation for {sid} at {obs_date}")
                if not math.isfinite(value):
                    raise ValueError(f"non-finite observation for {sid} at {obs_date}")
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

    parsed, parse_errors = _parse_series_independently(text, series_filters, parse_abs_sdmx_csv)
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    con.execute("SAVEPOINT macro_source_update")
    try:
        for series_id in series_filters:
            rows = parsed.get(series_id, [])
            if not rows:
                message = parse_errors.get(series_id) or "no rows matched filter (upstream schema or codes may have changed)"
                record_run(con, series_id, status="error", message=message, source_url=source_url, success=False)
                results[series_id] = {"status": "error", "message": message, "rows": 0}
                continue
            archive_cpi_predecessor(con, series_id, source_url)
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
        con.execute("RELEASE SAVEPOINT macro_source_update")
    except (sqlite3.Error, ValueError) as exc:
        con.execute("ROLLBACK TO SAVEPOINT macro_source_update")
        con.execute("RELEASE SAVEPOINT macro_source_update")
        message = f"source update rolled back: {exc}"
        results = {}
        for series_id in series_filters:
            record_run(con, series_id, status="error", message=message,
                       source_url=source_url, success=False)
            results[series_id] = {"status": "error", "message": message, "rows": 0}
    con.commit()
    return results


def _parse_series_independently(text: str, selectors: dict, parser) -> tuple[dict, dict]:
    """Fetch once, isolate unit/numeric/identity drift to the affected series."""
    parsed, errors = {}, {}
    for series_id, selector in selectors.items():
        try:
            parsed.update(parser(text, {series_id: selector}))
        except (ValueError, csv.Error) as exc:
            errors[series_id] = f"source parse failed: {exc}"
    return parsed, errors


def ingest_abs_cpi_m(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS CPI_M dataflow and upsert series mapped in ``ABS_CPI_M_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_CPI_M_URL, ABS_CPI_M_SERIES)


def ingest_abs_lf_under(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS LF_UNDER and upsert series mapped in ``ABS_LF_UNDER_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_LF_UNDER_URL, ABS_LF_UNDER_SERIES)


def ingest_abs_lf_hours(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS LF_HOURS and upsert series mapped in ``ABS_LF_HOURS_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_LF_HOURS_URL, ABS_LF_HOURS_SERIES)


def ingest_abs_hsi_m(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS HSI_M and upsert series mapped in ``ABS_HSI_M_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_HSI_M_URL, ABS_HSI_M_SERIES)


def ingest_abs_lend_housing(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS LEND_HOUSING and upsert series mapped in ``ABS_LEND_HOUSING_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_LEND_HOUSING_URL, ABS_LEND_HOUSING_SERIES)


def ingest_abs_ba_gccsa(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch the key-filtered ABS BA_GCCSA slice for ``building_approvals_abs``."""
    return _ingest_abs_sdmx_csv(con, ABS_BA_GCCSA_URL, ABS_BA_GCCSA_SERIES)


def ingest_abs_wpi(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS WPI and upsert series mapped in ``ABS_WPI_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_WPI_URL, ABS_WPI_SERIES)


def ingest_abs_jv(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch ABS JV and upsert series mapped in ``ABS_JV_SERIES``."""
    return _ingest_abs_sdmx_csv(con, ABS_JV_URL, ABS_JV_SERIES)


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
              source_url = CASE WHEN excluded.status = 'ok' THEN excluded.source_url
                  ELSE COALESCE(ingest_runs.source_url, excluded.source_url) END""",
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


def _ingest_rba_csv(
    con: sqlite3.Connection,
    source_url: str,
    columns: dict[str, str],
) -> dict[str, dict[str, object]]:
    """Common ingest loop for any RBA statistical-tables CSV.

    Fetches ``source_url``, parses with ``parse_rba_csv`` against the
    given AR-series-id -> CSV-column-header mapping, upserts
    observations, and records freshness rows. Schema-drift handling
    matches PR #118 review feedback: parse failures error every
    expected series; columns missing from the upstream CSV error
    only the affected series; columns present but empty also error
    only the affected series.
    """
    results: dict[str, dict[str, object]] = {}
    try:
        text = _fetch_url(source_url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        message = f"fetch or parse failed: {exc}"
        for series_id in columns:
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

    parsed, parse_errors = _parse_series_independently(text, columns, parse_rba_csv)
    missing_columns = set(columns) - set(parsed)
    for series_id in missing_columns:
        message = parse_errors.get(series_id) or f"upstream column missing: {columns[series_id]!r}"
        record_run(con, series_id, status="error", message=message, source_url=source_url, success=False)
        results[series_id] = {"status": "error", "message": message, "rows": 0}

    for series_id, rows in parsed.items():
        if not rows:
            message = "column present but no rows parsed"
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


def ingest_rba_h5(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA H5 and upsert the columns mapped in ``RBA_H5_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_H5_URL, RBA_H5_COLUMNS)


def ingest_rba_h3(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA H3 and upsert the columns mapped in ``RBA_H3_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_H3_URL, RBA_H3_COLUMNS)


def ingest_rba_g1(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA G1 (CPI inflation) and upsert the columns mapped in ``RBA_G1_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_G1_URL, RBA_G1_COLUMNS)


def ingest_rba_g3(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA G3 (inflation expectations) and upsert the columns mapped in ``RBA_G3_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_G3_URL, RBA_G3_COLUMNS)


def ingest_rba_h4(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA H4 (labour costs) and upsert the columns mapped in ``RBA_H4_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_H4_URL, RBA_H4_COLUMNS)


def ingest_rba_h2(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA H2 (demand and income) and upsert the columns mapped in ``RBA_H2_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_H2_URL, RBA_H2_COLUMNS)


def ingest_rba_f1_1(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA F1.1 (money market rates) and upsert the columns mapped in ``RBA_F1_1_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_F1_1_URL, RBA_F1_1_COLUMNS)


def ingest_rba_f11(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA F11 (exchange rates) and upsert the columns mapped in ``RBA_F11_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_F11_URL, RBA_F11_COLUMNS)


def ingest_rba_i2(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA I2 (commodity prices) and upsert the columns mapped in ``RBA_I2_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_I2_URL, RBA_I2_COLUMNS)


def ingest_rba_d1(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA D1 (financial aggregates) and upsert the columns mapped in ``RBA_D1_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_D1_URL, RBA_D1_COLUMNS)


def ingest_rba_j1(con: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Fetch RBA J1 star-variables and upsert the columns mapped in ``RBA_J1_COLUMNS``."""
    return _ingest_rba_csv(con, RBA_J1_URL, RBA_J1_COLUMNS)


def _refresh_family(item: tuple[str, tuple], store: Path) -> tuple[str, dict]:
    name, (url, selectors) = item
    con = open_store(store)
    try:
        ingest = _ingest_rba_csv if name.startswith("rba_") else _ingest_abs_sdmx_csv
        return name, ingest(con, url, selectors)
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh official macro sources with bounded concurrency")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--source", choices=[*SOURCE_FAMILIES, "all"], default="all")
    parser.add_argument("--workers", type=int, choices=range(1, 4), default=3)
    args = parser.parse_args(argv)
    # Initialise once before parallel readers/writers. Each source commits on
    # its own connection; a timed-out batch preserves completed source refreshes.
    open_store(args.store).close()
    sources = [(name, spec) for name, spec in SOURCE_FAMILIES.items()
               if args.source in (name, "all")]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = pool.map(lambda item: _refresh_family(item, args.store), sources)
        report = dict(results)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return int(any(row.get("status") != "ok" for family in report.values() for row in family.values()))


if __name__ == "__main__":
    sys.exit(main())
