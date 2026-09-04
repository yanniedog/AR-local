---
name: ingest-agent
description: Bring up or repair the real CDR ingest and canonical observation pipeline.
---

# Ingest agent

Use when asked to run ingest bring-up or repair ingest/export correctness.

1. Read `AGENTS.md`, `WORKFLOW.md`, and the current ingest units.
2. Work only from real CDR responses and the immutable raw-attempt journal.
3. Reconcile provider/product coverage through ProductAccountingV1.
4. Produce only ObservationV1, ProductAccountingV1, and sidecar-free SQLite v9.
5. Run sanity comparison before finalization; withhold ambiguous or corrupt runs.
6. Finalize only after reloading and verifying all three artifacts.
7. Run focused tests, then `npm test` before shipping.

Do not create current `dashboard-cache`, fabricated rows, compatibility exports,
or payloads from unverified files. Report exact run date, counts, exclusions,
database checks, and verification commands.
