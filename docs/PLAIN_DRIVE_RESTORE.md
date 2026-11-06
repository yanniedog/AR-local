# Plain Drive breakglass raw-file restoration

The raw recovery objects are losslessly compressed tar.zst files, without
encryption, passwords or a recovery key. Keep the accepted catalog SHA-256 and
its object path with the offsite recovery record. The catalog binds every pack,
its full verification result, the exact-source file index and explicit excluded
paths. Existing encrypted Restic snapshots remain a separate preserved fallback.

`pi_plain_backup_restore.py` is a local, manually invoked recovery command. It
requires Python 3.11+ and this repository's source files and dependencies
(`python -m pip install -r requirements.txt`). These include
`zstandard==0.25.0` and Windows timezone data (`tzdata`).
It needs neither a functioning Pi nor its SSD, sudo credentials, an active
backup broker, a queue lease, nor an encryption key. It performs no network,
upload, deletion of pre-existing files, flashing or production-root writes.

## Obtain the objects

Download the accepted catalog, its `manifests/<sha256>.jsonl` file index, and
every `packs/<pack_id>/archive.tar.zst` named by that catalog from the dedicated
Drive folder's `plaintext-recovery` child. Preserve that relative directory
structure inside a new local `downloaded` directory. Pack descriptors may be
retained too; restore uses the descriptors already bound into the catalog.

The Drive web interface can download these objects. Unzip a browser-created ZIP
into a private staging directory and arrange the paths above; do not unpack the
tar.zst payloads with an unchecked general extraction command. A second method
is a read-only download using an already approved rclone configuration:

```sh
rclone copy approved_remote:plaintext-recovery /recovery/downloaded \
  --drive-root-folder-id APPROVED_DEDICATED_FOLDER_ID \
  --immutable --checksum --transfers 1 --checkers 1
```

Use the existing private folder's recorded ID, rather than a folder-name search.
This `copy` reads Drive and writes a new local destination. Do not use `sync`,
`delete`, `purge`, or a reverse source/destination order. Confirm downloads have
completed before starting the restore. Missing, changed or corrupted objects
cause failure; the tool never repairs cloud content or invents missing files.

## Restore into a new directory

Use an empty private recovery disk with space for all restored files, the object
mirror and the desired system image. NTFS or a Linux filesystem is required for
the hardlinks used between local restored representations; FAT/exFAT is not a
suitable output filesystem. The workspace path must not already exist and must
be outside the downloaded mirror. Replace the example paths and SHA with the
accepted recovery receipt values:

```sh
python pi_plain_backup_restore.py \
  --mirror /recovery/downloaded \
  --catalog /recovery/downloaded/catalogs/ACCEPTED_SHA256.json \
  --catalog-sha256 ACCEPTED_SHA256 \
  --workspace /recovery/restored-NEW \
  --max-hours 24 --free-space-floor-mib 1024
```

The same command works in PowerShell with Windows absolute paths and either a
single line or PowerShell's backtick line continuation. The catalog hash must
come from the independently retained accepted receipt. Calculating a new hash
of an unknown catalog proves neither its provenance nor its completeness.

The command hashes each compressed pack, enforces a single complete checksummed
Zstd frame, reconstructs its content address from the embedded file manifest,
and streams each regular member into private files with exclusive creation. It
rejects unsafe paths, symlinks, hardlink/device archive entries, duplicate or
missing mappings, unexpected members, metadata differences and corrupt bytes.
Committed-view SQLite files receive integrity and foreign-key checks. Their
new proof must exactly match the accepted catalog's proof. JSON arrays and path
indexes are processed on disk; individual JSON records are limited to 16 MiB,
file-index lines to 64 KiB and Zstd windows to 128 MiB. Duration and free-space
guards stop the operation before a success receipt is written.

On success the new workspace contains:

- `data/<source_relative>`: exact source bytes, including original SQLite
  databases and their captured WAL or rollback journals. This is the raw tree
  consumed by the system-image external recovery map.
- `committed-view/<source_relative>`: consistent SQLite committed views. These
  deliberately occupy a separate tree from the original database/journal pair.
- `logical/<logical_path>`: every archive member, including separately named
  external control files and both SQLite representations. Data/view trees use
  local hardlinks to these verified files without another full copy.
- `restored-files.jsonl`, retained embedded manifests, `excluded-paths.jsonl`
  and `restore-result.json`: original file metadata, mapping and verification
  evidence. Exclusions require the complementary system image; they are not
  silently treated as raw-file backup coverage.

On Windows the new workspace is created atomically with a protected DACL for
the current user and SYSTEM; a filesystem with persistent ACLs is required.
On POSIX it is mode 0700. No existing directory's ACL is changed. New files
request mode 0600 (the Windows workspace's DACL provides privacy), and apply original file mtime with the
output filesystem's precision; the exact nanosecond value stays recorded. Original
ownership and mode are retained in the evidence. To apply those values to
mapped files on Linux, run the same command as root with `--apply-metadata`,
using a different new workspace. Directory ownership/mode and ACL/xattrs come
from the separately verified system image and external recovery map. Windows
cannot apply Linux ownership; its successful byte restore does not claim that
metadata step. External controls retain their logical names and recorded
metadata; placement at their original operating-system paths is an operator
recovery step, never an automatic overwrite.

Never open the exact original DB beside its restored WAL for routine inspection:
SQLite may replay or checkpoint that pair. Query the committed view, or copy
the original database and journal into another private drill directory first.
Do not overlay a committed view onto a raw database while retaining its old WAL.

A failed attempt remains an incomplete private workspace without
`restore-result.json`. Preserve it for diagnosis or dispose of that exact new
directory after checking its identity; start a retry at another new workspace.
No successful local fixture test, source review or hash receipt alone proves the
real Pi's full offsite backup or a bootable recovered machine. Full native raw
restore, system-image readback/reconstruction and boot acceptance remain separate
recorded checks.
