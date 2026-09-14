# Bounded dashboard history coverage

The banking history endpoints retain the existing limit of 90 database files.
`All` selects the entire loaded timeline, not all retained history. Neither
file presence nor a successful read establishes complete product history.

Both raw and compact responses now carry `history_coverage` schema version 1:

| Counter | Meaning |
| --- | --- |
| `available_run_file_count` | Eligible existing regular database files at inventory time, at or before the requested date. |
| `selected_run_file_count` | Latest eligible files selected under the unchanged 90-file limit. |
| `omitted_run_file_count`, `truncated` | Eligible files excluded by that limit. |
| `missing_run_file_count` | Dated candidate directories (or the fixed root) without a regular database file. Missing calendar directories cannot be inferred. |
| `inventory_error_count` | Filesystem inventory errors; zero does not establish historical completeness. |
| `successful_selected_run_file_count` | Selected files whose section query returned normally, including zero-row results. |
| `empty_selected_run_file_count` | Successful reads returning no rows for the requested section/date bound. |
| `unreadable_selected_run_file_count` | Selected queries failing with SQLite or filesystem errors. Public details omit private paths. |
| `observed_date_count`, `observed_row_count` | Distinct actual row dates and row count from successful queries, before gap filling, cohort, standardness and numeric filters. |
| `returned_observed_*`, `returned_carry_forward_*` | Compact-only date and rate-contribution counts after those existing filters and numeric acceptance. A date can contain both types. |

Filename dates describe inventory, not section observations. A fixed export root
uses one database file, which can contain several observed dates. `partial` marks
known cap, missing-file, inventory or read problems; `historical_completeness`
always remains `not_established`, including when `partial` is false.

Inventory uses filesystem metadata for every eligible candidate and its WAL/SHM
sidecars. Both response caches fingerprint that complete inventory, including
older omitted files. This adds no database body reads and does not expand the
existing selected-file limit. Stat fingerprints are cache invalidators, not
cryptographic or transactional source attestations.

The existing interior-gap carry-forward behavior is unchanged. The compact
points and provider series add `observed_count` and `carry_forward_count` after
the existing numeric kernel accepts a row. Only the existing literal string
`carry_forward == "1"` marks a synthetic contribution. The shared Python
aggregate helpers expose these fields only when explicitly requested; default
payload shape and arithmetic remain unchanged.

The UI says **loaded**, discloses omitted/unreadable/empty/missing files, and shows
observed contributions separately from carried-forward estimates for the visible
dates and focused provider. Raw drilldown counts use its existing filtered cohort.
Legacy payloads explicitly report unavailable coverage/provenance; a current-only
bootstrap snapshot does not claim history has loaded. No UI path certifies full
historical or legal/product-terms coverage from these counts.

Verification uses disposable inventory markers and protocol-only numeric controls,
plus existing retained-fixture regressions. It is not business-data acceptance or
proof of Pi deployment. No live history expansion, source mutation, new gap fill,
backup write, or runtime/timer change is part of this change.
