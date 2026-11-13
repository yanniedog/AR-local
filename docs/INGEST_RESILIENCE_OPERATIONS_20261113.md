# Ingest resilience: operational continuation

Read the latest `INGEST_RESILIENCE_REPAIR_20261113.md`, mandatory runbook and full recovery ledger first. This is an evidence-backed route map, **not a receipt or authorization to bypass gates**. Source reviewed on 2026-11-13; recheck final integrated bytes. Preserve the accepted fallback and original sources. At 23:22 Hobart the independent Nov13 raw restore has passed; live financial capture, full candidate qualification and deployment remain pending.

## Existing retained-data qualification

The hosted `pi-quality-canary.yml` requires `target_commit` equal the exact current main commit. Set TARGET and PY to independently verified values, not a moving branch or guessed interpreter. Current prepared interpreter was observed at `/srv/ar-local/quality-python-ede584cfef64-20261107/bin/python3`; preflight must verify it remains suitable.

```sh
gh workflow run pi-quality-canary.yml --ref main -f mode=preflight -f target_commit="$TARGET" -f python="$PY"
```

Only after preflight, current ownership/queue, completed natural ingest and the 03:30–22:00 Hobart mutation window permit execution:

```sh
gh workflow run pi-quality-canary.yml --ref main -f mode=canary -f target_commit="$TARGET" -f python="$PY" -f confirm=RUN_GUARDED_CANARY -f pressure_profile=legacy -f dispositions=docs/evidence/cdr-quality-20260912/historical-dispositions.json -f dispositions_sha256=2992159f9e656a37a05c40c14a52a8e9b745c9f9841ccf289ef4a1c7986d46e9
```

This runs producer tests and retained-source/payload reconciliation under existing resource supervision and `PrivateNetwork=true`. It does not capture live providers, publish, restore or deploy. A source, date, generation or bound-control change requires fresh qualification. Preserve failed receipts; do not rerun blindly or waive gates.

## Live qualification route implemented; execution pending

PR #1137 integrates `pi_live_financial_capture.py`, `pi_live_financial_worker.py` and hash-bound `pi_cdr_quality_window.py`. The final reviewed component is `72d0dde08f0f18cfbda1578d2bc007263765780c`: 143 focused/RAM checks passed, independent review cleared the absolute-deadline and drop-behind corrections. Use only the exact merged source after applicable CI. The paragraphs below describe the implementation requirements, not remaining missing source.

The launcher supports `plan` followed by `run`, with required `--source`, `--operation`, `--expected-commit`, `--python`, and bounded `--runtime-seconds` (300–5400). A new operation must be immediately below `/srv/ar-local/canary`; its corresponding `/dev/shm/ar-local-canary-<operation-name>` must also be new. Production-equivalent automatic staging keeps raw capture in RAM and derived exports on disk; do **not** force `--ram-stage`, which also stages exports. The worker requires actual RAM-stage provenance, committed register-journal membership, a full audit binding and a matching local-only archive result. Request concurrency is production's 8 providers × 4 detail workers; the existing supervisor retains its 200% CPU ceiling, no-swap and memory/pressure gates.

This session's explicit maintenance extension ends **2026-11-14 00:30 Hobart**. `--window-authorization` plus its SHA256 must bind exact source, canonical operation roots and named stages; the approval never crosses the quiet period. Remaining runtime is recalculated after snapshot hashing, with a cleanup reserve. The original operator-quote receipt is authority provenance, not a qualification result. The installed restricted CI activation helper retains its own normal window. Next normal window starts **03:30 Nov14**. The last full retained-data canary took 86 minutes despite a compatible audit cache: do not start it in a predictably shorter slot.

The dynamic financial register currently contains 306 brands; never hardcode that future count. `pi_canary_shadow_ingest.py` supports only `template` and `canonicalize`, not a supervised ingest runner. Its scalar receipt checks do not prove resource limits, actual provider completeness or isolation. Production `pi_cdr_quality_repair.py` is a post-deployment path and cannot substitute for pre-deployment qualification.

The bounded network-enabled shadow launcher uses the existing `pi_resource_supervisor.py` and shared queue. It binds detached exact source, new isolated `/srv/ar-local/canary/<generation>/` runs/state/spool and local-only archive configuration. Production paths remain read-only, production archive env/Drive credentials inaccessible, and child processes stay within resource accounting and cleanup, with a finite deadline and before/after production preservation receipts. This is a separate route from the retained-data canary's `PrivateNetwork=true` execution.

Real acceptance must reconcile the fresh official financial population and all requested categories against attempted providers, index pages and detail outcomes. Record duration, peak resources, disk growth, payload sizes, raw/normalized identities, failure reasons and selected-generation contracts. Partial upstream responses remain partial. One index probe or an old 115-provider replay cannot satisfy this requirement.

## Existing exact-commit activation

Preferred D027 source activation is documented in `docs/CDR_QUALITY_DEPLOY.md`. Collect fresh raw producer CI/branch-rule/review bindings and current shipping-app acceptance evidence; a summarized PASS or old app receipt is insufficient. With verified candidate C, operation OP, target TARGET and binding paths:

```sh
"$PY" "$C/pi_cdr_quality_activate.py" seal --source "$C" --production /srv/ar-local/AR-local --data-root /srv/ar-local/data --operation "$OP" --expected-commit "$TARGET" --ci-binding "$PRODUCER_BINDING" --app-acceptance "$APP_BINDING"
"$PY" "$C/pi_cdr_quality_activate.py" activate --manifest "$OP/activation.json" --manifest-sha256 "$RETURNED_SEAL_SHA" --dry-run
```

Remove only `--dry-run` after current technical gates pass. Seal expires after six hours or 22:00 Hobart, whichever comes first; activation needs at least 30 minutes remaining. Current observations and publication controls are bound into the seal. This source route does not commission unrelated service bundles. Do not confuse quality `canary.json` with the distinct restricted-deployment `canary-acceptance.json`/approved-plan route or fill repository approval variables with the wrong manifest hash.

After qualified deployment, the existing production recapture dry run is:

```sh
"$PY" /srv/ar-local/AR-local/pi_cdr_quality_repair.py --expected-commit "$TARGET" --expected-generation "$CURRENT_SELECTED_GENERATION" --reason "Integrated ingest resilience repair PRs" --dry-run
```

It checks ownership, source, selected generation, recovery budget, pending publication and window. Only READY plus current gates permits the non-dry execution. CAPTURED is not proof of publication, backup, app acceptance or a natural daily cycle. Inspect the live Pi dashboard and run `npm run verify:pi` against the exact deployment; retain public asset readback and matching archive evidence separately.

## Independent daily raw restore verification: Nov13 PASS

`pi_daily_raw_restore.py` and `pi_daily_raw_restore_sqlite.py` now implement this route (component `c5dbbb1f847a1caeca724c4c53b03f9d75c30523`, integrated in #1137). Read `docs/DAILY_RAW_RESTORE_QUALIFICATION.md` for the exact CLI and bounds. The source document's original pending-runtime statements are superseded by checkpoint 9 of the progressive handoff. The real downloaded Nov13 generation passed: 42,669 files / 3,011,911,860 bytes, committed SQLite integrity and foreign-key checks, and unchanged originals/input hashes. This qualifies one captured, still-partial generation; broader recovery remains separate.

`pi_daily_cdr_day_archive.py` has backup/request modes, **no restore command or CLI generation selector**. Finalization owns generation-specific archive binding. Use `raw-progress.jsonl` to select the exact generation, source fingerprint, immutable remote name, compressed bytes/hash and manifest. Canonical dates may coexist with generation-suffixed objects; a date-only lookup is insufficient.

Use the dedicated verifier for this archive format. `pi_plain_backup_restore.py` requires its own accepted plaintext catalog/packs and is not a decoder for daily raw archives.

Required independent acceptance: download the exact approved remote object to new private scratch using copy semantics; verify retained receipt size/SHA; validate embedded manifest; reject traversal, absolute paths, duplicate members, links and device entries; reconcile file count, bytes and hashes; validate copied SQLite databases/journals in isolated committed views. Never open originals beside their captured WAL or checkpoint source evidence. Bound decompression, disk and runtime resources; leave failed evidence intact. Produce a generation-bound receipt with actual checks, not a promoted upload PASS. Do not enable obsolete Restic services or delete old recovery copies.

Nov7–13 selected raw archives already have compressed upload/readback PASS receipts; Nov13 now additionally has independent extraction/semantic restore PASS. Full retained-generation inventory, other-generation restores, system recovery and physical boot remain separate proof categories. Email remains explicitly deferred by the operator. Detailed private command/evidence inventory: `C:/code/AR-local/.work/ingest-resilience-20261113/runtime-handoff.md`.

## Consumer detail and quiet-change acceptance remains open

Do not equate complete raw capture with a complete consumer comparison interface. Verified source boundaries:

| Layer | Owning source / concrete continuation |
|---|---|
| Original responses | `cdr_raw_attempt_journal.py` and archive promotion retain the lossless backstop. Verify every successful detail's original body/hash and provenance, including unknown/additive fields. |
| Normalized facts/history | `cdr_product_facts.py` traverses generic fields and records source paths/values, structured bundles, typed facts and stable change identities. `cdr_outputs.py` guards uncertain removals. Verify real adjacent observations for fee/limit/condition additions, edits and removals, preserving unknowns and normalization versions. |
| Published details | `app_payload_details.py` publishes curated fees, features, eligibility, constraints, rate conditions and document references. Its optional `facts` field comes from `app_payload_feature_facts.py`, which deliberately emits conservative **feature facts only**, not the complete generic fact store. Unknown source fields and full structured bundles are therefore not automatically published/searchable merely because raw capture retained them. |
| Change alerts | Reviewed v1/v2 builders do not serialize stored `bank_product_changes` events. Define and test a versioned, bounded evidence/changes transport and its consumer contract; do not simply expose old unqualified removal events. Audit optional activity consumers before connecting watchlists. |
| Linked terms | `cdr_terms` discovery already walks nested references; `contracts/product_terms/document-graph-v1.md` defines bounded captured-document graphs and explicit applicability. Link discovery is not proof that bytes were acquired, interpreted or applicable to a given product/cohort. Confirm deployed collection state, retained versions, scope and comparison evidence. |

Next consumer work should preserve a generic evidence view for unfamiliar fields while keeping typed comparisons conservative. Carry source identity, observation time, raw value and mapping status; avoid guessing eligibility from narrative text. Test payload budgets/chunking and actual AR-app rendering/search/watchlist behavior on retained real products across mortgages, savings and term deposits. Distinguish a factual source change from suspected deceptive intent. No end-to-end consumer/watchlist acceptance was performed in this session.
