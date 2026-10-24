# Narrow archive readback runtime repair

The October 24 natural capture finalized successfully. Its immutable revision
uploaded, but an immediate GitHub public read returned 404 for `manifest.json`.
The pinned publisher therefore refused promotion, leaving the rolling manifest
and dates index on October 23. PR #968 adds bounded missing-only readback retries;
it never accepts different bytes or retries authentication/transport failures.

## Controlled scope decision

The operator explicitly requested fixing stale selectors and recurring history
delivery on October 24. This bounded installation applies only the reviewed
archive-I/O module to the existing natural daily command, using
`pi_payload_archive_launcher.py`. The pinned producer checkout, capture,
selection, data builders, gates, credentials, queue, timers and observations stay
unchanged. It does not activate unrelated current-main ingest/audit changes.

This is an explicit deviation from the full current-main checkout activation
procedure in `CDR_QUALITY_DEPLOY.md`: no checkout activation occurs. The narrower
acceptance below covers the complete changed call graph. Preserve the earlier
failed whole-producer canaries and paging evidence as failures. They neither
authorize this installation nor become passing evidence through it.

The launcher validates a clean exact predecessor, both original and replacement
module hashes, canonical nonoverlapping package/source paths, and the exact
existing `--banks-only --skip-git-sync` arguments. It preloads only
`app_payload_revisions_github` from the immutable package before running the
original `pi_daily_sync.py` as `__main__`. All its local imports resolve from the
pinned producer. The module's public API is unchanged. The daily publisher imports
this module in-process; placing it in `sys.modules` first covers its revision
archive/readback and alias imports without changing builder or ingest execution.

## Gates and installation

1. Read the controlled recovery runbook, complete handoff and latest private
   takeover. Record plan version/commit/canonical and raw hashes, user authority,
   exact reviewed merged package commit and candidate file hashes.
2. Read back the current daily unit and every drop-in, effective command,
   environment-file references, service account, working directory and timers.
   Preserve exact file preimages and the complete effective command. Refuse any
   unexplained active owner, tracked source drift, changed command or missing
   natural daily timer/dashboard. Keep the Drive write hold and retry state.
3. Stage a new private package, never overwrite an existing package. Include the
   exact merged launcher and archive module plus a hash manifest. Compare the
   archive module against the original: only the bounded PR #968 retry delta is
   admitted. Validate its dependency imports against the original producer.
4. Under the existing shared `ar-local` queue and native production lease, run
   Linux launcher regressions and archive/revision/encryption tests against the
   isolated replacement with the pinned dependencies. Require complete pytest
   output and JUnit. Run the exact staged launcher with `--check-only`, then a
   bounded read-only real-archive probe through its loaded store; independently
   verify the selected manifest and every declared asset by size/hash. No upload,
   ingest, backup or timer action is part of this canary.
5. Require healthy dashboard, idle ingest, unchanged source/pointer/Drive-hold
   hashes, enough resource headroom and a daylight admission with two hours
   before the 22:00 cutoff. Preserve package, unit and data rollback preimages.
6. Install the exact package root-owned and non-writable by the service account
   under a new content-addressed directory. Add one root-owned daily-service
   drop-in replacing only `ExecStart`. Preserve its existing outer queue command
   and all queue arguments verbatim. Replace only the inner Python invocation
   with the same Python executable, `-B`, package launcher, validated source/root
   hashes and package path, followed by `-- --banks-only --skip-git-sync`.
   Never copy secrets into the package or command. Keep all existing unit
   environment files, user, working directory, limits and stop hooks.
7. Run `systemd-analyze verify`, then reload definitions. Do not start, restart or
   enable a service or timer. Read back effective argv and every preserved
   property. Prove `--check-only` with the installed root-owned bytes as the
   actual service account, and repeat the bounded real-archive read-only probe.
8. Independently verify source, pointer, Drive hold and timer state unchanged,
   dashboard HTTP and `verify:pi`. Record exact files, hashes, commands, timestamps
   and results in an immutable operator receipt. Append a private takeover entry.

This installation proves the next scheduled daily invocation is configured to
load the repair; only a separately observed natural run proves that it executed.
No manual source recapture is authorized by this procedure.

## Rollback

Refuse installation if a same-named drop-in/package already exists with different
bytes. On any post-install failure, remove only the newly installed drop-in after
verifying its exact hash, restore any preserved preimage, reload definitions and
verify the original effective command and unchanged timers/source/data. Retain
both packages, every failed receipt and all source observations. Do not restart
the natural daily service to test rollback. A running daily invocation defers
installation/rollback until it has terminated and released its own lease.
