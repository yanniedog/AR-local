These are small CSV excerpts captured from official sources on 7 September 2026.
Header rows and the last two observations per selected series are preserved.
The current CPI excerpt also includes August/September 2025, which overlap the
retired definition, to verify that revised values never overwrite its archive.
Tests alter copies only to inject transport/schema failures; they do not invent
business observations or replace live acceptance.

- `rba_h5.csv`: https://www.rba.gov.au/statistics/tables/csv/h5-data.csv
- `abs_lf_hours.csv`: https://data.api.abs.gov.au/rest/data/LF_HOURS/M18.3.1599.TOT.20.AUS.M?format=csv
- `abs_cpi_current.csv`: https://data.api.abs.gov.au/rest/data/CPI/3.10001+999902..50.M?format=csv
- `abs_cpi_retired.csv`: https://data.api.abs.gov.au/rest/data/CPI_M/3.10001+999905.10.50.M?format=csv

The hours response identifies `UNIT_MEASURE=HR` and `UNIT_MULT=3` (thousands of
hours). The current CPI response identifies headline original (`10001`, `10`)
and trimmed mean seasonally adjusted (`999902`, `20`), both in percent. ABS
ceased the old partial CPI indicator in September 2025:
https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/monthly-consumer-price-index-indicator/sep-2025
