# Plaintext backup host control (source preparation)

This is source, not an installation or backup acceptance. It creates no timer,
starts no scheduled task and changes no Pi parameter by itself. Preserve the
existing encrypted fallback and global Restic hold. The packet explicitly grants
only the new manual plaintext archive scope. A completed new backup is not a
prerequisite for making that backup; the canary/deployment still requires verified
offsite raw and filesystem-image recovery copies.

## Boundary and fixed installation mapping

A root-created one-shot `ar-local-plain-backup-<32hex>.service` runs the shared
queue as `pi`. The queue MainPID directly spawns the root-owned trusted parent,
which imports only protected standard-library control code and calls fixed sudo
verbs. It never imports producer code while privilege gain remains possible.
`pi_plain_backup_plan.service_plan` returns the exact service and sudo command
plan, without executing it. PROBE uses runtime120s, CPU100%, IOWeight10, TasksMax64
and stop45s. RUN_ARCHIVE has the existing six-hour ceiling. Queue waiting and
execution timers remain separate; admission retains the natural-ingest window.
The producer also enforces its stricter 00:25-03:30 Hobart cleanup margin.

Install reviewed bytes only after independent review, under root-protected
ancestors (no symlinks or group/other write):

| Checked-in source | Fixed installed control path |
| --- | --- |
| pi_plain_backup_entry.py | /usr/local/lib/ar-local-plain-backup/broker.py |
| pi_plain_backup_parent.py | /usr/local/lib/ar-local-plain-backup/parent.py |
| pi_plain_backup_reconcile.py | /usr/local/lib/ar-local-plain-backup/reconcile.py |
| pi_plain_backup_core.py | same control directory and basename |
| pi_plain_backup_linux.py | same control directory and basename |
| pi_plain_drive_resources.py | same control directory and basename |
| pi_shared_queue_post_hooks.py | control directory AND installed queue directory |
| pi_plain_backup_probe.py | control directory/source/pi_plain_backup_probe.py |
| pi_plain_backup_reclaim_wrapper.py | existing Drive reclaim entry path, below |

The protected `root-control-manifest.json` contains exactly the seven installed
control basenames (broker.py, parent.py, reconcile.py, the core, Linux adapter,
resource monitor and post-hooks module), each mapped to its SHA256. Root imports
only that verified control closure. Producer Git blobs, the unprivileged probe,
and qualified zstandard package/dist-info files are installed separately under
`source/`, root-owned and read-only, with a per-file root packet closure and its
canonical-JSON SHA256. Those producer/dependency modules are imported only after
dropping to Pi UID/GID with NNP and all capabilities empty. No root pip install or
production-venv modification is involved.

## Per-operation bindings and directories

`/var/lib/ar-local-plain-backup-control/<nonce>` is root-owned0700. Its packet
contains schema `ar-local-plain-backup-packet-v1`, mode PROBE or RUN_ARCHIVE, nonce,
exact unit, `manual_plaintext_drive_write: true`, created/expires UTC timestamps,
actual Pi UID/GID, fixed data root and original credential source path, pinned
remote and Drive root-folder ID, closure mapping, and reviewed hashes named:
queue_closure_sha256, source_closure_sha256, parent_sha256, resources_sha256, broker_sha256,
bwrap_sha256, setpriv_sha256, credential_sha256, global_hold_sha256,
reconcile_wrapper_sha256, reconcile_original_sha256, reconcile_callback_sha256.
The queue_closure maps exactly queue/store/policy/native/post_hooks installed Python
module basenames to their reviewed hashes; admission verifies each protected
installed module and its canonical aggregate hash. There are no generic executable, shell, root-user or arbitrary-worker arguments.
PROBE authority expires within120s. RUN_ARCHIVE expires within six hours and
names a distinct successful coupled_probe_nonce with the same source/control and
runtime hashes. All root packets/receipts must come from actual retained proof.

`/var/lib/ar-local-plain-backup-handoff/<nonce>` is root-owned0750 with Pi group.
Its approval.json (root:pi0640) uses schema
`ar-local-plain-backup-authority-v1`, repeats operation scope, expiry, source and
control bindings, and hashes the actual native queue argv with canonical compact
JSON as queue_argv_sha256. worker.json is a root-protected object with schema
`ar-local-plain-backup-worker-v1` and nonce. credentials-copy.conf is an actual
copy, root:pi0440, one link, bounded64KiB, matching credential_sha256. Preserve
the original credential. Never print configuration bytes, tokens or provider
responses. The exact copy is atomically quarantined root-private only after all
untrusted worker PIDs are gone. No recursive removal occurs.

`/var/lib/ar-local-plain-backup-work/<nonce>` has a protected root-owned parent.
Its initially empty sandbox directory is Pi-owned0700. Only that directory is
bound writable inside the producer sandbox. The archive operation is its NEW
`archive` child; TMPDIR/TEMP/TMP point to the existing sandbox parent.

## Confinement and authoritative resources

The fixed root broker holds the actual admitted queue/native lease and monitors
outside the worker namespaces. It durably journals PREPARED before60-to0, then
ACTIVE. Admission requires native unit commands, real MainPID/start ticks,
invocation/boot/cgroup, actual manual native lease and inherited parent FD3,
qualified source/runtime bytes, the unchanged legacy hold, and active existing
reconciliation. It refuses an incumbent reclaim owner or an unowned parameter.

The root-created bwrap uses private PID, IPC and mount namespaces, private proc
and dev, and a read-only root/source tree. It keeps host user/cgroup/network
namespaces: UID/GID and filesystem metadata remain faithful, and Drive transport
can use the network. It hides run, home, root, original credentials and private
control state. Alternate host proc aliases cause refusal. A readable host proc
view is never bound inside: its process-root magic links would bypass the source
read-only mount. setpriv drops UID/GID to Pi, supplementary groups and every
capability, then sets NNP before Python imports producer code.

Only a root-owned0400, read-only, unlinked fully sealed memfd is inherited as
FD3. It binds the exact v1 attestation agreed with pi_plain_backup_attestation:
queue/native inode and owner, boot, source dev/inode, source closure, destination,
worker UID/GID, UTC/monotonic expiry and monitor namespace identities. Worker
requires host user namespace, different PID/mount namespaces, actual same cgroup,
NNP1/all caps0, read-only source and exact native ownership bytes. No host native
FD, journal FD, host proc or DBus socket enters the sandbox.

Host swap-out must stay zero across the entire owned interval, including final
60 restoration observations; cold swap-in is bounded16MiB at actual page size.
Available memory requires3328MiB at admission and2560MiB during work; PSI avg10
must remain below10. Workload swap is zero, aggregate sampled RSS early-stops at
640MiB, sample gap above2s fails, CPU is one core, and the expiry is authoritative.
Do not add RLIMIT_AS to Go/rclone: its virtual mappings are not resident memory.
Root monitor never imports producer modules. A fixed Linux parent-death signal
closes the fork/exec gap, then bwrap handles monitor death. PIDfd-based cleanup
rechecks live cgroup and start ticks before signaling. Ambiguous PIDs/ownership
never authorize cleanup or parameter changes.

Normal finish proves only the known wrapper/trusted parent/sudo/callback PIDs
remain, durably journals RESTORING, restores owned0 to60, verifies readback and
records RESTORED before parent returns. Independent privileged ExecStopPost uses
the same fixed recover verb after systemd has killed the whole worker cgroup.
Current values other than owned0/expected60 are preserved. On a new boot it only
closes an already reset60; an unexplained new zero remains blocked.

The separate plain-backup stop predicate does not add these units to ingest's
FIXED_AR_UNITS or dashboard stop-hook behavior. Only after busy/readiness gates
pass, the native bridge atomically replaces its own exact manual record with a
same-byte successor inode, under the deployed recovery lock. The original
production-lock descriptor therefore leaves the successor through stop-post.
Normal release and Store.reconcile retain the host claim until root completion,
whole-cgroup termination and exact native-file cleanup are all proven. Unknown
or missing completion is retained, never erased.

## Existing reconciliation integration; no reload or new schedule

The actual existing loaded ExecStart is:
`/usr/bin/python3 -I -B /usr/local/lib/ar-local-drive-reclaim/pi_drive_reclaim.py reconcile`.
It already runs as root with NNP, from the enabled existing30-second timer.
Do not infer loaded behavior from NeedDaemonReload alone or perform a blind
manager reload. Preserve the original entry byte-for-byte as
`pi_drive_reclaim.original.py`, prove no active legacy lease/journal, then the
reviewed dispatcher can atomically replace the SAME loaded path. Its protected
`reconcile-wrapper-manifest.json` binds wrapper, preserved original, new callback
and root-control manifest bytes. The broker checks that closure plus actual
loaded native ExecStartEx and existing root/NNP/timer properties.

Original acquire/finish behavior remains delegated to verified original source;
this plaintext flow never invokes legacy acquire. For reconcile, the original
runs as a bounded40-second child using fixed internal reconcile-original scope,
and the new callback runs even if the original fails. Both components report
failure after their bounded attempt, within the existing90-second service budget.
The callback visits both plaintext and canary root journals, skips live units,
uses a finite35-second pass and fixed recover commands, and never starts/stops
services or changes schedules. An installation does not itself prove real orphan
or boot recovery. Retain actual boot-default/configuration evidence separately.

## Commissioning before archive capture

A root-protected sandbox-probe.json normalizes actual generic kernel proof:
current boot, runtime hashes, private PID/mount, host UID mapping, source read-only,
no host-proc alias, NNP/all-caps dropped and verified sealed context. That permits
only bounded PROBE without a previous coupled receipt. PROBE executes the exact
new retained queue/native route,60-to0, root supervision, unprivileged attestation
and staged dependency imports, fixed finish60, credential quarantine and root
stop-post. It performs no freeze, compression, image capture, Rclone or Drive call.
Successful root completion and full resource acceptance produce coupled-probe.json
with PROBE_PASS and scope NO_BACKUP_NO_DRIVE_WRITES, never backup PASS.

Use a new nonce for RUN_ARCHIVE only after that actual coupled proof qualifies
its exact closure. Archive producer acceptance, offsite full restore acceptance,
filesystem image acceptance, deployment and public payload acceptance remain
separate claims. This source has only mocked/Windows-focused validation so far;
Linux CI and actual coupled commissioning remain mandatory before archive use.

## Protected installation and packet preparation

`pi_plain_backup_install.py` is the separately reviewed stdlib-only initial
installer. Its fixed runtime path is
`/var/lib/ar-local-plain-backup-install-tools/install.py`; the complete uncompressed
bundle is copied as root-owned0400 `bundle.tar` beside it. Independently verify
the installer SHA before executing it as root. The reviewed bundle manifest SHA
and entire archive SHA are explicit arguments, not paths or generic commands:

```
/usr/bin/python3 -I -B /var/lib/ar-local-plain-backup-install-tools/install.py prepare <bundleSHA> <archiveSHA>
/usr/bin/python3 -I -B /var/lib/ar-local-plain-backup-install-tools/install.py apply <bundleSHA>
```

Run both inside the existing manual host/ar-local queue with Userpi, CPU100%,
IOWeight10, TasksMax64, control-group kill and a finite runtime at most ten minutes.
The installer checks the live sole admitted claim, exact queue MainPID/invocation,
boot/start ticks, native manual lease and direct queued sudo ancestry. It preserves
all expected original queue bytes and the original reclaim entry root-private,
requires inactive legacy backup/reclaim and no current journal, and refuses any
unexpected incumbent hash. It never imports mutable production/source Python as
root. New queue post_hooks is published before its importers; root controls,
producer/runtime closure and manifests are complete before atomic dispatcher
publication. A partial installation is retained and requires review, not a blind
retry. Existing schedules, timer state, manager reload and service activation are
never changed. Resource observations cover bounded preparation/copy with the
same whole-unit640MiB early stop, zero swap-out, zero workload swap,2.5GiB floor
and3328MiB admission reserve. Swappiness stays60 during installation.

The installation plan additionally stages `plan.py` and `build-packet.py` beside
the seven broker controls; the packet builder validates their installed hashes
against root-private installation.json before importing either reviewed control.
The existing original credential is Pi-owned0600 under root0700 custody. The
builder checks its canonical path, protected ancestors, UID/GID/mode/link/size,
stable read-only descriptor and unchanged leaf identity, preserves it exactly,
and creates only the separate root:pi0440 operation copy.

```
/usr/bin/python3 -I -B /usr/local/lib/ar-local-plain-backup/build-packet.py PROBE <fresh32hex>
```

This writes only private packet/workspace and public read-only handoff files. It
normalizes actual current-boot kernel evidence as KERNEL_ONLY, checks installed
producer/runtime/control hashes and prepares the fixed service plan. It does not
create/start a unit. PROBE authority expires within120 seconds, so prepare it only
when the operator is ready to launch that exact reviewed one-shot service. After
actual coupled/root-resource/stop-post proof, an explicitly authorized separate
`RUN_ARCHIVE <fresh32hex> <successfulProbe32hex>` packet may be prepared. Neither
packet creation nor installer success is backup acceptance.
