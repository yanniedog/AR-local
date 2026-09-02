# AR-local workflow

## Build and review

1. Fetch `origin`; branch from current `origin/main` as `agent/<topic>`.
2. Preserve unrelated changes. Keep one logical change and one writer per path.
3. Run focused checks, `git diff --check`, then `npm test`.
4. Commit, push, and open a PR to the repository default branch.
5. Settle required CI with `npm run wait-for-bots -- --pr <n>`.
6. Disposition every substantive review thread as Implemented, Deferred, or
   Declined with evidence; resolve completed threads.
7. Run `npm run pr:gates:check -- --pr <n>` and use the guarded squash merge
   command only when it passes.

Do not force-push, bypass protection, merge a draft through raw GitHub commands,
or call a PR complete while required checks or review threads remain.

## Runtime closeout

Deployment is separate from merge and requires explicit authority plus a fresh
passing protected backup gate: natural backup, matching restore drill, boot
proof, and exact candidate SHA.

1. Run `npm run pi:deploy:verify`.
2. Deploy the exact main SHA with
   `npm run pi:deploy -- --expected-commit <sha>`. Add
   `--bootstrap-observation` only for the first dashboard-to-status cutover; it
   runs one systemd-managed canonical ingest before acceptance.
3. Confirm the Pi checkout is clean and equals that SHA.
4. Run `npm run verify:pi`.
5. Confirm `ar-local-status.service`, nginx, ingest timers, listener scope, and
   current ObservationV1/accounting/SQLite v11 evidence.

Never deploy over a dirty Pi checkout or use destructive rollback. A passing
local suite is not runtime proof.
