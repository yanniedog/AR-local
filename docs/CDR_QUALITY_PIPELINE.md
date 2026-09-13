# CDR quality pipeline

## Authority and operating boundary

The operator approved this pipeline on 2026-09-11 and explicitly authorized
implementation, gated code repairs in AR-local and AR-app, PR merge, exact-tested
deployment, same-day recapture, versioned publication, and daily Drive backups.
This decision supersedes the laptop-as-primary-backup prerequisite in
ARL-OPS-001 D-004 through D-007 for this pipeline. Existing backup and recovery
evidence remains immutable. Historical physical-boot claims are not upgraded by
database backup success. No Windows elevation is needed for this pipeline.

The 01:00 Australia/Hobart natural ingest remains mandatory. Mutating operations
yield to ingest. Same-day recovery keeps the existing 03:30–22:00 window,
resource checks, operation lock and immutable-observation safeguards. A later
calendar day's source is never relabelled as an earlier day. Unknown/malformed
source evidence remains a disclosed gap; missing data is never manufactured.

## Daily owner

A Codex heartbeat at 04:00 Australia/Hobart owns review and repair across both
repositories. It runs using the configured subscription/model and requires the
desktop computer and Codex app to remain running. It starts by reading this
policy, the latest chronological recovery handoff, repository instructions, and
durable audit/repair state. Older handoff entries remain reference evidence;
they do not reinstate superseded laptop activation requirements.

The daily workflow audits the current full dataset against all retained history,
repairs reproducible defects, runs required repository checks, closes substantive
review findings, merges through the repository wrapper, canary-tests the exact
candidate, and verifies the deployed Pi and public payload. Pending GitHub work
retains ownership with a conditional same-day follow-up. Unchanged healthy runs
remain quiet; meaningful improvements, failures and required action are reported.

Capture, finalization, publication, consumer verification, and backup each have
their own result. PASS means the corresponding evidence actually exists.

During activation, each transaction retains live readiness and verifier output
under `activation-<id>/smoke/`, separately for pre-switch, post-switch and rollback
checks. Timestamped phase receipts bind those logs by hash; the final activation
receipt links each phase and includes the failed-check reason. A failed rollback
does not erase the original activation failure. All three phases use the sealed
candidate's verifier, whose hash is recorded, including when checking old code.
Every endpoint and success condition remains required. Activation allows 90
seconds for headers from each of the three cold history/section requests, with
a 300-second whole-verifier timeout and the existing 120-second readiness bound.
Ordinary `verify_local.py` calls retain their 30-second request default.

Activation requires at least 30 minutes before sealed expiry before changing
coordination timers and again immediately before checkout: 21 minutes for all
three smoke paths plus a 9-minute margin for other work. This admission margin
is not a hard whole-operation deadline for existing inline source hashing.
Rollback remains available after expiry. The 22:00 activation/capture cutoff and
the natural-ingest quiet window remain unchanged.

## Payload revisions

The additive v1 revision protocol retains every archived generation and points
each date at one selected verified revision. The immutable tag is
`app-payload-YYYY-MM-DD-rNNNNNN`. `dates-index.json` keeps its legacy fields and
adds `revision_protocol: 1` and `revision_heads`, keyed by date. Each head binds
`revision`, `generation_id`, `manifest_url`, `manifest_sha256`, and
`bundle_sha256`. Manifests add `payload_revision` containing `schema_version: 1`,
the revision/generation/bundle identities, and nullable `parent_revision`.

Archive and download verification precede pointer promotion. Legacy aliases are
compatibility projections. Revision archives are never subject to rolling asset
pruning. App support is shipped and verified before producer activation.
Details-only and optional-asset-only changes are revisions too. The app keeps
its previous installed verified bundle during an interrupted update and never
mixes generation assets or fetches archived same-day alternatives.

## Google Drive

The Pi owns a Restic repository accessed through rclone, with compression and
encryption. A dedicated Drive folder is created by the authorized rclone
identity using `drive.file` scope. The first snapshot contains all retained CDR
recovery data; later snapshots upload new chunks and metadata. All history is
retained. No automatic forget/prune or old-observation deletion is authorized.

The independent Pi timer is 03:30 Australia/Hobart daily; terminal observation
and repair events queue additional backups. A consistent inventory and mutable
SQLite/control snapshots are captured before transfer. Network transfer never
holds the production operation lock. Missing OAuth or recovery password is
BLOCKED, not backup success. The recovery password must also be retained off
the Pi. Retire the old laptop schedule only after initial Drive backup/restore
PASS. See GOOGLE_DRIVE_BACKUP.md for the implementation and restore commands.

## Acceptance

The optional v2 standard-cohort product history reapplies explicit savings
winner restrictions from each day's retained product detail. Stable exported
rate fields and any retained array index must agree before a rate is excluded;
price alone is insufficient. Direct tier `additionalInfo` and nested condition
information retain their rate-local scope. Original observations and raw prices
are unchanged. The projection records date/product and source-detail/rate hashes,
reclassified-row counts and held product-days. A known restricted product's day
with unavailable or ambiguous evidence remains a null gap; no zero, cross-gap
move or present-day restriction is substituted for that day's missing evidence.
Existing all-products history and the app's dated-core history are separate
contracts; this standard-cohort sidecar does not change their ranking policy.
Retained calculation frequency must agree, including an explicitly blank field;
older rows without that column still require an unambiguous match. Identical
semantic product/detail copies from different source paths are equivalent
evidence. Valid restricted product detail is registered even when that day's
flattened rates are absent, so another unverifiable day cannot evade the gap policy.

Use retained real responses and generated artifacts for regression fixtures.
Require source-to-SQLite-to-payload reconciliation, revision preservation and
interruption tests, full producer Python tests, AR-app mobile CI and headless
data audit, exact deployed commit, live Pi browser inspection and `verify:pi`.
Require initial/incremental Drive restore with hashes, SQLite integrity and
foreign-key checks. Natural scheduled execution is separate from commissioning.

The originally supplied AR-app audit URL returned a missing-file response during
planning. It is an outstanding input, not claimed reviewed evidence. Current
live and historical producer/app audit evidence remains independently usable.

## Commands and evidence

Run the shipping app audit from AR-app `mobile` with
`node scripts/audit-public-payload.cjs --output <report.json>`. Retain both output
files and transfer the JSON to the Pi's audit evidence area. Then run
`python cdr_quality_audit.py --data-root <data-root> --app-audit <report.json>`.
The command reads every retained observation and operational log. Its derived
SQLite index and create-once JSON reports live under `state/quality-audit`.
`--audit-root <isolated-directory>` keeps all derived writes outside production
data during commissioning. `--no-public` is only a source diagnostic; its result
cannot satisfy publication or consumer acceptance.

Every daily run rechecks the complete source/log inventory and ledger metadata,
and fully hashes and audits current/new/changed observations. Previously verified
immutable observations use cached full results with their verification timestamp;
`--scrub` rehashes all history and is mandatory on Sundays. Cache contents are
rebuildable; historical databases are never migrated or edited. Retained SQLite
WAL/rollback journals are applied only to verified private copies. Reports retain
all provider/product membership changes and failure recurrence; product absence
is not automatically treated as data loss or retirement.

After a code repair is tested, reviewed, merged, canaried and deployed, use
`python pi_cdr_quality_repair.py --expected-commit <deployed-sha>
--expected-generation <selected-generation> --reason <repaired-issue>` on the Pi.
The repair reserves a capture in the existing durable recovery budget, checks
the actual date and expected state again under the production lock, captures
fresh responses and preserves the old generation. `--dry-run` verifies readiness
without reserving or capturing. A successful child process alone is not payload
or coverage acceptance: rerun the producer/public/app audits and check the
independent backup receipt.

Same-day selection distinguishes missing products from explicit source category
exclusions. An exclusion requires the exact product in a fresh, complete,
contract-bound index from the same registered provider and an existing
out-of-scope CDR category. Selection receipts retain each product's category,
index body/event hashes, prior rate-row count and complete count reconciliation.
When verified withdrawals occur alongside scope exclusions, only identities
present before and absent afterward contribute withdrawn-row allowances. The
receipt records both disjoint allowances and the remaining rate delta; duplicate
claims or retained stale products cannot excuse another product's lost rows.
Scope proof uses the latest coherent index crawl, retaining earlier trailing
pages as evidence without borrowing them. An attempted detail classification
must be usable, bound to the same-day request and product, and consistent with
the existing classifier; failed or conflicting probes prevent exclusion.
Absent or in-scope products, unverified evidence, and unexplained rate loss still
refuse selection. After an approved selection-policy repair, the existing
watchdog reconsiders retained finalized generations before any network probe or
capture. It preserves the original refusal receipt and reserves publication of
the newly accepted pointer; publication/readback acceptance remains separate.

Exit codes for the producer audit are 0 PASS, 1 WARN, 2 FAIL and 3 BLOCKED. The
repair command returns 0 READY/CAPTURED, 2 FAIL/NOT_SELECTED and 3 BLOCKED.
Historical known gaps require an explicit disposition; do not erase the evidence
or change its original status to make a current report green.

V2 insight publication has its own immutable history. Before a mutable v1
selector is replaced or its assets are pruned, the publisher preserves any
existing v2 manifest, every declared insight asset, the exact matching v1 base
manifest, and its core/details assets. The standalone v2 publisher performs the
same predecessor check and archives the incoming bundle before selector
promotion. Archives use `app-payload-v2-<date>-<full-manifest-sha256>` and are never
pruned. Original manifest bytes are unchanged; `preservation.json` records their
hashes and the archived asset URLs. Every archive file is independently read
back, including on retries. Missing, malformed, mismatched or conflicting
evidence prevents replacement.

`manifest-v2.json` remains the latest selector and keeps its existing schema.
An insight-only change gets a distinct v2 archive without requiring a different
v1 numbered revision. Both immutable generations survive a failed selector
upload; rollback restores only a missing selector and preserves its exact bytes.
Eligible v2 publication that fails or does not confirm success leaves the whole
publication outcome failed for the existing retry workflow, while the successful
v1 bundle remains available. Publication success includes exact selector and
asset readback; capture and deployment acceptance remain separate.

On Windows, process liveness must use native process handles, never signal zero.
Run process-control tests in the operator's hidden isolated runner and require a
complete pytest summary and JUnit file. A truncated run, even with exit zero,
does not pass verification.
