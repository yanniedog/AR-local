# File-level Pi system recovery set

This source implements an unencrypted, losslessly compressed recovery image.
It does not install a service, grant sudo, change a timer, upload to Drive, or
flash a disk. Runtime commissioning remains required. The existing plaintext
backup broker runs an unprivileged raw producer; it must not be reused unchanged
to launch this root image builder.

The offsite set consists of the OS/boot image, complete manifests and receipts,
and the exact accepted plaintext raw catalog/packs it references. An image with
`raw_restore_required: true` is a component of that set. It is not a complete
standalone copy of the raw archive and must not be accepted without verifying
and restoring that external layer. Preserve the existing encrypted fallback
and its recovery material until the new complete set passes readback/restore.
No new encryption key or recovery password is introduced.

## Protected execution boundary

The fixed bundle is `pi_system_namespace.py`, `pi_system_capture.py`,
`pi_system_image.py`, `pi_system_filesystems.py`, and
`pi_system_raw_restore.py`. Record the exact reviewed commit and independent
SHA-256 for every file. Using trusted system utilities, stage those bytes as
root-owned read-only regular files in a new protected directory whose entire
ancestor chain is root-owned and not group/other writable. Compare the copied
bytes with those independently recorded hashes **before executing Python**.
The launcher's self-check cannot make executing a malicious checkout safe.
Do not run a checkout or a Pi-writable staging script through sudo.

Create a protected read-only approval JSON with `files` mapping all five
filenames to those SHA-256 values. Retain its independently recorded hash too.
The protected entry command is:

```text
/usr/bin/python3 -I -S /protected/reviewed-bundle/pi_system_namespace.py PHASE --host-workspace /var/lib/ar-local-system-recovery/UNIQUE-NONCE --source-approval /protected/source-approval.json --source-approval-sha256 APPROVAL-SHA256
```

This is the worker entry point, not an admission bypass. Before native use, a
separate protected parent must integrate it with the existing shared queue's
`host` claim, production ownership/quiet-window rules, a bounded deadline,
whole-cgroup 640 MiB RSS enforcement, zero host swap-out, free-space/inode floors,
and independently recovered swappiness 60→0→60. The parent must keep its queue
claim through terminal cleanup and must not import candidate code as root.
The distinct image adapter and its native failure-path proof are prerequisites
to execution; a plaintext-producer success does not qualify these root phases.
There is no new sudoers/SSH route in this source.

The worker gets private PID, mount, network, IPC and UTS namespaces, fresh `/dev`
and `/proc`, read-only runtime/code mounts, and one private writable workspace.
Only source-reading phases expose the read-only root and boot aliases. Build
gets loop-control and `CAP_SYS_ADMIN`; physical device nodes are absent. This
is a boundary for **trusted, exact-reviewed root code**, not a claim that hostile
code retaining initial-user-namespace `CAP_SYS_ADMIN` cannot remount a bind.
Root-created private mount/PID namespaces and missing host process roots are
mandatory. No arbitrary program, physical disk, mount target or loop argument
is accepted.

## Inputs and measured capacity

Retain the actual `lsblk`, `findmnt`, `sfdisk`, filesystem/inode usage, active
service/timer and project-writer inventory. Do not treat a timed-out `du` prefix
as a complete size measurement. The normalized layout input contains only
`disk_id` (eight hex characters), `root_uuid`, and `boot_uuid`, derived from that
inventory. Capture independently reads the source FAT mount information and
records its UID/GID, explicit fmask/dmask, charset, shortname and time options.
Those options are replayed explicitly, independent of the parent's umask.

`baseline` accepts exactly `--layout`, `--catalog`, `--file-index`, and
`--catalog-sha256`. The three paths use their canonical `/source/root/...`
read-only aliases. The catalog digest must be the independently accepted
complete Drive readback, not a newly calculated unverified local substitute.
All later phases reject extra worker arguments. An optional root-controlled
`--restored-raw-workspace` is accepted by build alone for disaster reconstruction.

The initial inventory is disk-backed and counts all source files before copying
payload bytes. Its capacity receipt budgets private file staging, archive
overhead, the new image, worst-case compressed-image storage, and a reserve.
It also checks free staging inodes. Build rechecks actual free bytes before
creating the image. External exact raw files are counted only once across the
recovery set. An insufficient-capacity receipt is a refusal, not permission to
omit unique history, untracked work, credentials or another project's state.
An operator may propose disposal of only this operation's verified derived
staging after independent archive verification; this tool never deletes it.

## Capture phases and consistency

Run `baseline`, then `prepare`, under qualified bounded admission. Each makes a
complete online source inventory and stable private copies. The root parent
requires a protected `--writer-plan`, holds all four existing native apt/dpkg
record locks without writing their contents, observes the required apt service
and timer states, and refuses an unfinished `dpkg --audit`. The plan's
`package_writers` must include both `apt-daily` and `apt-daily-upgrade` services
and timers, plus any additional inventoried package owners. No timer is stopped
or started by this tool. Preparing and finalizing on different boot/package
states refuses, rather than pairing old binaries with new package state.

For `finalize`, the sole operator first quiesces every inventoried critical
application writer through its separately approved control path. The protected
writer plan contains:

- `application_writers`: exact inactive service/timer names, covering every
  project whose transactional state needs a consistent application boundary;
- `writer_paths`: a nonempty canonical relative path list for every such unit;
- `mutable_paths`: coverage of `etc`, `var`, `home`, `root`, `srv`, `opt`, and
  `usr/local`, plus every actual writer's paths;
- `online_os_capture`: explicit classifications for `usr`, `bin`, `lib`, `lib64`,
  `sbin`, and `boot`, identifying the accepted online package-quiesced window;
- `running_infrastructure`: the inventoried infrastructure left running, and
  a timezone-aware `expires_at` bounding application quiescence.

Root observes the real writer states before and after capture. The child cannot
reach host systemd. Unknown top-level work is refreshed as mutable. Cross-scope
hardlink groups refuse until the scope is expanded. The whole `/srv` scope is
retained; millions of raw/history entries may make finalization long. Measure
that work under the qualified deadline before approving a production pause;
do not assume it fits a few minutes. No full-host atomic snapshot is claimed.

Each copied non-directory file must have matching source identity before and
after copying, with at most three attempts. Continuously changing files cause a
refusal. Infrastructure can continue writing outside each file's capture window;
later bytes are not represented as having been captured. The full hashed source
observation JSONL records those windows/identities, and final receipts distinguish
online-prepared OS files from application-quiesced mutable state. Application
SQLite consistency requires the real writer inventory/quiescence; copying bytes
alone is not a database transaction snapshot. Boot contents/metadata must match
before and after finalization. The parent records postflight acceptance before
archives are allowed.

The root tree includes private configuration, credentials, untracked work and
all persistent project data. Runtime `dev`, `proc`, `sys`, `run`, `tmp`, the
separately captured `boot/firmware`, and exactly this new workspace have their
contents excluded. Volatile sockets have explicit map entries. An unexpected
persistent mount refuses until separately covered. Exact individual files under
CDR `runs`/`runs-archive` may be externalized only when current hash, size, owner,
mode and nanosecond mtime match the catalog's `exact_source_bytes` record.
No ancestor coverage claim omits a new or changed raw file. SQLite committed
views are never treated as exact original bytes.

## Archive, image and offsite acceptance

After root accepts `frozen.json`, resume the approved application writers.
`archive`, `build` and `compress` read private frozen bytes and can run under
later bounded claims. They have no source-root alias. Archives use standard PAX
tar and zstd level 15 with one thread, no encryption. Disk indexes preserve
global hardlinks and full binary ACL/xattr metadata without a global RAM list.
Archives checkpoint after at most 4096 entries/512 MiB source bytes, except one
larger file is one part. Valid completed parts are rehashed and reused; incomplete
derived artifacts are retained under new names. Archive parts must be restored
in order into the same destination for cross-part hardlinks.

Build exclusively creates a new `recovery.img`, records its inode before loop
attachment, proves kernel backing inode and partition identity before every
format/mount, and uses only that new loop's FAT/ext4 partitions. New filesystem
and partition identifiers avoid collisions with the original disk; only the
in-image `fstab`/`cmdline.txt` are rewritten. Full restored file hashes, ownership,
mode, nanosecond mtime, binary ACL/xattrs, symlinks, hardlinks and special-node
types must match. UUIDs are independently read back from the owned loop's
new superblocks. After unmount, read-only `fsck.vfat -n` and `e2fsck -f -n`
must pass on those proved partitions before detaching. These fixed tools must
be present and fit the guarded phase budget during native commissioning.
FAT comparisons use its actual source mount semantics;
unsupported metadata mismatches are failures. An uncertain loop/cleanup keeps
failure evidence for manual reconciliation, never detaches an unproved device.
Interrupted capture/build is not automatically restarted over existing outputs.

Compression checkpoints verified 1 GiB logical image frames. Preserve ordered
`compressed_parts`; concatenating and zstd-decompressing those frames reconstructs
the exact raw image whose full SHA-256 is in `recovery-set.json`. This raw image
can subsequently be supplied to Raspberry Pi Imager. The file-level approach is
consistent with [raspiBackup's restore model](https://framps.github.io/raspiBackupDoc/restore-intro.html),
but this implementation does not execute or vendor raspiBackup.

The keyless, file-only reassembler works on Linux and Windows with the pinned
`zstandard` requirement. Download the image frames into one private mirror and
use the independently retained recovery-set digest:

```text
python pi_system_image_restore.py --mirror DOWNLOADED-IMAGE-OBJECTS --recovery-set DOWNLOADED-IMAGE-OBJECTS/recovery-set.json --recovery-set-sha256 ACCEPTED-SHA256 --workspace NEW-PRIVATE-OUTPUT-DIRECTORY
```

It creates `recovery.img` only inside a newly created private directory, verifies
compressed/frame/global image hashes, and retains `raw_restore_required` in its
result. No disk or overwrite option exists. Windows directory creation applies
a protected current-user/SYSTEM DACL before any image bytes are written.

For full disaster reconstruction, the standalone plaintext raw restore tool
restores exact originals into its new private `data/` tree and committed views
separately. Build's optional raw workspace input independently validates its
catalog receipt and every external file, reapplies the image map's original
metadata, and performs a full joined filesystem comparison. This larger image
is a recovery/proof option; do not upload a second complete raw layer needlessly.

The protected uploader must transfer actual image frames, manifests, external
map, source observations, receipts and catalog bindings into private Drive
storage, then read them back completely by SHA-256. Intermediate OS tar archives
remain private reconstruction/proof artifacts; do not also upload that duplicate
OS layer without a specific necessity. Image objects require their own fixed,
create-only protected transport namespace and complete readback; do not weaken
the plaintext raw transport's path whitelist. Reuse already valid raw
packs; preserve fallback copies until the new set is complete. Source tests,
`ARCHIVED`, `FILESYSTEM_RESTORE_VERIFIED`, and local compression do not prove
offsite bytes. Acceptance requires actual full OS metadata restore and exact
external raw contents from the same accepted catalog, boot configuration
structure, clean loop cleanup, and complete Drive readback. Record physical
`boot_test: NOT_TESTED` until a real independent boot occurs. A physical boot is
a separate proof category, not an invented prerequisite to CI-account setup.

Never overwrite connected historical SD/USB media for a test. Actual physical
flashing/destructive data actions require a fresh, one-operation approval using
the separately registered conversational codephrase after presenting exact
target, commands, backup receipts and recovery plan. That phrase is distinct
from the sudo password and is never an OS credential or perpetual authorization.
