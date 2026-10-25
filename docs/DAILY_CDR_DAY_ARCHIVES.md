# Daily CDR raw records (unencrypted Google Drive)

Operator-authorized series of **one highly compressed, unencrypted**
`YYYY-MM-DD.tar.zst` per Australia/Hobart calendar day since CDR ingests
started (`2026-05-13`). Each object is a complete full raw record for that day:
every byte still on disk that ingest requested or received, plus the logs of
those attempts.

Included when the file still exists:

- `runs/<day>/` including `banks/` (`product-detail.json`, `product-id.txt`,
  `product-detail.error.txt`, `failures.jsonl`), `holders/`,
  `_raw-attempt-journals`, `attempt-evidence`, `_failed_attempts`, `_revisions`
- `_exports/` for that day, including `local-cdr.sqlite` and
  `banks-YYYY-MM-DD.json` / `.xlsx` when those are the surviving reconstruction
  inputs
- day-keyed state: `<day>.done.json`, `<day>.integrity.json`, `<day>.*.json`,
  `export-contracts-v2/<day>`, `ledger-v2/events/<day>`,
  `observation-selections-v1/<day>`, revision markers
- day slices of `runs-archive`, `.daily-raw-stage`, `logs`, `predeploy`
- systemd journals for that Hobart midnight-to-midnight window for
  `ar-local-daily`, `ar-local-ingest-now`, `ar-local-daily-watchdog`, and
  `ar-local-drive-backup` (written even when the range is empty)

Excluded as derived serving or publication copies: directories named
`dashboard-cache`, `app-payload`, and `app-payload-latest` (any
`app-payload-*` directory). SQLite and `banks-YYYY-MM-DD` exports are kept.
They do not by themselves make a day `wire_raw`.

`daily-cdr-day-archives/` remains on Drive. Those objects were uploaded
create-only and are export-only (no journals, no product-detail bodies). This
worker does not delete them and does not upload the raw series into that
folder, because `--immutable --ignore-existing` cannot replace them.
`deploy/pi/install-day-archive.sh` rewrites an installed
`AR_LOCAL_DAY_ARCHIVE_REMOTE` whose last segment is `daily-cdr-day-archives`
to `daily-cdr-raw-records`, using inline standard-library Python under
`python3 -I -S` so the root installer does not import the checkout. The
transport still rejects the legacy folder.

## Drive layout

Under the enrolled dedicated `drive.file` remote (see Pi
`/etc/ar-local/drive-backup.env`):

```text
AR-local Pi Backups Dedicated …/
  restic/
  daily-cdr-day-archives/     # retained export-only series; do not reuse
  daily-cdr-raw-records/      # this series
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
worker. `--skip-journals` is rejected.

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
| rclone config | dedicated verified conf under `/var/lib/ar-local-drive-backup/credentials/` |
| Remote | `…/daily-cdr-raw-records` beside the enrolled `restic/` folder |
| Journals | always on (`ar-local-daily`, `ar-local-ingest-now`, `ar-local-daily-watchdog`, `ar-local-drive-backup`) |

Quiet window: refuses work **00:30–02:00** Australia/Hobart.

Progress ledger for this series: `/var/lib/ar-local-day-archives/meta/raw-progress.jsonl`.
Older `progress.jsonl` PASS rows belong to `daily-cdr-day-archives/` and are not
treated as done. The timer runs `--once-pending` with journals on. Install the
unit against the day-archive seed checkout
(`/var/lib/ar-local-day-archives/src/AR-local`), not by canary-bypassing
`/srv/ar-local/AR-local`.

## Ongoing coverage

Successful `cdr_daily` finalize calls `archive_observation_day(date)` before
seal or any cleanup that removes that day's raw files. The upload is
synchronous, journals stay on, and the same Hobart day is allowed so the
still-present banks tree is in the tar. Cleanup runs only when the result is
`PASS` (verified upload; local tar removed only after that verify). Any other
result leaves the raw tree in place. `ar-local-day-archive.timer` still drains
queued requests; it is not the ingest cleanup gate.

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

The manifest `coverage` is one of `wire_raw`, `exports_only`, `partial`, or
`gap`.

| Class | Meaning |
|--------|---------|
| `wire_raw` | A banks-tree `product-detail.json` / `product-id.txt` / `product-detail.error.txt`, or bytes under `_raw-attempt-journals`, `attempt-evidence`, or `_failed_attempts`, still exist |
| `exports_only` | Surviving `_exports` (including sqlite and `banks-YYYY-MM-DD.json` / `.xlsx`) and no wire body |
| `partial` | Some other day-keyed bytes, and neither wire bodies nor exports |
| `gap` | Permanent gaps `2026-05-14` and `2026-06-26` only. `YYYY-MM-DD.GAP.json` markers, no fabricated archive |

`raw_banks_absent` is true when `runs/<day>/banks/` is already gone. Do not
invent it. `journal_status` is `captured`, `empty`, or `unavailable`.
`journals_absent` is true when journalctl could not be read and no journal
file was stored. Empty journal files are kept. A missing historical wire body
stays missing.
