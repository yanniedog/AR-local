# Historical audit export integrity

Historical audit summaries now bind `dates.csv` and `bank-product-dates.csv` by SHA-256 and exact byte length. The product report verifies both tables before deriving historical bank totals or writing historical report files. It parses and copies the same verified byte snapshot, so a later source-file change cannot replace the data already verified.

Older audit summaries without export bindings are refused. Do not attach hashes to unverified old tables. Run a new audit into a separate directory using the original selected index and its pinned dated assets. `--cached-cores` reuses both core and available detail files and verifies them against each original manifest; missing cached details still use the bounded public release transport. Original audit directories and publications remain unchanged.

Both commands require a nonempty, sorted, unique list of real ISO calendar dates. The per-date auditor validates manifest, core and detail shapes before counting records, and records malformed structures as failed dates instead of aborting unrelated dates. Byte/shape verification does not establish complete product or contractual coverage.

The task's retained 123-date audit was reconstructed after this change. All 369 manifest/core/detail assets matched the prior pinned evidence, all dates passed, and the 319,013-row product table was byte-identical to both the original audited table and the delivered report. A separate implementation recomputed all 111 historical bank totals from that table. Private receipts remain outside Git; these measured results do not replace tests for future sources.
