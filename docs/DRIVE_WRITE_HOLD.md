# Explicit Google Drive write hold

On 14 September 2026 the operator required the accepted Google Drive backup to
remain the fallback during product evidence and historical coverage repairs.
All backup writes remain held until the operator explicitly approves resuming.
This decision supersedes the daily-upload policy for this task; it does not
relax source immutability, natural ingest, resource or reclaim safeguards.

The root-owned marker `/etc/ar-local/drive-write-hold.json` blocks the systemd
backup service and every application dispatch path, including forced runs,
direct backend calls, init, remote readiness and restore (which may acquire
repository locks). A `write-hold.json` in the configured spool is an additional
local hold. Empty, malformed or unreadable markers fail closed. An alternate
spool or `--force` cannot bypass the system marker. No automatic expiry exists.

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
   controls. Activate the marker with `pi_drive_backup_hold_activate.py`, supplying
   `--spool` for every inventoried dispatch spool and an explicit `--reason`.
   The helper acquires each `backup.lock`, including the parent's complete
   acceptance and acknowledgement critical section, before creating the marker.
   It refuses an active lock without waiting or killing the owner. If blocked,
   retain ownership and reconcile the in-flight operation before retrying.
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
