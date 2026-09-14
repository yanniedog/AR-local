# Explicit Google Drive write hold

On 14 September 2026 the operator required the accepted Google Drive backup to
remain the fallback during product evidence and historical coverage repairs.
All backup writes remain held until the operator explicitly approves resuming.
This decision supersedes the daily-upload policy for this task; it does not
relax source immutability, natural ingest, resource or reclaim safeguards.

The root-owned marker `/etc/ar-local/drive-write-hold.json` and the global intent
record `/etc/ar-local/.drive-write-hold-activation.lock` each block the systemd
backup service and every checked-in application dispatch path, including forced runs,
direct backend calls, init, remote readiness and restore (which may acquire
repository locks). A `write-hold.json` in the configured spool is an additional
local hold. Empty, malformed or unreadable markers fail closed. An alternate
spool or `--force` cannot bypass either global marker. No automatic expiry exists.
The intent record alone is `ACTIVATION_PENDING`: new dispatch is refused by
upgraded guards, but complete spool coordination has not been established.
`HELD` from activation requires every inventoried spool lock and the final marker.
An existence-only runtime check never attests that coordination succeeded.

Terminal ingest requests still queue durably. A hold prevents dispatch and
acceptance/acknowledgement; held work is not successful backup evidence. A
worker that observes the hold at its final check retains candidate/resource
records for reconciliation. A check alone cannot revoke an acceptance already
in progress. Declaring the hold active requires coordinated activation below.

## Controlled runtime transition

1. Obtain the sole owner's safe-idle acknowledgement and pause the existing
   agent continuation. Inspect actual services, requests, worker groups and lease.
2. Let any in-flight backup reach a verified terminal state; preserve receipts
   and independent reclaim restoration. Do not kill an unknown upload or clear
   a lock to install a hold.
3. Disable the existing daily and queue write timers, preserving their original
   controls. Before activation, commission and independently verify the complete
   protected guard bundle and every authorized launcher/control path using the
   [installed proof contract](DRIVE_GUARD_INVENTORY.md). Legacy workers that know
   only their spool lock do not honor a global intent record. Their dispatch
   authority must be removed or routed through the verified guarded controller.
   Timer pauses alone do not account for direct or alternate-spool launches.
   Install the reviewed standalone helper through the protected installation
   transaction below; never run root Python from a Pi-owned checkout.
   Invoke its protected copy with `-I -S`, supplying `--spool` for every inventoried
   dispatch spool and an explicit `--reason`. The helper first validates the fixed
   protected proof and exact installed bytes without importing or executing them.
   Missing, malformed, changed, incomplete or over-budget proof refuses before
   creating the global record. Its atomic creation blocks new admission only
   after the global guard has been installed on every authorized path. The helper then
   acquires each `backup.lock` as a symlink to its protected global activation
   record, including the parent's complete acceptance and
   acknowledgement critical section, before atomically creating the marker.
   Every pre-existing lock refuses activation: active, dead-PID, malformed and
   empty locks are all unreconciled. The helper never recovers, renames, clears,
   waits on or signals an existing lock owner. If blocked, retain ownership and
   reconcile the original operation and its receipts. An existing global record
   returns `ACTIVATION_PENDING` with exit 2 and is never recovered or retried into
   `HELD` automatically. Partial or empty record bytes still block dispatch.
   A manually created marker alone is not proof of coordinated activation.
   Install the service-level refusal. Preserve original controls
   and queue identities in the local hold receipt. Leave reclaim reconciliation
   and natural ingest enabled.
4. Activate only the tested scoped component with current bindings. Direct
   historical executables not containing this guard must not remain authorized
   dispatch paths; account for those paths before declaring all-dispatch hold.
5. Verify refusal without invoking a backend upload/check/lock operation. Record
   marker/control hashes, schedule state, preserved queue and latest accepted
   receipt. Verify the hold again after restart and at task closeout.

Removing a marker or re-enabling the schedules requires explicit operator
approval. The code intentionally provides no automatic release command. This
document and passing unit tests do not establish an installed Pi hold.

## Protected installation and invocation

This code does not install the helper, guard bundle, backup service, credentials,
dispatchers or controls. Protected bundle/launcher commissioning and proof
approval are prerequisites to the following scoped helper installation. The
sole operator must record the approved commit and SHA-256 of the exact
`pi_drive_backup_hold_activate.py` bytes before transferring them. The expected
hash must come from that independent reviewed artifact, not from whichever bytes
happen to be present in the mutable Pi checkout at installation time.

Use an already trusted root-owned operator shell and trusted system utilities.
Do not execute a repository Python module, shell installer, `sudo python` command
from the checkout, or a script placed in a Pi-writable staging directory as root.
Treat the source file only as data: copy it to a fresh temporary file inside
`/usr/local/libexec/ar-local-drive-hold`, owned by root and non-writable by others;
verify its bytes against the independently recorded hash; then install that
verified file at `/usr/local/libexec/ar-local-drive-hold/activate.py` with owner
root:root and mode 0555. Verify the installed hash again. On mismatch, stop and
preserve the candidate for investigation; do not execute it.

Both that directory's entire ancestor chain and `/etc/ar-local` must be canonical,
root-owned directories without group/other write permission. Existing installed
helper bytes must be inventoried before replacement; never blindly overwrite an
unknown installation. The activation CLI verifies its fixed installation path,
file ownership/mode/link count, protected ancestors and Python isolation flags.
The installed leaf must be root:root and exactly mode 0555, including no special
permission bits. The `activate_hold()` entrypoint enforces these checks itself,
so importing it does not bypass the trusted-runtime gate.
These runtime checks supplement the installation contract: they cannot make
executing an already malicious script from a mutable checkout safe.

The only supported activation command shape is:

```text
/usr/bin/python3 -I -S /usr/local/libexec/ar-local-drive-hold/activate.py --spool /canonical/inventoried/spool --spool /another/inventoried/spool --reason "Preserve the accepted fallback during product evidence repairs"
```

The helper is standard-library-only. `-I` excludes working-directory, user-site
and Python environment injection; `-S` excludes site initialization. The helper
imports no backup, queue, operation-lock or checkout module. The system Python
and its standard library are part of the trusted host installation.

The protected `.drive-write-hold-activation.lock` is also non-recovering. It records
`ACTIVATION_PENDING`, the requested reason/spool inventory and verified proof
identity before any spool lock is
created. **Every newly created activation record and spool lock remains after
success or failure.** The helper never unlinks a lock pathname, including a
replacement entry; a separate inode check followed by unlink is not atomic in a
service-writable spool directory. Inspect the exact owner, terminal receipts and
marker/control state. Removal requires explicit operator resume approval and
manual reconciliation; this helper provides no release or cleanup command.

Spool locks deliberately use symlinks rather than a new flag in an ordinary PID
record. The previous operation-lock implementation bound by the fixture ignores new flags
but refuses symlinks before examining their target or applying PID, boot or age
recovery. Linux `O_CREAT|O_EXCL` also refuses dangling symlink entries. The target
is the permanent record in the protected system directory; the helper never
removes that target. These links preserve refusal on spools whose links were
created if activation stops before the system marker exists. Untouched spools
depend on the previously installed global guard; symlink compatibility alone
cannot protect them. A directory sentinel is unsafe with old code because stale recovery
can rename it away before unlink fails. New workers additionally refuse legacy
hold-role records, `recovery=manual`, nonregular entries and unreadable, malformed
or partial records. Unknown keys are refused before PID/boot/age recovery.
Only `pid`, `role`, optional `boot_id` and optional `recovery=automatic` form the
recognized ordinary schema. Well-formed ordinary PID/role locks retain stale-owner and
prior-boot recovery; unknown age alone never authorizes removal.

The old-worker compatibility fixture is bound to commit
`4ee90f76b7ddf300e5f963cf20eb15b81af34886`, source file
`ar_local_operation_lock.py`, SHA-256
`9eb985e6a6cec7e86e3b69dc8a1a5447b59af139bb6f710df68010627a6527d4`.
Inventory the actual installed worker versions, global guard, full import closure,
launch environment and controller critical section before activation. This local
work has not verified an installed Pi version. Executables without the verified
global guard and inventoried spool-lock critical section remain
unauthorized dispatch paths, as required by step 4. Passing fixture tests is not
proof of the installed Pi version. Activation is Linux-only; Windows differs for
dangling-link `O_EXCL`, so that native case is exercised by Linux CI and remains
an explicit Pi acceptance check. No Windows activation is supported.

The immutable marker uses a flushed temporary file and atomic no-replace link,
so a competing marker can never be overwritten.

An existing marker returns `ALREADY_HELD`, its hash and its original parsed content
when readable, before attempting any new activation locks. It does not replace
the old reason or spool inventory, and does
not re-attest coordinated activation. Empty or malformed markers still block
Drive dispatch but require separate coordination evidence. A repeat call with a
different inventory cannot silently expand the original receipt. The caller must
inventory every actual dispatch spool before first activation and reconcile any
missing scope explicitly while preserving the hold.

Record the installed helper/hash/ownership, trusted command, complete spool
inventory, marker hash and original content, timer and acceptance refusals, and
unchanged accepted-backup/queue identities. Local tests cover protocol behavior;
root installation, actual Pi lock coordination and reboot refusal remain separate
runtime gates. No installation or activation is implied by this document.

The checked-in service still launches from the configured repository checkout.
Its additional systemd intent-record condition is useful defense, but that launch
is not a protected isolated bundle proof. It remains unqualified for this new
activation contract until separately reviewed protected commissioning. Natural
ingest, durable backup requests and reclaim reconciliation remain enabled.
