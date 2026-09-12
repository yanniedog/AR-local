# Pi Google Drive backup

This implements the 11 September 2026 decision in [CDR_QUALITY_PIPELINE.md](CDR_QUALITY_PIPELINE.md): the Pi owns backup delivery, with no laptop or interactive session dependency. Until OAuth enrollment, the first upload, repository checks and the first full restore pass, the outcome is **BLOCKED**, not a commissioned backup.

Restic repository version 2 encrypts and compresses content. The first snapshot covers every retained CDR date and generation. Later snapshots reference existing chunks and upload only new or changed compressed chunks. Each snapshot remains a complete restore point; there is no growing full ZIP uploaded each day. All snapshots are retained indefinitely. No `forget`, `prune`, `delete`, `purge` or `sync` command is exposed by this workflow. Storage still grows with distinct retained data and metadata.

## Scope and consistency

The source includes `runs`, `runs-archive`, `state`, `logs` and `predeploy`, including failed observations, recovery records, immutable revisions, raw responses, manifests and ledgers. Unknown top-level namespaces fail closed for classification. Netdata telemetry, Git, caches, credentials and secret-bearing configuration filenames are excluded and recorded. Explicit non-secret control files document the service and recovery procedures.

The worker acquires the shared ingest lock only for a bounded source freeze. Immutable run files retain their original paths and are checked for changes after upload. Mutable state and logs are copied to a private spool outside the authoritative data root. SQLite databases with retained WAL/journal files are copied privately before SQLite backup merges committed changes. Original main/WAL/journal bytes are also retained under `sqlite-original/` for historical artifact reconstruction. Shared-memory files are disposable and excluded. Nothing opens the production SQLite databases for writes.

The ingest lock is released before network upload, repository checking or restore. Restic is limited to two Go workers, 8 MiB/s network bandwidth and two transfers; the service adds CPU and I/O scheduling limits. Source freezing has a 20-minute limit and stops before the 00:30–03:30 Hobart ingest quiet window. Uploads crossing that window are terminated safely and retried later. A 2 GiB free-space floor protects the private spool; a restore also requires room for its selected data. Interrupted or rejected uploads never advance `latest-verified.json` or acknowledge queued requests.

The Pi kernel checked on 2026-09-12 has no memory cgroup controller or memory
PSI file, so MemoryHigh/MemoryMax/MemorySwapMax are not enforced there. The Drive
controller instead samples the aggregate RSS and swap of **every process in its
isolated, undelegated systemd cgroup**, including detached Restic/rclone children,
at 100 ms intervals. It refuses a sample gap over two seconds, any workload swap,
any new host swap-out, host headroom below 2.5 GiB, or aggregate RSS reaching
640 MiB. That is a 128 MiB early-stop margin below the 768 MiB workload budget;
admission reserves another 768 MiB above the 2.5 GiB host floor. A total of at most
16 MiB cold host swap-in is tolerated over the whole operation, using the host's
actual page size (16 KiB here). Missing/reset/malformed counters fail closed.
PSI is used when present and explicitly reported unavailable otherwise.

This is **sampled containment**, not a hard aggregate allocation limit. Memory
can grow between samples; receipts retain the measured peak, largest sampling
gap and overshoot. RSS double-counts shared pages conservatively. The unit keeps
CPUQuota=100%, IOWeight=10 and TasksMax=64; I/O weight is scheduling priority, not
a hard bandwidth cap. Undelegated read-only control groups, restricted namespaces,
empty capabilities and KillMode=control-group prevent untracked detached work.
Stable pidfds terminate children on failure and cleanup must finish before PASS.
The 20-hour whole-operation deadline and quiet-window guard cover source freeze,
uploads, repository checks, restore and worker cleanup.

Restic and rclone receive GOMAXPROCS=2, GOGC=50 and **GOMEMLIMIT=192MiB per
process**. GOMEMLIMIT is a soft Go runtime target, not the acceptance boundary;
the independent supervisor includes native allocations and all other processes.
There is deliberately no RLIMIT_AS/LimitAS: Go reserves virtual address space
that is much larger than resident memory. See the [Go memory limit guidance](https://go.dev/doc/gc-guide#Memory_limit).

The worker emits only a candidate. Its parent retains the backup operation lock
until the whole worker has exited and descendants are gone, then validates and
hash-binds the candidate, request and resource receipt before updating
`latest-verified.json` or acknowledging exactly the captured queue UUIDs.
The next run, including same-day NO_WORK, revalidates these hashes and bounds.
Old receipts without resource proof remain historical evidence and cannot be
silently accepted. Failed resource attempts remain under `resource-runs/`.
No natural schedule, cloud transfer or restore is proven by a local resource test.

If termination leaves a repository lock, Restic exit 11 is retained as actionable
**BLOCKED** with queue requests and the previous verified pointer preserved.
This interface does not automatically unlock: a matching stale lock cannot be
proven solely from a killed local process if another host may own the repository.
Inspect the retained resource receipt, repository lock owner/hostname/time and
live processes before an operator performs scoped recovery. Never use broad
unlock, `--remove-all`, `--no-lock` or disregard a live lock. The exit-code mapping
is documented by [Restic](https://restic.readthedocs.io/en/v0.18.0/075_scripting.html).

Excluded directories are pruned before traversal and recorded as excluded
namespaces. Content identity includes mode, uid and gid as well as path, bytes
and size, so metadata-only changes produce a fresh manifest/snapshot. Original
metadata is retained in the manifest even when a private SQLite copy has the
service user's ownership; restoring original ownership remains an operator step.

Inventories and collision checks use a private SQLite index with a 2 MiB page
cache. Manifest JSON remains portable and unchanged in shape, but it is written
and read one file record at a time. Hashing, Restic file lists, and restore
verification also stream; memory does not grow with the retained file count.
Empty WALs are preserved as exact sidecars while their immutable main databases
remain direct inputs. They do not force a fresh copy of the full historical
database each day. Nonempty WAL/journal databases still use a private merged
snapshot and preserve original components.

The first full restore reads the whole selected snapshot without creating a
separate include pattern for every file. Weekly sampling uses selected namespace
prefixes. Every selected file/database is verified; receipt examples are capped
at 1,000 with explicit counts/truncation flags and a digest of all SQLite check
records. Complete source identities remain in the snapshot's source manifest.

## One-time enrollment

Install Restic with repository-v2/compression support and rclone on the Pi using the operating system package manager or a verified vendor release. The commissioning target has Restic 0.18.0 and rclone 1.60.1. Use the approved runtime checkout and service user when rendering the units:

```sh
sudo bash deploy/pi/install-drive-backup.sh /srv/ar-local/AR-local pi /srv/ar-local/data /var/lib/ar-local-drive-backup
```

The installer writes the three named backup units, a non-secret environment file,
and a `drive-backup.conf` environment drop-in for each of the daily, forced,
watchdog and boot-recovery ingest services. These producers inherit only backup
configuration paths and can queue terminal events without opening credentials.
The installer does not start or enable timers. On the uncommissioned Pi checked
on 2026-09-12 both timer names were **NOT_FOUND**, not verified installed/disabled.
Credentials live in `/var/lib/ar-local-drive-backup/credentials`, owned by `pi`,
mode 0700; individual credential files use 0600.

Create the Restic encryption password as the service user. The helper never prints the password and refuses to replace an existing file:

```sh
python3 pi_drive_backup_enroll.py password --credentials-dir /var/lib/ar-local-drive-backup/credentials
```

Store a separate recovery copy of `restic.password` in the user's password manager before commissioning. It is intentionally excluded from the encrypted repository it unlocks. A lost Pi must not mean a lost encryption key. Do not paste this password, the rclone configuration, or OAuth tokens into chat, logs, Git or a PR.

For Google authorization, open an ordinary-user SSH connection from the laptop, forwarding only the loopback OAuth port:

```sh
ssh -L 127.0.0.1:53682:127.0.0.1:53682 ar-local-pi5-lan
```

In that Pi session run:

```sh
cd /srv/ar-local/AR-local
python3 pi_drive_backup_enroll.py oauth --credentials-dir /var/lib/ar-local-drive-backup/credentials
```

Open the helper's emitted loopback URL in the laptop browser. The user selects their Google account and grants permission. The helper runs rclone on the Pi, captures provider output, and emits only the authorization URL and final status. The refresh token stays on the Pi; no token transfer or chat paste is needed. Enrollment times out after 15 minutes and never overwrites existing credentials.

The remote requests only `drive.file`. Let this rclone identity create the dedicated `AR-local Pi Backups/restic` folder; a folder created by another app may be invisible under that scope. Do not change the remote to broad `drive` scope to work around that restriction. Google consent is the only required user interaction for the recurring uploader.

## Commission and enable

Local readiness does not start a backup. Every command that accesses the
repository (`init`, remote readiness, `run`, `restore`) must run in the installed
backup service or an equally isolated commissioning service; a direct SSH
invocation fails closed. For one-time commissioning, use this bounded shell
function with the approved runtime and installed configuration:

```sh
drive_commission() {
  sudo systemd-run --unit="ar-local-drive-commission-$(date +%s)" --wait --collect --pipe \
    -p User=pi -p Group=pi -p WorkingDirectory=/srv/ar-local/AR-local \
    -p EnvironmentFile=/etc/ar-local/drive-backup.env -p UMask=0077 \
    -p CPUQuota=100% -p IOWeight=10 -p TasksMax=64 -p Nice=15 -p IOSchedulingClass=idle \
    -p MemoryHigh=512M -p MemoryMax=768M -p MemorySwapMax=0 -p OOMPolicy=stop \
    -p NoNewPrivileges=yes -p PrivateTmp=yes -p ProtectSystem=strict -p ProtectHome=yes \
    -p ProtectControlGroups=yes -p RestrictNamespaces=yes -p CapabilityBoundingSet= \
    -p KillMode=control-group -p TimeoutStartSec=20h -p TimeoutStopSec=30s \
    -p 'ReadWritePaths=/var/lib/ar-local-drive-backup /srv/ar-local/data/state' \
    /usr/bin/python3 /srv/ar-local/AR-local/pi_drive_backup.py "$@"
}
drive_commission readiness
drive_commission init
drive_commission readiness --remote
sudo systemctl start ar-local-drive-backup.service
```

`--control-file` requires an absolute canonical path; adjust the example if the approved runtime differs. The installed service already supplies absolute paths for its documented control files. `init` is only for the first repository creation; a rerun against an existing repository is expected to fail rather than reset it.

The first accepted backup must include a full cloud download to an isolated directory, SHA-256 verification of every restored file, and SQLite `integrity_check` plus `foreign_key_check`. The normal service performs this automatically before writing its first PASS receipt. Later runs check the repository each day; every seven days they also restore current data, all state, and a rotating historical date. An explicit full restore remains available:

```sh
drive_commission restore --full
```

After the first full restore PASS, start the installed service once (its control-file set also becomes part of the snapshot), inspect its final receipt, then enable both timers:

```sh
sudo systemctl start ar-local-drive-backup.service
sudo systemctl enable --now ar-local-drive-backup.timer ar-local-drive-backup-queue.timer
systemctl list-timers ar-local-drive-backup.timer ar-local-drive-backup-queue.timer
```

The daily timer runs at 03:30 Australia/Hobart. A second timer checks every half hour for terminal-observation requests or an interrupted day's work. UUID queue entries arriving during an upload remain pending for the next run. Configure `AR_LOCAL_DRIVE_BACKUP_SPOOL` for ingest/recovery services so their terminal hook queues a backup. The queue worker can also be invoked explicitly with `request --reason <reason>`.

## Evidence and recovery

The private spool holds immutable RUNNING/PASS/FAIL/BLOCKED receipts and source manifests. `latest-verified.json` identifies the accepted cloud snapshot, source content digest, manifest digest, repository stored bytes, newly uploaded bytes and most recent restore proof. A repository initialization, successful OAuth response, upload alone, or green unit test is not a restore proof. Keep existing backup arrangements until the first cloud restore PASS is observed.

Each Restic command also retains private diagnostics beneath its resource
operation's `diagnostics/<command-id>/`. `started.json` binds the command, worker,
parent and original request hash before launch; `process.json` identifies the
child. Raw stderr keeps at most32KiB of head and96KiB of tail in mode0600 files
inside mode0700 directories. One additional96KiB pending tail is the maximum
replacement overhead. The head and last complete tail survive a killed wrapper;
an absent final `result.json` means completion is unverified. Raw bytes can contain
credentials or provider identifiers: never publish them or copy them into normal
logs, Git, payloads or support messages. They remain outside the source data tree.

The immutable command result contains only hashes/counts and fixed diagnostic
categories. `API_RATE_LIMIT` is separate from `REMOTE_STORAGE_QUOTA`; labels are
matches in retained error text, not proof of the sole underlying cause. Normal
failure messages expose only command, exit code, category and private evidence ID.
Guard interruptions and lock refusal retain their existing failure semantics;
no diagnostic outcome advances backup acceptance or authorizes an automatic
unlock. If stderr capture fails or cannot drain, backup fails closed. Historical
failures recorded before this retention change cannot recover discarded stderr.

For disaster recovery, install Restic/rclone on a replacement host, recover the encryption password from its separate custody, and authorize access to the same dedicated Drive repository. Run `restic snapshots`, select the receipt-bound snapshot and `restic restore <id> --target <empty-private-directory>`. Restic restores absolute source paths beneath that private directory. The included source manifest maps each physical backup path to its logical `data/`, `control/` or `sqlite-original/` path and supplies SHA-256 digests. Verify every selected file before placing recovered data under a stopped production service. Use the merged SQLite copy for normal recovery; original DB components are reserved for exact historical reconstruction. Do not automatically overwrite a live data tree.

References: [Restic backup and deduplication](https://restic.readthedocs.io/en/stable/040_backup.html), [rclone backend](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html), [rclone Drive scope](https://rclone.org/drive/), [SSH OAuth setup](https://rclone.org/remote_setup/), [SQLite backup API](https://www.sqlite.org/backup.html).
