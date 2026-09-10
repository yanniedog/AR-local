# September 10 recovery-clock activation

The original 09:14 v5 backup restored all three components, then reported a
genuine aggregate `FAIL` because the recovery monitor changed only `checked_at`.
That failure and its full packet remain in `private-tools-activation-20260910`.

PR669 adds a semantic control identity that retains every recovery fact except
that observation timestamp. It still archives and verifies the original raw
file, and verifies the normalized facts against the restored file. Its Linux
CI caught the test module exceeding 1,000 lines. PR670 split that regression;
both complete Linux and Windows product CI passed. The actual merged candidate
is `b6c5a4d8984ad2d2509514418c753cd555b0144f`.

The rejected v6/D024 transaction stopped before task mutation because a failed
receipt cannot be the ancestry anchor for a new receiver. Its original and
corrected pre-action decisions, exact inputs and failure are retained here.

D025 then used the existing v5 control API, without replacing functions or
relaxing checks. Fresh original preflight required observation, macro and
inventory current with only control stale. The new control archive passed its
restore checks, and the unchanged scheduled check reported `PASS` at 09:55:33.
Its native successful receipt is the exact D026 predecessor. The outer intent,
script hash, component receipt and original output are preserved under `D025`.

D026 installed the exact v7 receiver at 09:57:19 without elevation, preserving
the task principal, triggers and settings. The hidden probe passed at 09:58:05.
The user-authorized manual task was requested at 09:58:51 and began at 09:58:56.
`running-task.json` is a dated running snapshot, not terminal success. The active
logs remain outside the repository until completion. Natural-trigger and
physical-recovery acceptance remain open.

The `publication` directory corrects the scope of the earlier v2 manifest-only
check. Both advertised v2 assets were downloaded and verified at 09:48:32:
compressed size/hash, gzip decoding, uncompressed size, JSON, schema-appropriate
date, and v1 base identities. Product history supplies `run_date` and `core_sha`;
economic outlook supplies `generated_at`, matching the manifest and September
10 in Hobart. The original attempt assumed a `run_date` field on both payloads;
that verifier assumption failed, and was corrected before reporting PASS.
No device state, app refresh, producer publication or ingest replay is claimed.

These dated scripts and inputs are evidence, not instructions to replay them.
Use a fresh intent and current identities for any later covered action.
