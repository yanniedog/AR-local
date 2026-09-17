# Dashboard history transport

The dashboard requests `/api/banks/history/section/series` for product drilldown
and historical-date previews. The legacy `/section` response remains unchanged.
Both use the same selected run inventory, filtering, gap-fill calculation and
coverage metadata. No rows, dates or fields are dropped.

`ar-dashboard-history-dictionary-v1` interns scalar values and row templates.
Each observation names its template, run-date value and optional carry-forward
value. Index `-1` means an absent field; a dictionary entry containing `null`
remains an explicit null. Strings, including exact decimal tokens, remain strings.
The decoder reconstructs independent row objects before existing normalization.

Admission limits are 20 MiB JSON, 1,000,000 observations, 100,000 templates,
300,000 scalar values and 64 template columns. Exceeding a limit fails explicitly;
there is no truncation or fallback to the oversized legacy response. Invalid
references, counts, dates, provenance counts and section bindings are rejected.
Public product/release contracts are unaffected by this local HTTP representation.

`npm run verify:pi` uses `--history-mode=series`, which reads and validates the
complete bounded response for each banking section, with a 90-second whole-request
deadline for each history section and a check for the decoder asset. Routine restart checks retain
the compact aggregate mode. The explicit legacy `raw` mode checks HTTP status
only and does not establish successful parsing or drilldown behavior.
