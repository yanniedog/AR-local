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

Independent review of `ccbc823` and `f3d765c` found no actionable introduced
defects; 39 lifecycle/public-disclosure tests independently passed. The interim
identity guard remains conservative across interim and registered ID fields.

## Supervised qualification route

Runtime source `a98efe2`, resource correction `3df2f7c` and staging repair
`7c123a3` add
`pi_live_financial_capture.py` and its worker. It
requires exact clean current main, a new operation directory directly under
`/srv/ar-local/canary`, the shared AR-local queue claim and a supervised owned
systemd unit. Source and production mounts are read-only; writes stay in the
operation and RAM stage. Private rclone configuration points only to a local
archive destination. Production concurrency is retained (8 providers, default
4 detail workers), with three reserved queue CPU slots, the existing 200% CPU
ceiling, 3GiB memory cap, existing
quality resource telemetry/stops and a bounded cleanup reserve. The receipt
states the inherited quality-canary swap-recording policy explicitly.

The launcher preserves production's automatic Pi raw-RAM/derived-disk staging;
it does not force `--ram-stage`, which disables that production path. Its RAM
root is isolated. Qualification verifies the actual finalized marker used that
RAM root; a disk fallback remains retained evidence but cannot claim RAM-mode
qualification. Tests compare the parsed command to production's arguments.

The worker independently verifies promoted committed journal evidence, attempts
every discovered financial provider exactly once, audits captured source/ledger/
SQLite accounting and requires the matching local-only raw archive receipt.
Upstream failures remain explicit; a qualification PASS does not mean every
upstream product was available. Production publication, Drive transport and
selection are not invoked. Failed RAM evidence is preserved after owned-unit
cleanup; the original stage is never deleted by this route.

`pi_cdr_quality_window.py` supports a one-off, SHA256-bound authorization JSON:
schema `ar-local-operation-window-v1`, exact `target_commit`, timezone
`Australia/Hobart`, nonempty operator `reason`, aware `issued_at`, `not_before`
and `expires_at`, explicit canonical `operation_roots` and `stages` selected
from `quality-canary`, `quality-seal`, `quality-activate`,
`live-financial-capture`. Duration is at most four hours and expiry cannot cross
the next 00:30 quiet boundary. It changes no unattended schedule or default
window. Canary, seal and activation retain the same hash-bound authorization.

After runtime-owner review, use the exact candidate's Python and script with
`plan`, then `run`, `--source`, `--operation`, `--expected-commit`, `--python`,
bounded `--runtime-seconds`, and both `--window-authorization` and
`--window-authorization-sha256` when an explicit extension applies. `queued` and
`worker` are internal supervised stages. This documentation is not a production
execution receipt or standing permission extension.

Runtime's initial focused controls passed 113 tests. Existing activation fixtures
cannot complete on this Windows interpreter because executable pathname mode
includes execute bits while descriptor mode does not, and the existing strict
identity guard rejects that mismatch. The 34 setup errors remain recorded;
production identity checks were not relaxed. Full integrated Linux CI must pass.

The integrated financial-discovery/lifecycle/disclosure/restore/live-route/
resource/recovery/deployment controls passed 288 tests. The final focused rerun
passed 71 tests, including the corrected CPU property and its ceiling assertion.
After staging repair `7c123a3`, 108 integrated live/resource/actual-RAM-stage and
capacity checks passed. The earlier test invocation used a nonexistent test
filename and collected no tests; its receipt is retained and is not acceptance.

Next: integrated regression checks, review/merge optional qualification-route
branches when ready, full exact-head CI, substantive feedback disposition and
guarded squash closeout. Root owns any Pi action. The explicitly extended
maintenance authority expires at 00:30 November 14 Hobart; SMTP is deferred by
the user. No Pi mutation has occurred from this source integration worktree.
