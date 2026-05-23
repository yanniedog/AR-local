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
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
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

# RBA H3 "Monthly Activity Indicators". Same CSV layout as H5; the
# "Title" header row carries the human column names we map from. The
# three series we expose are all seasonally-adjusted monthly headlines
# the dashboard already references.
RBA_H3_URL = "https://www.rba.gov.au/statistics/tables/csv/h3-data.csv"
RBA_H3_COLUMNS: dict[str, str] = {
    "dwelling_approvals": "Private dwelling approvals",
    "consumer_sentiment": "Consumer sentiment",
    "business_conditions": "Business conditions",
}

# RBA G1 "Consumer Price Inflation" (quarterly). The Title row uses an
# en-dash (U+2013) in several column headers -- copy verbatim from the
# CSV to avoid a silent missing-column error. Column 10 is the headline
# RBA-trimmed-mean YoY measure the RBA tracks for monetary policy.
RBA_G1_URL = "https://www.rba.gov.au/statistics/tables/csv/g1-data.csv"
RBA_G1_COLUMNS: dict[str, str] = {
    "trimmed_mean_cpi": "Year-ended trimmed mean inflation – excluding interest charges and tax changes",
}

# RBA G3 "Inflation Expectations" (quarterly). Headline column is the
# Westpac-MI consumer 1-year-ahead measure (trimmed mean for 1-year
# ahead annual inflation rate; end-quarter observation).
RBA_G3_URL = "https://www.rba.gov.au/statistics/tables/csv/g3-data.csv"
RBA_G3_COLUMNS: dict[str, str] = {
    "inflation_expectations": "Consumer inflation expectations – 1-year ahead",
}

# RBA H4 "Labour Costs" (quarterly). Headline wage growth measure.
RBA_H4_URL = "https://www.rba.gov.au/statistics/tables/csv/h4-data.csv"
RBA_H4_COLUMNS: dict[str, str] = {
    "wage_growth": "Year-ended wage growth",
}

# RBA H2 "Household and Business Sector Demand and Income" (quarterly).
# Levels in $ millions; growth rates are sibling columns. Catalog
# advertises the level for household_consumption and public_demand.
RBA_H2_URL = "https://www.rba.gov.au/statistics/tables/csv/h2-data.csv"
RBA_H2_COLUMNS: dict[str, str] = {
    "household_consumption": "Household consumption",
    "public_demand": "Public demand",
}

# RBA F1.1 "Interest Rates and Yields - Money Market - Daily". Despite
# the name the catalog treats bank bills as monthly headlines; the
# upserter's PK is (series_id, observation_date) so daily upserts are
# safe and the dashboard forward-fill works either way.
RBA_F1_1_URL = "https://www.rba.gov.au/statistics/tables/csv/f1.1-data.csv"
RBA_F1_1_COLUMNS: dict[str, str] = {
    "bank_bill_30d": "1-month BABs/NCDs",
    "bank_bill_90d": "3-month BABs/NCDs",
    "bank_bill_180d": "6-month BABs/NCDs",
}

# RBA F11 "Exchange Rates - Monthly". Date column is DD-Mon-YYYY
# (handled by the dual-format _parse_rba_date).
RBA_F11_URL = "https://www.rba.gov.au/statistics/tables/csv/f11-data.csv"
RBA_F11_COLUMNS: dict[str, str] = {
    "aud_twi": "Trade-weighted Index May 1970 = 100",
}

# RBA I2 "Commodity Prices" (monthly). Catalog wants the A$-denominated
# headline index.
RBA_I2_URL = "https://www.rba.gov.au/statistics/tables/csv/i2-data.csv"
RBA_I2_COLUMNS: dict[str, str] = {
    "commodity_prices": "Commodity prices – A$",
}

# RBA D1 "Growth in Selected Financial Aggregates" (monthly). Catalog
# wants the housing-credit YoY growth rate.
RBA_D1_URL = "https://www.rba.gov.au/statistics/tables/csv/d1-data.csv"
RBA_D1_COLUMNS: dict[str, str] = {
    "housing_credit_growth": "Credit; Housing; 12-month ended growth",
}

# RBA J1 star-variables (RBA survey of professional forecasters, ~45
# semi-annual rows since 2015). Each row records the median, mean and
# range of forecaster estimates for the medium-to-long-term inflation,
# potential GDP growth, NAIRU, neutral interest rate and output gap.
# We expose the medians: neutral_rate (nominal neutral interest rate)
# and capacity_utilisation_proxy (output gap -- positive means demand
# is above capacity).
RBA_J1_URL = "https://www.rba.gov.au/statistics/tables/csv/j1-star-variables.csv"
RBA_J1_COLUMNS: dict[str, str] = {
    "neutral_rate": "Nominal neutral interest rate estimates – median",
    "capacity_utilisation_proxy": "Output gap – median",
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

# ABS Data API dataflow HSI_M (Monthly Household Spending Indicator).
# Codes verified against HSI_M v1.6.0:
#   MEASURE=9       Through the year percentage change (headline reporting)
#   CATEGORY=TOT    Total household spending
#   PRICE_ADJUSTMENT=CUR  Current Price (only option published)
#   TSEST=20        Seasonally Adjusted
#   STATE=AUS       Australia
#   FREQ=M          Monthly
# Note this dataflow uses ``STATE`` (not ``REGION``) for geography.
ABS_HSI_M_URL = f"{ABS_DATA_API_BASE}/HSI_M/all?format=csv"
ABS_HSI_M_SERIES: dict[str, dict[str, str]] = {
    "household_spending_indicator": {
        "MEASURE": "9",
        "CATEGORY": "TOT",
        "PRICE_ADJUSTMENT": "CUR",
        "TSEST": "20",
        "STATE": "AUS",
        "FREQ": "M",
    },
}

# ABS Data API dataflow LEND_HOUSING (Lending Indicators Housing
# Finance). Codes verified against LEND_HOUSING v1.1:
#   MEASURE=FIN_VAL    Value ($m)
#   DATA_ITEM=NEWCOMMITS  New loan commitments
#   LOAN_TYPE=DV8368   Total fixed term loans and revolving credit
#   LOAN_PURPOSE=TOTDWELL  Total dwellings excluding refinancing
#                       (the only purpose combinable with HOUSING_PURPOSE=TOT)
#   LENDER_TYPE=TOT    Total lender type
#   HOUSING_PURPOSE=TOT  Total housing purpose
#   TSEST=20           Seasonally Adjusted
#   REGION=AUS         Australia
#   FREQ=Q             Quarterly (ABS discontinued the monthly series in 2024)
# The catalog describes ``lending_indicator_housing`` as monthly; ABS
# now publishes only the quarterly aggregate -- the forward-fill in
# cdr_economic_local handles arbitrary observation cadences so this
# does not require a contract change.
ABS_LEND_HOUSING_URL = f"{ABS_DATA_API_BASE}/LEND_HOUSING/all?format=csv"
ABS_LEND_HOUSING_SERIES: dict[str, dict[str, str]] = {
    "lending_indicator_housing": {
        "MEASURE": "FIN_VAL",
        "DATA_ITEM": "NEWCOMMITS",
        "LOAN_TYPE": "DV8368",
        "LOAN_PURPOSE": "TOTDWELL",
        "LENDER_TYPE": "TOT",
        "HOUSING_PURPOSE": "TOT",
        "TSEST": "20",
        "REGION": "AUS",
        "FREQ": "Q",
    },
}

# ABS Data API dataflow BA_GCCSA (Building Approvals by GCCSA and above).
# Unlike the other ABS dataflows we already ingest, the unfiltered ``/all``
# response is ~3.6 GB (every measure x value-range x sector x work-type x
# building-type x TSEST x region x freq combination). We pin specific
# dimension values in the URL key (SDMX REST: positional dim values
# separated by ``.``) so the server returns only the headline residential
# approvals time series -- 53 KB, ~844 monthly observations since 1956.
#
# Codes verified against BA_GCCSA v1.0.0:
#   MEASURE=1        Number of dwelling units
#   VALUE=1          Total (i.e. not the $50K+/$1M+ value-range slices)
#   SECTOR=9         Total Sectors
#   WORK_TYPE=1      New (excludes alterations/additions/conversions)
#   BUILDING_TYPE=100  Total Residential
#   TSEST=10         Original (no SA published at AUS national monthly)
#   REGION=AUS
#   FREQ=M
# Key order matches the dataflow's dimension order:
# MEASURE.VALUE.SECTOR.WORK_TYPE.BUILDING_TYPE.TSEST.REGION.FREQ
ABS_BA_GCCSA_URL = (
    f"{ABS_DATA_API_BASE}/BA_GCCSA/1.1.9.1.100.10.AUS.M?format=csv"
)
ABS_BA_GCCSA_SERIES: dict[str, dict[str, str]] = {
    "building_approvals_abs": {
        "MEASURE": "1",
        "VALUE": "1",
        "SECTOR": "9",
        "WORK_TYPE": "1",
        "BUILDING_TYPE": "100",
        "TSEST": "10",
        "REGION": "AUS",
        "FREQ": "M",
    },
}

# ABS Data API dataflow WPI (Wage Price Index). Codes verified against
# WPI v1.0.0: MEASURE=3 (% change YoY), INDEX=THRPEB (Total hourly rates
# excluding bonuses -- the only INDEX with TSEST=20 published at the
# AUS combined-sector aggregate), SECTOR=7 (Private and Public),
# INDUSTRY=TOT (All Industries), TSEST=20 (SA), REGION=AUS, FREQ=Q.
# Note: INDEX=THRPIB (including bonuses) is published only as TSEST=10
# at this aggregate, so the headline SA wage measure uses THRPEB.
# URL key pins all 7 dimensions (MEASURE.INDEX.SECTOR.INDUSTRY.TSEST.REGION.FREQ)
# so the server returns only this series, mirroring the BA_GCCSA pattern
# (Gemini PR #126). Drops the response from ~11 MB to ~7 KB.
ABS_WPI_URL = f"{ABS_DATA_API_BASE}/WPI/3.THRPEB.7.TOT.20.AUS.Q?format=csv"
ABS_WPI_SERIES: dict[str, dict[str, str]] = {
    "abs_wage_price_index": {
        "MEASURE": "3",
        "INDEX": "THRPEB",
        "SECTOR": "7",
        "INDUSTRY": "TOT",
        "TSEST": "20",
        "REGION": "AUS",
        "FREQ": "Q",
    },
}

# ABS Data API dataflow JV (Job Vacancies). Codes verified against
# JV v1.0.0: MEASURE=M1 (Job Vacancies, '000), SECTOR=7 (Private and
# Public), INDUSTRY=TOT, TSEST=20 (SA), REGION=AUS, FREQ=Q.
# URL key pins all 6 dimensions (MEASURE.SECTOR.INDUSTRY.TSEST.REGION.FREQ)
# so the server returns only this series (Gemini PR #126). Drops the
# response from ~2.5 MB to ~10 KB.
ABS_JV_URL = f"{ABS_DATA_API_BASE}/JV/M1.7.TOT.20.AUS.Q?format=csv"
ABS_JV_SERIES: dict[str, dict[str, str]] = {
    "job_vacancies": {
        "MEASURE": "M1",
        "SECTOR": "7",
        "INDUSTRY": "TOT",
        "TSEST": "20",
        "REGION": "AUS",
        "FREQ": "Q",
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


_MONTH_ABBR = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_rba_date(raw: str) -> str | None:
    """Parse an RBA tables date column.

    Most RBA statistical tables use ``DD/MM/YYYY`` for the obs-date
    column. A handful (e.g. F11 exchange rates) instead use
    ``DD-Mon-YYYY`` -- the same format the header-row publication date
    uses. Try both. Returns ISO ``YYYY-MM-DD`` or None.

    Month-abbrev parsing uses a hand-rolled lookup rather than
    ``%b``/``%B`` strptime so non-English ``LC_TIME`` hosts still
    parse the English RBA month names (Codex P2 PR #129).
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
    except ValueError:
        pass
    parts = raw.split("-")
    if len(parts) == 3:
        try:
            day = int(parts[0])
            month = _MONTH_ABBR.get(parts[1].capitalize())
            year = int(parts[2])
        except ValueError:
            return None
        if month is None:
            return None
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


def _parse_publication_date(raw: str) -> str | None:
    """RBA tables publication date is DD-Mon-YYYY (e.g. 22-May-2026).

    Uses the hand-rolled _MONTH_ABBR lookup (not strptime ``%b``) so
    non-English ``LC_TIME`` hosts still parse the English month names —
    same locale-safety lesson as _parse_rba_date (Codex P2 PR #129).
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    parts = raw.split("-")
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        month = _MONTH_ABBR.get(parts[1].capitalize())
        year = int(parts[2])
    except ValueError:
        return None
    if month is None:
        return None
    try:
        return date(year, month, day).isoformat()
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
        parsed = parse_rba_csv(text, columns)
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

    missing_columns = set(columns) - set(parsed)
    for series_id in missing_columns:
        message = f"upstream column missing: {columns[series_id]!r}"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest macro time series into state/local-macro.sqlite")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH, help="Path to the local-macro SQLite store")
    parser.add_argument(
        "--source",
        choices=[
            "rba_h5",
            "rba_h3",
            "rba_g1",
            "rba_g3",
            "rba_h4",
            "rba_h2",
            "rba_f1_1",
            "rba_f11",
            "rba_i2",
            "rba_d1",
            "rba_j1",
            "abs_cpi_m",
            "abs_lf_under",
            "abs_lf_hours",
            "abs_hsi_m",
            "abs_lend_housing",
            "abs_ba_gccsa",
            "abs_wpi",
            "abs_jv",
            "all",
        ],
        default="all",
        help="Which source family to ingest (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    con = open_store(args.store)
    try:
        report: dict[str, object] = {}
        if args.source in ("rba_h5", "all"):
            report["rba_h5"] = ingest_rba_h5(con)
        if args.source in ("rba_h3", "all"):
            report["rba_h3"] = ingest_rba_h3(con)
        if args.source in ("rba_g1", "all"):
            report["rba_g1"] = ingest_rba_g1(con)
        if args.source in ("rba_g3", "all"):
            report["rba_g3"] = ingest_rba_g3(con)
        if args.source in ("rba_h4", "all"):
            report["rba_h4"] = ingest_rba_h4(con)
        if args.source in ("rba_h2", "all"):
            report["rba_h2"] = ingest_rba_h2(con)
        if args.source in ("rba_f1_1", "all"):
            report["rba_f1_1"] = ingest_rba_f1_1(con)
        if args.source in ("rba_f11", "all"):
            report["rba_f11"] = ingest_rba_f11(con)
        if args.source in ("rba_i2", "all"):
            report["rba_i2"] = ingest_rba_i2(con)
        if args.source in ("rba_d1", "all"):
            report["rba_d1"] = ingest_rba_d1(con)
        if args.source in ("rba_j1", "all"):
            report["rba_j1"] = ingest_rba_j1(con)
        if args.source in ("abs_cpi_m", "all"):
            report["abs_cpi_m"] = ingest_abs_cpi_m(con)
        if args.source in ("abs_lf_under", "all"):
            report["abs_lf_under"] = ingest_abs_lf_under(con)
        if args.source in ("abs_lf_hours", "all"):
            report["abs_lf_hours"] = ingest_abs_lf_hours(con)
        if args.source in ("abs_hsi_m", "all"):
            report["abs_hsi_m"] = ingest_abs_hsi_m(con)
        if args.source in ("abs_lend_housing", "all"):
            report["abs_lend_housing"] = ingest_abs_lend_housing(con)
        if args.source in ("abs_ba_gccsa", "all"):
            report["abs_ba_gccsa"] = ingest_abs_ba_gccsa(con)
        if args.source in ("abs_wpi", "all"):
            report["abs_wpi"] = ingest_abs_wpi(con)
        if args.source in ("abs_jv", "all"):
            report["abs_jv"] = ingest_abs_jv(con)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
