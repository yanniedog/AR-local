# Integrated ingest repair continuation — 2026-11-13

Root authorized consolidating source PRs #1131, #1132, #1134, #1135 and #1136
into one exact-head tested PR, preserving component commits and feedback
dispositions. Originals remain open until the integrated PR merges, then close
with supersession links. Documentation PR #1129 merges last, after controlled
runtime qualification; no source merge alone establishes Pi acceptance.

Base: `865a854`. Local branch: `agent/ingest-integration-20261113`.
Integrated component heads:

| PR | Head | Behavior |
|---|---|---|
| #1131 | `3309a9e` | Publish intact usable partial observations; preserve dated retry failures; disclose uncertainty; keep recovery eligible |
| #1132 | `c0c0bcb` | Truthful current-schema failure accounting and HTTP-200 CDR-error detection |
| #1134 | `d9d88cb` | Include non-bank lenders; detect incomplete register responses; install new validation dependency in trusted restore bundle |
| #1135 | `f22f435` | Evidence-backed prospective CDR cessation and safe public disclosure; no product-withdrawal inference |
| #1136 | `5705193` | Prefer known suppression causes; workbook reason map as JSON; verify captured empty-index regression |

Conflicts in `app_payload_observation_gate.py` and `app_payload_build.py` were
resolved by retaining BOTH public projections: partial population uncertainty
and confirmed CDR participation cessation. Neither projection exposes nested
transport/history provenance. All original integrity, source selection and
zero-usable-data guards remain.

Integration regression `f3d765c` exercises both public disclosures together using
the captured 306-provider financial register. Review repair `ccbc823` accepts
retained interim registry IDs and revokes cessation when that identity reappears
under either identity field. The report's Counter serialization allegation was
declined: Counter is a dictionary subclass, and actual CLI/isolated-stdin tests
already execute that path successfully. Both substantive threads were resolved.

Restore qualification `c5dbbb1` is integrated. Its standalone local verifier binds
an already downloaded daily raw archive to an exact retained upload receipt and
generation, validates bounded archive extraction, and checks SQLite committed
state on separate copies while preserving all originals. It does not download,
write Drive, change production, or establish real-generation acceptance through
fixture tests. See `DAILY_RAW_RESTORE_QUALIFICATION.md` for invocation and limits.

Component validation: #1131 synchronized controls 120 passed; #1135 synchronized
controls 144 passed; #1136 108 passed plus independent 15-test review. #1134 full
CI exposed a real missing trusted-bundle module, repaired in `d9d88cb`; 73
restore/register tests then passed. These are not a substitute for integrated
exact-head hosted CI. Preserve untracked JUnit and isolated-run evidence.

Integrated local checks: 486 component tests passed (one existing workbook style
warning); 55 combined public-projection checks passed; 209 lifecycle, report and
restore checks passed after the interim-ID review repair. The latter includes
all new restore tests and existing restore/archive compatibility controls. Root
independently passed all 31 new restore checks. These receipts do not establish
live capture or production restore success.

Next: integrated regression checks, review/merge optional qualification-route
branches when ready, full exact-head CI, substantive feedback disposition and
guarded squash closeout. Root owns any Pi action. The explicitly extended
maintenance authority expires at 00:30 November 14 Hobart; SMTP is deferred by
the user. No Pi mutation has occurred from this source integration worktree.
