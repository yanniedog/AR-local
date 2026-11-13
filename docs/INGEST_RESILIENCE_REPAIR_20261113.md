# Daily ingest resilience repair — progressive handoff

Updated: 2026-11-13, Australia/Hobart. **Work in progress; production repair is not yet accepted.**

## Objective and authority

The operator requests maximum obtainable daily CDR coverage for every registered bank and mortgage, savings and term-deposit product; preservation of complete consumer-relevant details and longitudinal changes; daily Pi capture, GitHub publication and verified Google Drive backup. This request authorizes work toward those runtime outcomes and daily backups. Preserve immutable observations, prior recovery copies, resource limits, ownership locks and exact-commit deployment gates. Do not equate public availability with complete coverage. Never label carried-forward observations as fresh or infer product withdrawal from a failed provider capture.

## Resume first

1. Read this document's latest checkpoint, specialist handoffs below, repository AGENTS.md and WORKFLOW.md. Before Pi operations, complete the mandatory runbook and recovery-ledger review. The ledger is approximately 3 MB; this investigation has not yet completed that full review and has not mutated the Pi.
2. Recheck origin/main, open PRs, running work and live ownership. This checkpoint starts from `4e3e394ee192a009946aa9d31b85d9a854c451bb` (PR #1128). Original checkout has unrelated untracked work; leave it intact.
3. Obtain a current per-provider/date failure matrix, publication receipt, archive receipt and deployed commit before selecting a runtime repair. Use already-retained diagnostics first. A missing diagnostic is not proof of data loss.
4. Complete exact-head CI and feedback disposition for each source fix. Deploy the qualified exact commit through the reviewed gate, then verify the live Pi dashboard and `npm run verify:pi`. Publication, Drive object hashes and restore evidence require separate acceptance.

## Verified findings and corrections

| Finding | Evidence | Consequence / action |
|---|---|---|
| Today's capture is partial, not missed | GitHub #1124, category INGEST_PARTIAL, first observed 2026-11-12 14:30 UTC | Determine actual failed providers and stages; do not hide the warning by renaming it success. |
| Today's publication has recovered | GitHub #1126 is CLOSED and PUBLICATION_CURRENT; manifest and dates index both 2026-11-13, updated 2026-11-12 22:43 UTC | Earlier local handoff claims of currently missing publication are stale. This receipt proves neither complete capture nor complete history. |
| Natural publishing and later backfill use different policies | Current source retains natural observation gate; scheduled pi-payload-backfill applies the later 2026-11-07 operator policy `all` to integrity-bound observations | Investigate reusing the reviewed policy in the daily path, preserving membership/integrity and truthful partial labels. Do not blindly loosen thresholds. |
| Local handoff timing and access facts drifted | Authenticated gh access works; no open PRs at initial check; #1127/#1128 merged. Current backfill cron 18:45/08:15 UTC | In AEDT these are 05:45/19:15; actual start can be delayed. Do not shift into the protected window merely to suppress alerts. |
| Older proposed stale carry-forward conflicts with provenance requirements | Existing untracked INGEST_COVERAGE_HANDOFF_20261113.md vs runbook D-003 | Preserve partial observations. Any consumer fallback must explicitly distinguish old data and must not manufacture daily captures or change events. |
| Source fixes are not deployment evidence | Recent successful pi-quality-canary workflow exists, but live state not yet independently read | Verify exact candidate, complete receipt and current service configuration before activation. |

## Work ownership and durable records

- Coordination/documentation: `C:/code/AR-local-ingest-handoff-20261113`, branch `agent/ingest-repair-handoff-20261113`, this file.
- Provider capture/recovery: `C:/code/AR-local-coverage-resilience-20261113`, branch `agent/coverage-resilience-20261113`; `docs/COVERAGE_PROVIDER_HANDOFF_20261113.md`.
- Publication/admission: `C:/code/AR-local-publication-resilience-20261113`, branch `agent/publication-resilience-20261113`; `docs/PUBLICATION_REPAIR_HANDOFF_20261113.md`.
- Runtime investigation: `C:/code/AR-local/.work/ingest-resilience-20261113/runtime-handoff.md` (private/local).
- Earlier untracked `C:/code/AR-local/docs/INGEST_COVERAGE_HANDOFF_20261113.md` is preserved. Its claims and proposed policies require revalidation; it is not current authority by itself.

## Required durable design and acceptance

- Inventory: retain each day's authoritative register and provider identity/endpoint changes; enumerate all pages and relevant categories; account separately for attempted, empty, failed and retired providers.
- Capture: bounded retries and rate limits; Retry-After; negotiated API versions; compatible unknown fields preserved; explicit schema/pagination failures. Do not silently discard partial page results or declare incomplete pages complete.
- Evidence: preserve original product-detail bytes/JSON, timestamps, source URLs, negotiated versions and hashes. Normalize searchable attributes without dropping unknown fields. Linked terms need independent capture/change evidence; CDR does not guarantee every consumer term is supplied.
- History: immutable observations, stable identities, versioned normalized values and raw diffs. Missing capture is unknown, not deletion; only comparable confirmed observations may drive user change alerts. Describe factual changes without inferring deceptive intent.
- Recovery: bounded same-day failed-provider retry on the Pi, operation locks and quiet-window admission; improvements create a new observation/revision, never rewrite accepted history. Reuse already-captured good responses where safe.
- Publication: validate assets and membership, upload dependencies before atomic selectors, verify public readback, keep previous valid release, disclose freshness and per-provider coverage. Monitor capture and publication separately.
- Backup: verify daily archive receipt, file count/bytes/hash and remote object; regularly restore and rehash retained source. An accessible Drive folder or completed process is insufficient. Retain old backup systems until replacement recovery is proven.
- Alerts: actionable provider/stage/error classification and rolling state transitions; recover only the matching condition. Keep historical incidents until their underlying evidence is reconciled. Never bulk-close genuine data-loss incidents to reduce noise.
- Release acceptance: real retained data checks, CI, exact deployed commit, live dashboard smoke, public asset hashes, Drive restore proof, then multiple natural daily cycles. No implementation can guarantee capture of data an upstream provider does not expose; unmet coverage must remain visible and retryable.

## Checkpoint 1 — investigation started

No source fix, Pi deployment, backup, republish or incident closure is claimed at this checkpoint. Parallel investigations are running. Next checkpoint will attach concrete defects, tests and rollout steps.
