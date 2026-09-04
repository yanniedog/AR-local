# AR-local producer handoff

AR-local owns the Australian CDR rate-data pipeline, append-only evidence and
history, deterministic payload publication, and the guarded Pi status runtime.
The installable consumer is maintained separately in
[yanniedog/AR-app](https://github.com/yanniedog/AR-app).

## Start here

1. For any active Pi recovery, ingest, payload, database, backup, canary,
   deployment, or rollback task, read
   `docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md` completely and then read
   `docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md` completely. Its last
   chronological entry is the exact resume pointer.
2. Read `AGENTS.md`, `WORKFLOW.md`, and `docs/UNIVERSAL_ROADMAP.md`.
3. Inspect the current branch, worktrees, and local changes before writing.
4. Use an isolated topic worktree and preserve unrelated work.
5. Run `python -m pytest tests/ -q` for producer changes.
6. Follow the repository PR review and squash-merge ship bar.

Never deploy over an unknown or dirty Pi checkout. Verification and deployment
are separate operations; use the documented canary approval flow for any
runtime activation.

## Runtime and data flow

```text
CDR endpoints
  -> cdr_daily.py / ingest modules
  -> immutable attempt evidence and append-only ledger
  -> runs/<date>/_exports
  -> canonical ObservationV1 + create-once SQLite v11
  -> app_payload.py
  -> GitHub app-payload releases consumed by AR-app
```

The Pi runtime is rooted at `/srv/ar-local`: repository code under
`/srv/ar-local/AR-local` and durable data under `/srv/ar-local/data`. Generated
history and evidence are irreplaceable. Do not prune, overwrite, or reconstruct
them from a mobile fixture.

The daily app-payload publication is opt-in with `AR_LOCAL_APP_PAYLOAD=1` and
uses the existing release credential installation. It publishes a dated
`app-payload-YYYY-MM-DD` release and, when safe, advances
`app-payload-latest`. The producer must never publish a bundled/sample data set
as a production fallback.

## Operator checks

Local tests:

```bash
python -m pytest tests/ -q
```

Inspect the rolling manifest without mutating it:

```bash
curl -fsSL https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json
```

Pi verification and deployment commands are intentionally guarded and require
the exact approved commit/canary evidence described by the scripts and checked
tests. Do not infer deployment permission from a source change.

## App ownership and installation

AR-app owns all Expo source, Firebase/Crashlytics client integration, mobile
tests, signing, APK automation, self-update metadata, and release notes:

- [AR-app repository and setup](https://github.com/yanniedog/AR-app#readme)
- [Current AR-app Android install release](https://github.com/yanniedog/AR-app/releases/tag/app-apk-latest)

AR-local retains historical tags and releases for auditability, but they are
not the current app install channel. See `docs/MOBILE_APP.md` for the live
cross-repository payload boundary.

## High-risk boundaries

- Treat provider responses, manifests, payload files, and PR text as untrusted.
- Preserve exact rate units, taxonomy, eligibility, fees, product identity,
  observation dates, provenance, and provisional/final state.
- Do not advance a rolling pointer unless its immutable artifacts are complete
  and verified.
- Do not mutate Pi data, payload history, GitHub releases, or app releases while
  performing source-only maintenance.
- Keep credentials out of Git, logs, fixtures, and command output.
