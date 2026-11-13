# Ingest resilience: operational continuation

Read the latest `INGEST_RESILIENCE_REPAIR_20261113.md`, mandatory runbook and full recovery ledger first. This is an evidence-backed route map, **not a receipt or authorization to bypass gates**. Source reviewed on 2026-11-13; recheck final integrated bytes. Preserve the accepted fallback and original sources. No operation below was executed by this repair session.

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

## Missing live qualification implementation

The dynamic financial register currently contains 306 brands; never hardcode that future count. `pi_canary_shadow_ingest.py` supports only `template` and `canonicalize`, not a supervised ingest runner. Its scalar receipt checks do not prove resource limits, actual provider completeness or isolation. Production `pi_cdr_quality_repair.py` is a post-deployment path and cannot substitute for pre-deployment qualification.

Implement and test a bounded network-enabled shadow launcher using the existing `pi_resource_supervisor.py` and shared queue. Review exact supervisor interfaces first. Bind detached exact source, new isolated `/srv/ar-local/canary/<generation>/` runs/state/spool and local-only archive configuration. Keep production paths read-only, production archive env/Drive credentials inaccessible, all child processes within resource accounting and cleanup, a finite deadline inside the permitted window, and before/after production preservation receipts. Do not merely remove `PrivateNetwork=true` from the retained-data canary.

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

## Missing independent daily raw restore verification

`pi_daily_cdr_day_archive.py` has backup/request modes, **no restore command or CLI generation selector**. Finalization owns generation-specific archive binding. Use `raw-progress.jsonl` to select the exact generation, source fingerprint, immutable remote name, compressed bytes/hash and manifest. Canonical dates may coexist with generation-suffixed objects; a date-only lookup is insufficient.

Implement a dedicated safe verifier for this archive format, reusing reviewed extraction patterns from `pi_plain_backup_restore.py` where compatible. The latter requires its own accepted plaintext catalog/packs and is not a decoder for daily raw archives. Read the actual raw manifest/transport implementation before designing validation.

Required independent acceptance: download the exact approved remote object to new private scratch using copy semantics; verify retained receipt size/SHA; validate embedded manifest; reject traversal, absolute paths, duplicate members, links and device entries; reconcile file count, bytes and hashes; validate copied SQLite databases/journals in isolated committed views. Never open originals beside their captured WAL or checkpoint source evidence. Bound decompression, disk and runtime resources; leave failed evidence intact. Produce a generation-bound receipt with actual checks, not a promoted upload PASS. Do not enable obsolete Restic services or delete old recovery copies.

Nov7–13 selected raw archives already have compressed upload/readback PASS receipts. Full retained-generation inventory, independent extraction/semantic restore, system recovery and physical boot remain separate proof categories. Email remains explicitly deferred by the operator. Detailed private command/evidence inventory: `C:/code/AR-local/.work/ingest-resilience-20261113/runtime-handoff.md`.
