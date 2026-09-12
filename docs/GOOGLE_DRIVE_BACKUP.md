# Pi Google Drive backup

This implements the 11 September 2026 decision in [CDR_QUALITY_PIPELINE.md](CDR_QUALITY_PIPELINE.md): the Pi owns backup delivery, with no laptop or interactive session dependency. Until OAuth enrollment, the first upload, repository checks and the first full restore pass, the outcome is **BLOCKED**, not a commissioned backup.

Restic repository version 2 encrypts and compresses content. The first snapshot covers every retained CDR date and generation. Later snapshots reference existing chunks and upload only new or changed compressed chunks. Each snapshot remains a complete restore point; there is no growing full ZIP uploaded each day. All snapshots are retained indefinitely. No `forget`, `prune`, `delete`, `purge` or `sync` command is exposed by this workflow. Storage still grows with distinct retained data and metadata.

## Scope and consistency

The source includes `runs`, `runs-archive`, `state`, `logs` and `predeploy`, including failed observations, recovery records, immutable revisions, raw responses, manifests and ledgers. Unknown top-level namespaces fail closed for classification. Netdata telemetry, Git, caches, credentials and secret-bearing configuration filenames are excluded and recorded. Explicit non-secret control files document the service and recovery procedures.

The worker acquires the shared ingest lock only for a bounded source freeze. Immutable run files retain their original paths and are checked for changes after upload. Mutable state and logs are copied to a private spool outside the authoritative data root. SQLite databases with retained WAL/journal files are copied privately before SQLite backup merges committed changes. Original main/WAL/journal bytes are also retained under `sqlite-original/` for historical artifact reconstruction. Shared-memory files are disposable and excluded. Nothing opens the production SQLite databases for writes.

The ingest lock is released before network upload, repository checking or restore. Restic is limited to two Go workers, 8 MiB/s network bandwidth and two transfers; the service adds CPU, memory and I/O limits. Source freezing has a 20-minute limit and stops before the 00:30–03:30 Hobart ingest quiet window. Uploads crossing that window are terminated safely and retried later. A 2 GiB free-space floor protects the private spool; a restore also requires room for its selected data. Interrupted or rejected uploads never advance `latest-verified.json` or acknowledge queued requests.

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

The installer writes only the three named systemd units and a non-secret environment file. It leaves both timers disabled. Credentials live in `/var/lib/ar-local-drive-backup/credentials`, owned by `pi`, mode 0700; individual credential files use 0600.

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

As the service user, load the installed non-secret configuration, verify prerequisites, initialize the dedicated encrypted repository, and run the first backup:

```sh
set -a
. /etc/ar-local/drive-backup.env
set +a
python3 pi_drive_backup.py readiness
python3 pi_drive_backup.py init
python3 pi_drive_backup.py readiness --remote
python3 pi_drive_backup.py run --force --control-file /srv/ar-local/AR-local/docs/GOOGLE_DRIVE_BACKUP.md
```

`--control-file` requires an absolute canonical path; adjust the example if the approved runtime differs. The installed service already supplies absolute paths for its documented control files. `init` is only for the first repository creation; a rerun against an existing repository is expected to fail rather than reset it.

The first accepted backup must include a full cloud download to an isolated directory, SHA-256 verification of every restored file, and SQLite `integrity_check` plus `foreign_key_check`. The normal service performs this automatically before writing its first PASS receipt. Later runs check the repository each day; every seven days they also restore current data, all state, and a rotating historical date. An explicit full restore remains available:

```sh
python3 pi_drive_backup.py restore --full
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

For disaster recovery, install Restic/rclone on a replacement host, recover the encryption password from its separate custody, and authorize access to the same dedicated Drive repository. Run `restic snapshots`, select the receipt-bound snapshot and `restic restore <id> --target <empty-private-directory>`. Restic restores absolute source paths beneath that private directory. The included source manifest maps each physical backup path to its logical `data/`, `control/` or `sqlite-original/` path and supplies SHA-256 digests. Verify every selected file before placing recovered data under a stopped production service. Use the merged SQLite copy for normal recovery; original DB components are reserved for exact historical reconstruction. Do not automatically overwrite a live data tree.

References: [Restic backup and deduplication](https://restic.readthedocs.io/en/stable/040_backup.html), [rclone backend](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html), [rclone Drive scope](https://rclone.org/drive/), [SSH OAuth setup](https://rclone.org/remote_setup/), [SQLite backup API](https://www.sqlite.org/backup.html).
