# Shared Pi task queue

The queue runs on demand inside each submitted task. It has no daemon, cron job,
timer or periodic worker. Installing its AR-local service overrides does not
start or enable ingest: the existing timer and operator commands retain control.

## Rules

- Three CPU slots are available; one of the Pi's four cores remains outside this
  queue for the dashboard, SSH and bounded background checks.
- Jobs using different resources can run concurrently. Shared reads can overlap;
  an exclusive resource claim excludes other jobs using that resource. `host`
  is exclusive against every queued task, including shared reads.
- Waiting conflicts are FIFO. A ready AR-local request waiting at least 7,200
  seconds takes priority at the next safe slot, including reserving the CPU
  capacity it needs. Its age uses the same boot's monotonic clock.
- From 00:30 until 02:00 Australia/Hobart, only the verified daily ingest and
  daily watchdog units can enter, even before natural ingest registers.
  Other jobs, including manual AR-local work, whose maximum execution time
  plus a 60-second stop allowance would reach the next 00:30 boundary also wait.
  Running jobs are not cancelled
  merely because another request becomes higher priority.
- Other projects get one CPU slot and at most 30 minutes of execution per job.
  AR-local can request up to three slots and six hours. Split longer maintenance
  into resumable jobs. Every job also has a finite waiting deadline.
- Existing transaction locks remain mandatory. Host-wide work also acquires
  AR-local's production lease and checks for unregistered active AR operations.
  An occupied native lease returns the task to waiting without resetting its age.

This is cooperative coordination among projects using the same Pi account.
Direct SSH commands that bypass the queue do not acquire its resource claims.
All deployment and maintenance operators should use the entry point below and
declare every resource they can mutate. Use `host` for shared network changes,
package upgrades, reboots and other host-wide operations. Keep routine project
deployments scoped to that project's data and service unless they also affect
shared host resources. Do not run queued commands as root or detach them.

## Submit work

From a normal Pi user shell in the project directory:

```sh
pi-shared-task --project crypto-mining --resource crypto-mining \
  --max-runtime 1200 -- /path/to/reviewed-deploy-command

pi-shared-task --project ar-local --resource ar-local --cpu-slots 3 \
  --max-runtime 21600 -- /path/to/reviewed-ar-command

pi-shared-task --project simjury --resource host \
  --max-runtime 600 -- /path/to/reviewed-host-command

python3 /usr/local/lib/shared-pi-queue/pi_shared_queue.py status
```

`--dry-run` validates a submission and reports budgets without executing a
command or creating queue state. Actual submissions create a temporary systemd
service, run as the submitting user, and return the command's exit status.
Host claims acquire the native production lease themselves; their commands must
not reacquire that same lease. Ordinary AR producer commands retain their own
native lock and should declare `ar-local` without `host`.
Only audited noninteractive operations should be submitted. Use separate
operator-authorized tools for privileged maintenance; the queue does not grant
privileges or turn writable request metadata into root commands.

Execution budgets start at admission. A job retaining escaped descendants at
its deadline receives whole-cgroup termination and returns failure, even
if its original child already exited successfully. The wrapper returns 124 when
it survives deadline teardown. A stubborn descendant requiring whole-unit
SIGKILL also kills the wrapper; callers receive the actual nonzero systemd
failure status instead. The pre-escalation log identifies the timeout, and
claims remain held until whole-unit termination is proven. Priority never interrupts
an active transaction; deadlines bound how long another project can occupy it.

The launcher sets CPU and I/O priorities, whole-process-tree termination, finite
runtime and memory cgroup ceilings. This Pi currently boots with its memory
controller disabled, so those memory ceilings are not enforced. Admission also
requires at least 1 GiB available RAM. This pressure guard is not a hard RSS
limit. Do not apply small address-space limits to Go or Node jobs with large
virtual reservations. Memory-controller activation requires a separately
planned reboot; queue installation does not reboot the host.

## Recovery and installation

Queue state is atomic, bounded JSON in `/var/lib/shared-pi-queue`, owned by the
Pi operator with mode 0700. A short kernel lock serializes registration,
reconciliation and admission. Records bind a boot, exact systemd invocation,
wrapper PID/start ticks and cgroup before starting a child. The slot stays held
while descendants survive. Host claims mark the native AR lease as requiring
explicit recovery, so a dead wrapper cannot expose surviving children to a
legacy worker's PID-based reclamation. Queue reconciliation clears only its own
matching native hold after proving whole-cgroup termination.
Fixed AR-local services keep their claims through systemd post-start and
post-stop hooks, including gaps between hooks. A new invocation can retire its
own predecessor only after the new wrapper is verified as its cgroup's sole
member, before it starts a command. Surviving or ambiguous ownership still blocks.
Expiration alone never frees a running slot. A
temporary observation error defers admission and can recover when evidence
returns; ambiguous ownership blocks admission. Do not delete state to bypass
that protection. Inspect the recorded unit and its complete cgroup first.

Install the exact tested `pi_shared_queue.py`, `pi_shared_queue_store.py`,
`pi_shared_queue_policy.py`, `pi_shared_queue_native.py`, `pi_shared_queue_post_hooks.py` and `pi_shared_task.py` under root-owned
`/usr/local/lib/shared-pi-queue/`. The `pi-shared-task` entry point executes the
installed launcher. Create the user-owned 0700 state directory. Preserve old
files and service overrides before replacement.

After preserving existing files, install the checked-in executable entry point:

```sh
sudo install -m 0755 deploy/pi/pi-shared-task /usr/local/bin/pi-shared-task
```

The launcher requires systemd's `--expand-environment=no` support (verified on
this Pi's systemd 257), preserving `$VAR` and shell expressions exactly as
submitted. The queue is currently commissioned for the fixed Pi producer and
data roots; host claims reject unsupported root overrides rather than locking
an unrelated data directory.

Render `deploy/pi/shared-queue-daily.conf`, `shared-queue-watchdog.conf` and
`shared-queue-ingest-now.conf` as `98-shared-queue.conf` in their respective
AR-local service drop-in directories. First read back each installed unit's
`WorkingDirectory` and original producer command, and verify the repository root
matches both. Use `python3 scripts/render-shared-pi-units.py --repo-root <verified-root>
--template <template> --output <staged-file>` for each override. Never install an
unrendered template or assume the default checkout: unresolved placeholders
deliberately cannot launch an old `/srv` executable. Non-default data roots remain
unsupported by the native bridge and must not activate these wrappers.
Preserve the stable producer executable
and existing environment files. Reload definitions and read back the effective
command, CPU quota, timeout and kill policy. Do not start, enable or restart a
timer. The daily-watchdog timer intentionally remains inactive.

Also install `pi_shared_queue_stop_hook.py` with those modules. The overrides
replace unconditional dashboard restoration with this guarded hook. It requires
the exact invocation's persisted proof that its command started, retains the
queue claim, and acquires an idle native lease before restoring the dashboard.
The watchdog preserves its 00:30–03:30 Hobart restoration deferral. Fixed ingest
services have a finite 900-second stop budget: the supported maximum of 64
privileged environment-file reads can consume 640 seconds, before service
inspection and dashboard restoration. Their claims remain held throughout.
Transient operator jobs retain a 45-second stop grace. Before execution, the
wrapper sends MainPID readiness for `Type=notify` and verifies PID 1 activation
and its runtime deadline. A separate startup timer bounds waiting; unused
queue-wait allowance never extends execution. Failure to signal or verify
readiness prevents command spawn.
Daily and manual service startup budgets reserve another hour after the
six-hour queue wait and six-hour command limits for inherited restart and smoke
checks (40 curl retries, ordinary endpoint probes and three history deadlines).
The service still bounds the entire startup; hook runtime retains its queue claim.
The runtime-health override installs the reviewed standalone health script while
using the stable producer's dependencies and existing environment. Its Tailscale
recovery holds queue admission closed while checking all occupied claims and
acquiring the native production lease. Any running job or uncertain ownership
defers the restart, including non-AR jobs without a `host` resource.
Install `deploy/pi/shared-queue-health.conf` as the health service's
`98-shared-queue.conf`; reload definitions without starting or enabling its timer.
An invocation cancelled before execution cannot restart an incumbent's paused
dashboard. An interrupted launch without persisted start proof defers recovery
to the existing bounded health check once the native owner has ended.

Before activating these wrappers, run the queue's Linux process tests and
supervised harmless canaries: compatible jobs overlap; conflicting jobs execute
in order; a dead wrapper with a live child retains its slot; a live native AR
lease defers host work. Verify SSH and the Pi dashboard throughout. Source CI,
merge, installed hashes and natural-cycle acceptance are separate evidence.

## Exact AR-local rollout invocations (safe-head)

Use these shapes only in **daylight** after post-ingest preflight. Substitute
reviewed SHAs and paths. Do **not** treat this section as activation authority.
Host claims must not nest a second production lease inside the command.

### Dry-run admission (no mutate)

```sh
pi-shared-task --dry-run --project ar-local --resource host --max-runtime 1800 -- \
  /bin/true

pi-shared-task --dry-run --project ar-local --resource ar-local --cpu-slots 1 \
  --max-runtime 600 -- /bin/true
```

### Gate-bytes-only foundation (production HEAD unchanged)

Requires an aligned disposable source tree `$SRC` with
`HEAD == origin/main == <approved-40-char-sha>`, plus installer support for
`--gate-bytes-only` (see `docs/PI_BACKUP_FOUNDATION.md`). Does not create
`backup.env`, mount disks, or enable backup timers.

```sh
pi-shared-task --project ar-local --resource host --max-runtime 1800 -- \
  /bin/bash -lc 'cd /srv/ar-local/AR-local && \
    sh deploy/pi/install-backup-foundation.sh --gate-bytes-only \
      --prod-repo /srv/ar-local/AR-local \
      --expect-prod-head <protected-production-sha> \
      "$SRC" /srv/ar-local/australianrates /srv/ar-local/data \
      <approved-40-char-sha>'
```

### Full backup-foundation install (after authorized mount + backup.env)

```sh
pi-shared-task --project ar-local --resource host --max-runtime 1800 -- \
  /bin/bash -lc 'cd /srv/ar-local/AR-local && \
    sh deploy/pi/install-backup-foundation.sh \
      /srv/ar-local/AR-local /srv/ar-local/australianrates /srv/ar-local/data \
      <approved-40-char-sha>'
```

### Exact-commit deploy (canary-approved only)

Activation remains the protected workflow's
`python pi_deploy_verify.py --deploy --expected-commit <TARGET_SHA>` path.
When submitting that reviewed command through the queue, keep resource
`ar-local` (not a nested second lease) and a max-runtime that leaves 60s before
the next 00:30 Hobart freeze:

```sh
pi-shared-task --project ar-local --resource ar-local --cpu-slots 1 \
  --max-runtime 3600 -- \
  /bin/bash -lc 'cd /srv/ar-local/AR-local && \
    python3 pi_deploy_verify.py --deploy --expected-commit <40-char-target-sha>'
```

Prefer dispatching `.github/workflows/pi-deploy-on-main.yml` with matching
protected `AR_PI_CANARY_*` values over ad-hoc queue deploys. Never use a bare
`git pull` or moving-main checkout as the activation command.
