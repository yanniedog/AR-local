# Daily CDR day-archives (unencrypted Google Drive)

Operator-authorized series of **one highly compressed, unencrypted**
`YYYY-MM-DD.tar.zst` per Australia/Hobart calendar day since CDR ingests
started (`2026-05-13`). Each archive holds the reconstructable primary material
for that day (run tree, day-keyed state, optional archive/stage/log slices, and
journalctl exports for AR-local units). Higher-order app payloads and dashboard
caches are excluded.

## Drive layout

Under the enrolled `drive.file` remote:

```text
AR-local Pi Backups/
  restic/
  daily-cdr-day-archives/     # this series
    YYYY-MM-DD.tar.zst
    YYYY-MM-DD.sha256
    YYYY-MM-DD.manifest.json
    YYYY-MM-DD.GAP.json       # permanent gaps only
    CONTROL.tar.zst           # global binding pointers
    CONTROL.sha256
    CONTROL.manifest.json
```

Uploads are create-only (`rclone copyto --immutable --ignore-existing --checksum`).
After a **re-download sha256 verify**, only the local compressed workspace files
are removed. Source trees under `/srv/ar-local/data` are never deleted by this
worker.

## Compression

PAX `tar` + Zstandard **level 19**, checksummed frame, **no encryption / no
password** (`zstd-lossless-no-encryption-level-19`).

## Permanent gaps

`2026-05-14` and `2026-06-26` receive a small `YYYY-MM-DD.GAP.json` marker only.
No fabricated observation archive is uploaded.

## Worker

```sh
python3 pi_daily_cdr_day_archive.py --backfill --max-days 3
python3 pi_daily_cdr_day_archive.py --date 2026-05-13
python3 pi_daily_cdr_day_archive.py --once-pending
python3 pi_daily_cdr_day_archive.py --control
python3 pi_daily_cdr_day_archive.py --request 2026-10-25
```

Defaults:

| Setting | Value |
|--------|--------|
| Data root | `/srv/ar-local/data` (`AR_LOCAL_DATA_ROOT`) |
| Spool | `/var/lib/ar-local-day-archives` |
| rclone config | `/var/lib/ar-local-drive-backup/credentials/rclone.conf` |
| Remote | `ar_local_drive:AR-local Pi Backups/daily-cdr-day-archives` |

Quiet window: refuses work **00:30–02:00** Australia/Hobart.

Progress ledger: `/var/lib/ar-local-day-archives/progress.jsonl`.

## Ongoing coverage

Successful `cdr_daily` finalize calls `request_day_archive(date)`, writing
`/var/lib/ar-local-day-archives/requests/<date>.json`. The
`ar-local-day-archive.timer` drains pending requests outside the quiet window
via `pi-shared-task` / the installed service.

## Google Drive write-hold lift (operator 1B)

The code provides **no** automatic hold release. Under explicit operator
approval to lift the hold entirely:

1. Confirm no in-flight `ar-local-drive-backup.service` / queue worker.
2. Inventory and record hashes for:
   - `/etc/ar-local/drive-write-hold.json`
   - `/etc/ar-local/.drive-write-hold-activation.lock`
   - any spool `write-hold.json` / hold symlinks under
     `/var/lib/ar-local-drive-backup/`
3. As root, remove the hold markers after recording hashes.
4. Re-enable timers:
   `systemctl enable --now ar-local-drive-backup.timer ar-local-drive-backup-queue.timer`
5. Enable day-archive timer after the worker is installed:
   `systemctl enable --now ar-local-day-archive.timer`
6. Append a handoff ledger entry documenting lift + day-archive series start.
7. Create the Drive subdirectory (worker `ensure_folder`) and begin sequential
   backfill from `2026-05-13`.

## Coverage honesty

Early retained days may be `exports_only` (cleaned SQLite/JSON without wire HTTP
journals). Modern days with promoted attempt evidence classify as `wire_raw`.
Missing historical wire corpora cannot be invented; the archive contains
everything that still exists for that day.
