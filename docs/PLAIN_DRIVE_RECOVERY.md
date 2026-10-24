# Manually authorized plaintext Drive recovery packs

The operator's 24 October 2026 instruction requests lossless compression without
archive encryption or recovery keys. `pi_plain_drive_backup.py` implements that
bounded manual workflow. Existing encrypted Restic snapshots, credentials and
the installed Restic hold are preserved. This source does not install or start
services/timers, release the hold, change sysctls, capture a system image, or
establish a passing native resource/boot acceptance result.

The CLI is a real worker, intended for the independently qualified root control
broker. The broker supplies a new private operation directory, the existing
`drive.file` application's private rclone config, a root-sealed read-only memfd
attestation, and a deadline. The worker requires NNP and
exclusive host queue ownership. It never starts another queue job or acquires
the native lock already held by that queue owner. Ordinary `freeze()` callers
retain the original production-lock behavior.

The sealed handoff binds the queue owner, boot, invocation, native/source inode,
operation, approved destination, runtime closure and expiry. A qualified root
monitor outside the sandbox continuously verifies actual host queue/native
ownership and resources. The worker validates memfd ownership, full seals,
read-only access, hash/inode stability, deadline, actual cgroup, exact Pi UID/GID,
NNP/empty capabilities and source read-only mount. It requires distinct private
PID and mount namespaces while retaining the host user namespace so archive
UID/GID metadata stays faithful. Host `/proc` is deliberately unavailable:
exposing another Pi process's `/proc/<pid>/root` could escape read-only binds.
The native file's exact manual owner bytes remain point-checked through its
read-only source view. Verification never clears or adopts that holder's lock.

The existing source freezer preserves every retained raw attempt, failed
observation, revision, database, state/log and predeploy namespace in its explicit
scope. The explicit manual plaintext pipeline also preserves a nonempty
`.daily-export-stage` as private frozen copies, including retained export bytes
and consistent plus original SQLite representations. Its catalog scope records
policy version 2 and `retained_export_stage_policy: include-if-present`; catalog,
file-index and pack schemas remain unchanged. Routine legacy snapshots retain
their version 1 empty-stage requirement. The coupled probe checks this same
read-only source scope before reporting success, without freezing or cloud calls.
For retained staging, directory identities are recorded before traversal in the
private SQLite manifest index, including empty directories. They are checked
after traversal and before catalog/candidate acceptance; copied retained-file
identities are also rechecked. A concurrent addition, removal, replacement or
content change rejects acceptance. These proofs stream from disk with the
existing bounded SQLite cache rather than retaining the tree in memory.
The probe additionally validates retained-stage descendant metadata with the
same excluded-namespace, symlink and unique-regular-file checks, limited to
500,000 metadata checks or 60 seconds within its existing operation deadline.
That probe-only entry budget allows approximately three times the measured
168,438-check retained tree, which completed metadata-only validation in 10.33s.
The source validator's legacy 100,000-check default remains unchanged. The probe
checks its absolute monotonic deadline for every entry, verifies the complete
sealed lease before and after validation and at 100ms checkpoints during it, and
retains the independent Root monitor and existing 120-second probe limit.
It reads no retained payload bytes and does not claim a complete archive proof.

Legacy source freezes keep their 1,200-second default. The typed manual plaintext
path uses the remaining sealed host-operation monotonic deadline for its first
full inventory, which can exceed 20 minutes on large archives. It creates no
separate timeout allowance: the six-hour outer deadline, quiet window, free-space
and whole-cgroup resource guards continue to stop work. A local freeze timeout
reports only the fixed `source_freeze_deadline` code, without source paths.
Unknown top-level namespaces fail closed. Existing credential/cache and
telemetry exclusions remain explicit; this is a CDR recovery archive, not a
whole-filesystem image. Mutable SQLite input is copied privately, including the
original database/journal bytes, before deriving its consistent committed copy.
Production databases are never opened for writes.

Packs are grouped into date bases, individual observation/revision namespaces,
historical archive namespaces, and mutable controls. They contain deterministic
PAX tar members compressed using checksummed single-thread Zstandard level 15.
Content IDs include every logical path, SHA-256, size, mode, nanosecond mtime,
uid/gid and SQLite/original classification. Metadata is preserved in tar headers
and the embedded JSON manifest; restoration of privileged ownership is an
operator step. There is no password, key, archive encryption or crypt backend.

The disk-backed manifest/group index has a 2 MiB SQLite cache. File and archive
reads use the existing bounded cache-advised read path where supported. The
guard callback is applied throughout I/O; the CLI enforces at most six hours,
the 00:25–03:30 Hobart cleanup/quiet margin and a 2 GiB workspace free-space
floor. These are additional worker checks. The broker must still supply sampled
whole-cgroup resource containment, host headroom, zero-swap acceptance and
independent reclaim/cleanup. No hard memory limit is inferred on this Pi.

The rclone adapter accepts only an existing `drive`/`drive.file` config and a
`plaintext-recovery` child under a root-approved Drive folder ID, passed explicitly
as `--drive-root-folder-id` on every transport command. Remote name and folder ID
must match the root-sealed context; ambiguous folder names are insufficient. It exposes
only create-only `copyto --immutable --ignore-existing --checksum` uploads and
downloads. It has no delete, purge, move, sync, enrollment or credential-output
operation. Quota and prior plain archive inventory remain operator preflight;
this module does not search unrelated Drive identities or silently broaden the
OAuth scope. Existing packs in this format are reused after verification; other
historical archive formats require independent inventory/adoption rather than
being assumed absent or equivalent. Restic ciphertext cannot substitute for
the requested unencrypted archive.

Before a pack descriptor is published, the full cloud archive is downloaded,
its compressed SHA-256 verified, its complete checksummed Zstd frame checked,
and every tar member's order/type/path/metadata and restored bytes compared with
the independently frozen manifest. All selected consistent SQLite databases
pass integrity and foreign-key checks in private scratch. No archive extraction
writes paths supplied by tar. Only the currently verified SQLite member needs
scratch space. Missing/extra members, truncated checksum frames, unknown source
changes and nonzero trailing data refuse acceptance.

A resumed pack is skipped for upload only after its cloud descriptor matches
the current content ID and a fresh complete download passes those same checks.
An interrupted archive upload without a descriptor may be reused only when it
its complete downloaded contents match the independently frozen manifest.
Existing differing objects are never replaced. The complete content-addressed
catalog retains every pack's restored-file and SQLite counts/check digest plus
the streamed source-exclusion listing/count/digest. It is uploaded only after
all packs pass; its own full readback is verified. No mutable rolling pointer is
overwritten. The local candidate receipt explicitly requires external complete
resource acceptance and a separate system recovery image; it is not evidence
that those stages have passed.

The catalog also binds `file_index`: a content-addressed `manifests/<sha>.jsonl`
file with a full cloud readback. Its first line contains
`schema=ar-local-plain-file-index-v1` and `data_root`. Remaining lines include
source-relative path, logical member, pack ID, bytes/hash and metadata. An
`exact_source_bytes` representation can justify omitting a duplicate file from
the system image only after comparing its actual bytes/metadata. A
`sqlite_committed_view` is derived and cannot justify such an omission; its
`sqlite-original` counterpart preserves the exact original components. This raw
pipeline rejects external control files before reading or freezing sources;
only the root-attested CDR data tree is admitted. Full operating-system controls
belong in the separately approved system image.
Never infer whole-directory image exclusions from one covered descendant.

Pack paths must be canonical, contain no backslashes and remain unique under
case folding across the disk-backed index. Signed PAX timestamps preserve the
original nanosecond value, including times before the Unix epoch. Every transfer
constructs its own fixed-direction local/allowlisted-remote endpoints; there is
no public arbitrary copy command.

After independently accepted native execution, keep the catalog digest/path,
source scope and exclusions, resource receipt, broker restoration proof and
image/restore instructions together in the offsite recovery record. Existing
fallback snapshots remain until the operator separately approves their removal.
Do not delete an older fallback just because a newer upload returned success.
