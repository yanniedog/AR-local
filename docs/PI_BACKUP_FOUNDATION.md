# Pi backup foundation operator notes

This component implements Phase A of [ARL-OPS-001](PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md). Read that controlled runbook completely before using any command here. The runbook and its stop conditions remain authoritative.

## Safety boundary

The backup destination must be a physically separate filesystem mounted exactly at `/mnt/ar-local-backup`. The code rejects an unmounted directory, a bind-back to production storage, a separate partition or logical volume backed by the same physical disk, an unexpected device or filesystem, a symlinked destination, incorrect ownership or mode, low free space, and failed write/read/rename verification. There is no `--allow-unmounted` or force bypass.

Do not infer the correct device from `/dev/sdX` names. Establish and record its stable UUID and prove that it is the intended backup device before writing a filesystem, mount configuration, or data. The current unassigned Pi disks are not authorized backup targets.

## Configuration and installation

1. Copy `deploy/pi/backup.env.example` to `/etc/ar-local/backup.env` only after the mount identity has been established.
2. Replace the source with the verified stable device identity. Keep the controlled plan commit and SHA-256 unchanged unless a new runbook version is formally issued.
3. Create `/mnt/ar-local-backup/ar-local` as the ingest service user and group with mode `0700`.
4. Make the configuration readable by the service user; recommended mode is `0640`, owned by `root:<service-group>`.
5. Run the read/write preflight before installing timers:

   ```sh
   python3 pi_backup_foundation.py preflight --config /etc/ar-local/backup.env
   ```

6. Install the disabled-until-configured services only after preflight passes:

   ```sh
   sh deploy/pi/install-backup-foundation.sh
   ```

The installer verifies that configured UID/GID values match the actual ingest service account, performs the same preflight, then installs a root-owned trusted gate plus a SHA-256 manifest before enabling the 04:00 daily backup and 08:00 daily restore-drill timers. Each latest snapshot therefore receives restore evidence before normal daylight deployment. Candidate commits invoke that installed gate and cannot substitute their own gate implementation. Persistent catch-up is blocked from 00:30 through 03:30 and whenever an ingest service is active. The installer must not be called on the production Pi until the physical target has been approved.

## Evidence and acceptance

Snapshots are staged under a create-once `.partial-*` directory, hashed, flushed to storage, then atomically renamed with the parent directory flushed before success. The manifest is written last and copied to immutable manifest evidence. Backup and restore receipts are append-only; mutable `latest-*.json` files are pointers, not evidence. Snapshot payloads are never deleted automatically: `AR_BACKUP_RETENTION_COUNT` is a hard ceiling, and reaching it blocks further snapshots until an append-only decision separately authorizes archival or removal. The snapshot includes the entire production data root, Git bundles for both code repositories, installed AR-local systemd units and drop-ins, timer enablement links as metadata, relevant nginx and storage configuration, and metadata for the actual secret locations (including `notify.env`) without reading or copying secret contents. The mutable macro SQLite database is copied through SQLite's online backup API and checked semantically.

A restore drill first requires source-sized free-space headroom, copies the snapshot to a unique scratch directory, and checks every recorded hash, every SQLite database, required daily and macro schemas, export contracts, ledger reachability, and observation pointer/marker confinement. The unique scratch copy is removed before a passing receipt is written; cleanup failure makes the drill fail. A deployment is blocked unless all of the following are independently current and bound to the exact identities:

- a backup receipt for the current production SHA;
- a passing restore receipt for that same snapshot and manifest hash;
- a physical boot proof for the proposed candidate SHA;
- the controlled plan identity and checksum;
- the exact expected mount, filesystem, ownership, mode, capacity, and write/read probe.

Every preflight and deployment gate recomputes the raw and controlled runbook hashes and resolves the document-containing commit from Git. The configured plan identity is therefore checked against the actual controlled document rather than accepted merely because it has the right shape. The deployment gate also re-hashes every snapshot artifact, not only the snapshot manifest.

The software can validate a boot-proof record but cannot manufacture one. The clone must actually be booted and its network, dashboard, timers, configured device identity, mountpoint, filesystem, code SHA, and evidence hashes recorded. The referenced evidence files must remain present and hash-identical when the deployment gate runs. Until the external mount, restore drill, and physical boot test pass, Phase A remains `BLOCKED` and production deployment remains prohibited.

After an authorized deployment passes exact-SHA synchronization, service checks, and the dashboard smoke test, `pi_deploy_verify.py` invokes the trusted `record-deployment` command. It copies the accepted boot proof to create-once evidence and writes a create-once acceptance record using immutable backup, restore, and manifest paths. A locked explicit chain head orders records even when they are created in the same second. The record is bound to the protected and candidate SHAs, plan identities, exact parent and remote commands, evidence hashes, verification results, operator, timestamps, deviations, and the prior deployment-record digest. If the acceptance record cannot be durably created, the deploy command restores the exact protected SHA, re-applies its services, and verifies the dashboard; it never leaves an unaccepted candidate running silently.
