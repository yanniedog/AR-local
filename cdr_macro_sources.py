"""Verified official macro source selectors; stable IDs and explicit dimensions."""

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

# RBA F1.1 money-market monthly averages. The source's Frequency row
# and FIRMM series identifiers distinguish it from the daily table.
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

# ABS complete monthly CPI uses the CPI dataflow and stable dimension IDs.
# MEASURE=3 is annual percentage change. Headline is INDEX=10001/TSEST=10;
# trimmed mean is INDEX=999902/TSEST=20. The old CPI_M flow ceased in Sep2025.
# See the captured official source fixtures and their provenance README.
ABS_DATA_API_BASE = "https://data.api.abs.gov.au/rest/data"
# CPI_M ceased in September 2025. CPI is the complete monthly replacement;
# retain consumer IDs, but do not join the retired indicator's history to it.
ABS_CPI_M_URL = f"{ABS_DATA_API_BASE}/CPI/3.10001+999902.10+20.50.M?format=csv"
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
        "INDEX": "999902",
        "TSEST": "20",
        "REGION": "50",
        "FREQ": "M",
    },
}

# ABS Data API dataflow LF_UNDER (Labour Force: underemployment and
# underutilisation). Same dimension layout as LF but with PARM_ITEM
# instead of MEASURE for the measure axis; carries the standard M*
# labour codes (M16 employment-to-pop, M23 underemployment rate,
# M24 underutilisation rate). Codes verified against LF_UNDER v1.0.1.
ABS_LF_UNDER_URL = f"{ABS_DATA_API_BASE}/LF_UNDER/M16+M23+M24.3.1599.20.AUS.M?format=csv"
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
ABS_LF_HOURS_URL = f"{ABS_DATA_API_BASE}/LF_HOURS/M18.3.1599.TOT.20.AUS.M?format=csv"
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
ABS_HSI_M_URL = f"{ABS_DATA_API_BASE}/HSI_M/9.TOT.CUR.20.AUS.M?format=csv"
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
ABS_LEND_HOUSING_URL = (
    f"{ABS_DATA_API_BASE}/LEND_HOUSING/FIN_VAL.NEWCOMMITS.DV8368.TOTDWELL.TOT.TOT.20.AUS.Q?format=csv"
)
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

# Numeric scales are explicit contracts. A changed upstream unit fails only
# the affected series instead of silently publishing values in different units.
for _filters in (
    ABS_CPI_M_SERIES, ABS_LF_UNDER_SERIES, ABS_HSI_M_SERIES, ABS_WPI_SERIES,
):
    for _filter in _filters.values():
        _filter["UNIT_MEASURE"] = "PCT"
for _filters in (ABS_LF_UNDER_SERIES, ABS_HSI_M_SERIES):
    for _filter in _filters.values():
        _filter["UNIT_MULT"] = "0"
ABS_LF_HOURS_SERIES["hours_worked"].update(UNIT_MEASURE="HR", UNIT_MULT="3")
ABS_LEND_HOUSING_SERIES["lending_indicator_housing"].update(UNIT_MEASURE="AUD", UNIT_MULT="6")
ABS_BA_GCCSA_SERIES["building_approvals_abs"].update(UNIT_MEASURE="NUM", UNIT_MULT="0")
ABS_JV_SERIES["job_vacancies"].update(UNIT_MEASURE="NUM", UNIT_MULT="3")

# RBA's series identifiers survive editorial changes to the Title row. Never
# guess another column if a configured identifier disappears or is duplicated.
RBA_SERIES_CODES = {
    "unemployment_rate": "GLFSURSA", "participation_rate": "GLFSPRSA",
    "dwelling_approvals": "GISPSDA", "consumer_sentiment": "GICWMICS",
    "business_conditions": "GICNBC", "trimmed_mean_cpi": "GCPIOCPMTMYP",
    "inflation_expectations": "GCONEXP", "wage_growth": "GWPIYP",
    "household_consumption": "GGDPECCVPSH", "public_demand": "GGDPECCVPD",
    "bank_bill_30d": "FIRMMBAB30", "bank_bill_90d": "FIRMMBAB90",
    "bank_bill_180d": "FIRMMBAB180", "aud_twi": "FXRTWI",
    "commodity_prices": "GRCPAIAD", "housing_credit_growth": "DGFACH12",
    "neutral_rate": "JSVNNIREMED", "capacity_utilisation_proxy": "JSVOGMED",
}

RBA_UNITS = {
    **dict.fromkeys(RBA_SERIES_CODES, "Per cent"),
    "dwelling_approvals": "'000", "consumer_sentiment": "Index",
    "business_conditions": "Percentage points", "household_consumption": "$ million",
    "public_demand": "$ million", "aud_twi": "Index", "commodity_prices": "Index",
}

SOURCE_FAMILIES = {
    "rba_h5": (RBA_H5_URL, RBA_H5_COLUMNS),
    "rba_h3": (RBA_H3_URL, RBA_H3_COLUMNS),
    "rba_g1": (RBA_G1_URL, RBA_G1_COLUMNS),
    "rba_g3": (RBA_G3_URL, RBA_G3_COLUMNS),
    "rba_h4": (RBA_H4_URL, RBA_H4_COLUMNS),
    "rba_h2": (RBA_H2_URL, RBA_H2_COLUMNS),
    "rba_f1_1": (RBA_F1_1_URL, RBA_F1_1_COLUMNS),
    "rba_f11": (RBA_F11_URL, RBA_F11_COLUMNS),
    "rba_i2": (RBA_I2_URL, RBA_I2_COLUMNS),
    "rba_d1": (RBA_D1_URL, RBA_D1_COLUMNS),
    "rba_j1": (RBA_J1_URL, RBA_J1_COLUMNS),
    "abs_cpi_m": (ABS_CPI_M_URL, ABS_CPI_M_SERIES),
    "abs_lf_under": (ABS_LF_UNDER_URL, ABS_LF_UNDER_SERIES),
    "abs_lf_hours": (ABS_LF_HOURS_URL, ABS_LF_HOURS_SERIES),
    "abs_hsi_m": (ABS_HSI_M_URL, ABS_HSI_M_SERIES),
    "abs_lend_housing": (ABS_LEND_HOUSING_URL, ABS_LEND_HOUSING_SERIES),
    "abs_ba_gccsa": (ABS_BA_GCCSA_URL, ABS_BA_GCCSA_SERIES),
    "abs_wpi": (ABS_WPI_URL, ABS_WPI_SERIES),
    "abs_jv": (ABS_JV_URL, ABS_JV_SERIES),
}

LOCAL_SERIES_IDS = frozenset(sid for _, selectors in SOURCE_FAMILIES.values() for sid in selectors)
SOURCE_URLS = {sid: url for url, selectors in SOURCE_FAMILIES.values() for sid in selectors}

# Corrections to the old catalog describe the actual source series. Values in
# SQLite remain source-native, so existing hours history needs no destructive
# migration; readers consistently convert thousands of hours to millions.
SERIES_METADATA = {
    "hours_worked": {"unit": "Million hours"},
    "lending_indicator_housing": {"unit": "$ million", "frequency": "quarterly", "description": "Value of new housing loan commitments excluding refinancing; seasonally adjusted."},
    "bank_bill_90d": {"label": "90-day bank bill yield", "unit": "Per cent", "frequency": "monthly"},
    "bank_bill_180d": {"label": "180-day bank bill yield", "unit": "Per cent", "frequency": "monthly"},
    "neutral_rate": {"frequency": "semiannual"},
    "capacity_utilisation_proxy": {"label": "Output gap (forecaster median)", "frequency": "semiannual"},
    "monthly_cpi_indicator": {"label": "Monthly CPI inflation", "description": "Complete monthly CPI; the partial monthly indicator ceased in September 2025."},
    "monthly_trimmed_mean_cpi": {"label": "Monthly trimmed mean inflation", "description": "Complete monthly CPI trimmed mean; replaces the ceased partial monthly indicator."},
}
SERIES_VISIBLE_FROM = {"monthly_cpi_indicator": "2025-04-01", "monthly_trimmed_mean_cpi": "2025-04-01"}
