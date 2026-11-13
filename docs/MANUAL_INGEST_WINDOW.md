# Legacy manual ingest admission

The legacy `cdr-ingest` command starts `ar-local-ingest-now.service`. Its generic
shared queue reserves 00:30–02:00 Hobart; that alone previously allowed an idle
manual job at 02:30. The ordinary `--force` child did not invoke recovery's 03:30
guard. The dedicated manual guard now checks before service startup, before
runtime data work, and again after queue/ingest-lock waiting.

Both manual unit definitions pass `--manual-ingest`. The child also recognizes
the exact service component in its own Linux cgroup, so an older installed argv
cannot silently omit the new guard once the source is deployed. Unreadable or
malformed Linux service context fails closed. Natural 01:00 ingest and separately
claimed 03:00 repair keep their existing admission paths; global queue hours are
unchanged.

The long manual route must fit its existing maximum lifetime before 00:30:
21600s execution + 3600s inherited hook allowance + 900s stop grace = 26100s
(7h15min). These bounds come from `shared-queue-ingest-now.conf` and the fixed-unit
limits in `pi_shared_queue_store.Supervisor.current`; they also cover the direct
template's shorter 6h15min startup plus 45s stop. The six-hour queue wait is not
charged again when the child begins; admission is rechecked then. With the current
bounds, 03:30 and 17:14:59 are eligible; 17:15 and later are refused. Shorter controlled
maintenance/recapture routes retain their own budgets until the daily 00:30 cutoff.

The direct unit invokes a root-owned standalone `pi_manual_ingest_restore.py`
with isolated Python (`-I -S`), never privileged repository imports. Its 35-second
overall deadline fits the 45-second stop timeout. It recognizes only its own
current `ControlPID`, invocation, `deactivating/stop-post` state and sole surviving
cgroup process. It holds a nonblocking queue mutex and native production lease;
other/unknown owners defer restoration. Only this invocation's exact same-boot
dead producer lease can be reclaimed, preserving the stale bytes. It rechecks
quiet hours and reserves the full 35-second start/cleanup budget. The dashboard
start subprocess itself has a 10-second timeout. The helper never
changes schedules, enables services, grants sudo permissions or clears queue jobs.

The queued profile keeps its existing claim-aware installed stop hook. Manual
cleanup now observes the watchdog's 00:30–03:30 gate, including a child rejected
after the queue set `command_started=true`. Natural daily failure cleanup keeps
its existing policy. Both manual profiles require the exact `--manual-ingest`
argv; direct cleanup also requires the exact privileged isolated helper command.
The service snapshot checks root-protected installed hook bytes against reviewed
source hashes. Missing/old/unprotected bytes fail the fence.

## Controlled installation and rollback

Source activation alone does not rewrite either unit or the installed queue
bundle. Keep manual starts held until all applicable steps below are verified.
Use the ordinary approved immutable-source, quiet-window, sole-operator and
shared queue/native lease gates; do not hold an outer AR claim while starting a
second queued manual job. No timers are created or rescheduled by this repair.

1. Record the approved commit and source SHA256s for the helper, queue stop hook,
   manual base unit and rendered manual queue override. Retain exact installed
   bytes, owners/modes, symlink/absence evidence and effective native unit argv
   in the private rollback bundle. Verify the manual unit and all other
   producers/claim owners are idle before changing definitions.
2. Install the direct helper using the reviewed definitions-only installer:
   `sudo sh "$SOURCE/deploy/pi/install-manual-ingest-restore.sh" "$SOURCE" "$RESTORE_SHA256"`.
   The supplied digest must come from the independently approved source manifest.
   Both ordinary Pi unit installers call this before writing the new base unit.
   Those broad installers also affect other services; for an already commissioned
   Pi use the same reviewed render/install steps for the manual base unit only.
3. If the shared queue is commissioned, preserve its existing integration and
   update only the reviewed `pi_shared_queue_stop_hook.py` at its existing
   `/usr/local/lib/shared-pi-queue/` destination using a root-owned temporary
   regular file, source/destination hash comparison and atomic rename. Leave the
   other installed queue module bytes unchanged and record the six-module hash
   inventory before/after. Render `shared-queue-ingest-now.conf` with the existing
   `scripts/render-shared-pi-units.py` and verified repository root, then replace
   the existing manual override at the same recorded path. This is a queue hook
   update, not queue installation or CI-bundle commissioning. If an installed
   protected runtime profile pins queue hashes, stop and use that profile's
   approved update procedure; never ignore the mismatch.
4. Recheck idleness, reload systemd definitions, and collect fresh native
   `ExecStartEx`, `ExecStopPostEx`, deadlines, user and cgroup fences. Run the
   reviewed service snapshot verification, including protected helper/hash
   readback. Ensure the effective queued argv contains the new flag and uses
   the updated queue stop hook. A correct base file hidden by an old override is
   not acceptance. A direct hook is accepted only with the root-protected helper
   and exact data-root argument. Verify quiet rejection without starting ingest;
   actual manual capture remains a separately owned operation.
5. On failure, keep manual starts held, restore the preserved exact unit/override
   and hook bytes (or recorded absence) under the same idle/ownership gates,
   reload and read back the old effective definition. Retain the new standalone
   helper dormant if removing it would add ambiguity; nothing schedules it.
   Restoring an old unguarded stop hook does not restore the new window policy:
   the legacy manual command must remain unused until the repair is qualified.

Source/CI proof is not runtime installation. Unit/helper deployment and acceptance
must follow the exact-source runbook. Existing installed hooks remain unchanged
until their reviewed update. Do not use the legacy command while that
runtime qualification is pending; preserve the current qualified candidate and
sole Pi operation owner.
