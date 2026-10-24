# Guarded system recovery phases

This adapter provides a distinct root control path for the file-only system
image backend. It does not widen the plaintext raw producer's Pi UID, NNP or
zero-capability rules. Source tests do not qualify native deployment: the exact
installed closure must pass the actual private-image `PROBE` below before any
real source capture. No native run or Drive image upload is claimed by this PR.

The final Drive set contains the existing content-addressed raw packs/catalog,
compressed OS image frames, manifests/maps/proofs and exact restore tools. It
does not upload duplicate OS tar layers. The new set uses lossless Zstandard15,
one compression thread and no encryption. Existing encrypted fallback objects
and recovery material remain untouched. Keep the approved Drive folder private.

## Protection and installation

Use a fresh protected staging directory. Independently record the reviewed Git
head and SHA256 of the installer, entry and every payload file on this PC.
Trusted system utilities must copy exactly those bytes to root-owned read-only
regular files beneath exclusively root-controlled ancestors. Compare every
copied digest **before the first root execution**. Do not sudo a mutable checkout
or a Pi-writable script. The installer's own checks supplement that independent
review; they cannot establish trust in malicious initial executable bytes.

`pi_system_guard_install.py` is stdlib-only. Its `plan.json` has schema
`ar-local-system-recovery-install-v1`, `manual_system_recovery: true`, `files`
mapping the exact `ALIASES | MODULES` target set to SHA256 values, and `plain`
mapping the four qualified incumbent controls to SHA256 values. Alias targets
use the exact reviewed `pi_system_guard_entry.py` bytes. Also bind the incumbent
recovery wrapper SHA, unchanged global Drive hold SHA, existing
`NAME:plaintext-recovery` remote and approved Drive root folder ID. No OAuth
enrollment or new credentials are requested.

Validate only, from that protected stage:

```text
/usr/bin/python3 -I -S -B /PROTECTED/pi_system_guard_install.py --stage /PROTECTED --plan-sha256 REVIEWED-PLAN-SHA --installer-sha256 REVIEWED-INSTALLER-SHA
```

Explicit `--install` additionally requires the actual occupied exclusive
`host` + `ar-local` native queue claim. It creates a **new** fixed
`/usr/local/lib/ar-local-system-recovery` closure and distinct fixed state
directories, plus `/etc/ar-local/system-recovery-reconcile.json`. It refuses an
existing image installation or registry; preserve ambiguous partial output for
review. New directories use held-FD fchown/fchmod after mkdir, independent of
service UMask0077. Unexpected existing modes fail without silently relaxing
permissions. There is no account, sudoers, timer or schedule modification.

The separate reviewed queue-hook/recovery-wrapper extension must already support
the exact image authority and completion schemas. Its installed queue copy,
plaintext root-control manifest and wrapper manifest must transition together;
replacing only a hook would invalidate the incumbent plain broker. Do not start
either workload across a partially installed closure transition.

## Exact one-shot launch and native commissioning

Protected entries use `/usr/bin/python3 -I -S -B`. They verify the complete
root-owned source closure before registering only exact module filenames;
neither control directory is added to Python's search path. Child `/code` is
empty except individually bound approved files, preventing sibling stdlib
shadowing. Source-reading phases alone expose readonly root/boot aliases.
Build and PROBE have private PID/mount namespaces and the reviewed capability
set needed for owned loop filesystems. Physical device nodes are absent. This
boundary protects execution of **trusted reviewed root code**; initial-user-
namespace CAP_SYS_ADMIN is not a sandbox for hostile arbitrary root code.

Generate fresh independent32hex operation and workspace IDs. Prepare a PROBE:

```text
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/prepare.py PROBE OPERATION32 WORKSPACE32
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/start.py OPERATION32
```

Preparation publishes authority last and starts nothing. Start accepts only the
prepared nonce and reconstructs the exact service plan, then submits a one-shot
native queue service. It has no recurring schedule API. A submitted unit is not
accepted work. The Pi parent may invoke only fixed root acquire/finish helpers;
the privileged stop hook invokes fixed recover. Existing Pi NOPASSWD access, if
present, is not cryptographically restricted by this conversational procedure.

New image packets freeze six nonsecret runtime inputs: nonce, unit, mode,
UTC creation/expiry and integer `runtime_seconds`. The duration must equal the
floor of expiry minus creation, with a minimum15 seconds and mode caps120/21600;
it cannot be an arbitrary override. The queue argv, native RuntimeMax and root
job admission bind the same exact duration. New phases use wait0: a busy or
delayed claim must fail closed and finish normal cleanup before another fresh
nonce is prepared. The absolute expiry is also enforced by the worker context.
Preparation and admission require the protected referenced PROBE packet and
privileged coupled proof to match the current image root-manifest digest,
complete source closure and boot. This digest belongs to the image controller;
it is independent from the incumbent plaintext controller's manifest. Historical
plaintext terminal recovery retains its original proof bytes and does not
qualify a new acquisition.

The actual PROBE creates new private generic files with an ACL, binary xattr,
hardlink, symlink and FIFO. It creates a new sparse regular image, attaches only
its inode-proved loop, formats private FAT/ext4 partitions, restores and verifies
all fixture metadata, rewrites/checks boot identifiers, performs readonly fsck,
unmounts and detaches. It also checks intended directory750 under native0077.
It reads no real application source and writes no Drive object. It may publish
`IMAGE_PROBE_PASS` only after actual file/loop proofs, resource acceptance,
policy60 restoration and the real privileged native stop hook all pass on the
same boot and exact closure. An unexecuted PROBE is `NOT_TESTED`.

## Production phases and recovery

The fixed phases are `baseline`, `prepare`, `finalize`, `archive`, `build`,
`compress`, `upload`. Each gets a fresh operation nonce, the persistent workspace
ID and the accepted same-closure PROBE nonce. Inputs are protected, readonly
`layout.json`, `raw-catalog.json`, `raw-index.jsonl`, `writer-plan.json` below
`/var/lib/ar-local-system-recovery-inputs/WORKSPACE32`. Catalog identity must
already be accepted from full Drive readback. The raw index is streamed into
SQLite; the catalog parser refuses over32MiB and retains only its descriptor/SHA.

```text
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/prepare.py PHASE OPERATION32 WORKSPACE32 PROBE32
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/start.py OPERATION32
```

Each phase owns the existing host queue/native lease, applies temporary
swappiness60→0 only after a durable PREPARED record, and uses the existing
640MiB whole-cgroup RSS early stop, zero workload swap, zero new host swap-out,
headroom/PSI, deadline, free-byte/inode and quiet-window guards. Native systemd
queries run in an independent observer with a750ms subprocess deadline and
1.25s proof freshness, so DBus cannot block the resource sampling loop. Its exact
root-owned systemctl fork remains included in RSS/swap accounting. Compression and
archive parts retain verified prefixes for later qualified claims. Source copy
and final mutable scanning may be long on a multi-million-file host; source
tests establish no completion-time guarantee. A timed-out `du` is not capacity
proof. Preserve every unique project, credential and untracked path. Insufficient
capacity is a refusal, not authority to omit unique work.

The reviewed writer plan explicitly lists all package/application writer units
and paths. The parent records original active/inactive states durably before
stopping any unit. Restoration starts only previously active named units; an
active existing timer needs explicit exact stop/restore authority. Tailscale,
SSH, journald, networking and the natural daily timer cannot be stopped through
this adapter. No new timer is enabled or created. Package locks and dpkg status
proof cover online OS capture. Root-parent pre-mask metadata for dev/proc/sys/run/
tmp preserves original mode, UID/GID, nsmtime and ACL/xattrs in private staging,
including sticky1777. Runtime directory contents remain declared exclusions.

This is application-quiesced file-level recovery with recorded infrastructure
capture windows; it is not a globally atomic live-host snapshot. Full `/etc`,
`/var`, `/home`, `/root`, `/srv`, `/opt`, `/usr/local` plus all declared writer
paths are refreshed. Other online OS trees need explicit package/writer scope
evidence. Boot content must remain unchanged across its capture window.

The stop/reconcile path restores owned policy60 first, then proves no untrusted
processes remain, quarantines only the operation credential copy, proves the
owned image loop terminal and restores original writers. Completion must assert
`owned_loop_terminal` and `writers_restored`; otherwise the native claim remains
retained. Ambiguous or foreign loops are never detached. The optional callback
shares the incumbent40s callback allocation: at most four intents, nonblocking
locks and4.25s monotonic effect budget, inside the external5s timeout. Slow I/O
can interrupt a pass; preserve intents and retry through reviewed owner recovery,
without erasing custody. No new recovery timer is created.

For upload, the owner stages a root:pi0440 operation copy at fixed
`HANDOFF/OPERATION32/credentials-copy.conf` using the qualified incumbent
credential reader. Keep the original credential and its actual owner/mode
unchanged. The upload worker runs as Pi with NNP, all capabilities dropped,
private PID/mount namespaces, readonly exports and only its private upload
scratch writable. Its sealed context binds deadline, destination, credential
and upload plan. Only `system-images/sets/SHA/...` and
`system-images/catalogs/SHA.json` paths are permitted. Existing bytes require
full SHA readback; differing objects fail and are never replaced. The final
catalog is published last after every object passes complete readback.

## Keyless recovery and acceptance

### Guarded cold download, restore and rejoin

Use a separate NEW cold workspace. Its protected input
`/var/lib/ar-local-system-recovery-inputs/COLDWORKSPACE32/cold-plan.json` has
exactly `schema: ar-local-system-cold-plan-v1`, `raw_catalog_sha256`,
`raw_catalog_bytes`, `image_catalog_sha256` and `image_catalog_bytes`.
The operator obtains these identities from the separately accepted raw/image
publication evidence; a Pi fetch result cannot choose its own accepted catalog.
Preparation binds the actual qualified incumbent zstandard vendor file hashes,
without changing or reinstalling that raw producer.

```text
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/prepare.py fetch FETCH32 COLDWORKSPACE32 ACCEPTED-PROBE32
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/start.py FETCH32
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/prepare.py restore RESTORE32 COLDWORKSPACE32 ACCEPTED-PROBE32 FETCH32
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/start.py RESTORE32
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/prepare.py rejoin REJOIN32 COLDWORKSPACE32 ACCEPTED-PROBE32 RESTORE32
/usr/bin/python3 -I -S -B /usr/local/lib/ar-local-system-recovery/start.py REJOIN32
```

These are sequential independent host queue claims, each requiring the previous
actual root completion, same source/runtime/plan identity, resource acceptance,
policy60, writer/loop cleanup and privileged stop proof. Do not submit the next
phase while its predecessor is running or uncertain. Each uses the existing
whole-cgroup640MiB/zero-swap-out guard and independent policy restoration.

Fetch has specific read authority, an operation credential COPY and a Pi UID,
NNP, zero-capability child. Only fixed content-addressed raw/image paths can be
read. No Drive write verb is exposed by this phase. Verified complete objects
can resume under a fresh fetch nonce; differing objects and failed partials are
preserved. The root finalizer quarantines the credential copy before acceptance.
After successful fetch cleanup, the next root phase seals the derived mirror
under root ownership and repeats every catalog/object hash before trusting it.
Restore runs as root with all capabilities dropped and no network or credential,
creates NEW raw/reassembled-image workspaces and verifies real raw/SQLite/frame
contents. Capacity includes the mirror, exact raw restore, sparse image allocation
and later raw insertion; no original or historical backup is deleted for space.

Rejoin uses the fixed owned-loop namespace and only the new regular image file.
It first proves the complete unmodified OS plus exact raw files. Because capture
occurs inside a running guard, the captured image contains an active queue/native
lease and control intent whose scratch workspace is excluded. Only this NEW
offline image retires that captured custody: owner PID/ticks/boot/job/unit/
invocation and packet/authority/intent/source closure must correlate exactly.
Foreign or ambiguous ownership refuses recovery. Original queue, lease and
nonterminal control/handoff bytes and full metadata are moved into private
`/var/lib/ar-local-recovery-normalization/RECOVERY-SHA/original/`; terminal raw
backup controls remain unchanged. A valid empty v1 queue preserves its sequence.
No captured ACTIVE job receives a fabricated successful runtime completion.

The same journal records original absence of a NEW offline-only
`/etc/sysctl.d/zzzz-ar-local-recovery-swappiness.conf` containing explicit60,
plus hashes of the captured persistent sysctl configurations, fixed service and
boot command line. Conflicting settings, matching globs, later basenames,
unqualified service overrides/drop-ins/credential commands and persistent
`sysctl.extra` credentials refuse normalization. The transient captured `/proc`
value is never boot evidence. Existing source-host files and schedules are
unchanged. This is a structural persistent-policy proof; physical boot remains
`NOT_TESTED`.

Every intentional offline transform, added audit file and explicit policy is
included in a new expected manifest. Complete metadata/content verification,
readonly filesystem checks and owned-loop cleanup run afterwards. Only an
accepted privileged stop publishes `cold-recovery-proof.json` with the bound
raw/image catalog identities, joined image SHA, normalization manifest/receipt
hashes and root cleanup/resource proof. A downloaded component image or Pi
worker verdict alone cannot satisfy full recovery acceptance. Failed new images
remain private evidence and must not be automatically retried or flashed.

Download the image catalog's exact frames and metadata, plus its bound raw
catalog/packs/index. Restore tools are content-addressed and included in the
image object catalog; copy verified tools to their recorded source filenames.
Use the pinned Python/zstandard runtime. `pi_system_image_restore.py` accepts
only a new private workspace and produces ordinary `recovery.img` by verified
ordered decompression. It writes zero regions sparsely on Windows/NTFS and
POSIX, while verifying every logical byte against the global image SHA. Its
decoder enforces128MiB windows, and measured nonzero allocation bounds are
checked against decompressed content. Large empty logical capacity therefore
does not require dense temporary allocation on this PC.

The OS component reserves ext4 capacity/inodes for the external raw layer but
stores no duplicate raw contents. Use the exact-source `data/` output of
`pi_plain_backup_restore.py`; committed SQLite views remain separate. The
`pi_system_image_rejoin.py` backend accepts only fixed isolated `/scratch`,
readonly `/input` and `/restored-raw` views, a new verified reassembled regular
image, and the accepted recovery-set SHA. A reviewed private namespace must
expose only these files, individual approved code/runtime mounts, loop-control
and the same restricted build capabilities. It has no physical disk or resize
argument. The provided `pi_system_image_rejoin_launch.py` constructs that namespace
after independently approved immutable root staging and exact9-file source
approval; use it on the Linux recovery host:

```text
/usr/bin/python3 -I -S -B /PROTECTED/pi_system_image_rejoin_launch.py --image-workspace /NEW-PRIVATE-REASSEMBLER-OUTPUT --metadata /VERIFIED-METADATA --restored-raw /VERIFIED-RAW-RESTORE --source-approval /PROTECTED/rejoin-approval.json --source-approval-sha256 REVIEWED-SOURCE-SHA --recovery-set-sha256 ACCEPTED-RECOVERY-SHA
```

Its wrapper exposes no original Pi filesystem or connected physical media.
It proves the image identity, inserts absent exact raw paths, restores
metadata and verifies the complete joined filesystem, then readonly fsck and
owned-loop cleanup. A failed private rejoin is preserved; never retry against
an ambiguous image or flash any existing media.

Report separately: complete Drive bytes/readback, raw restore proof, OS/boot
restore+metadata proof, full joined recovery proof, structural boot configuration,
and physical `boot_test: NOT_TESTED` until an actual approved boot occurs. An OS
component with `raw_restore_required:true` cannot alone satisfy complete recovery
acceptance. Connected historical SD/USB media must remain untouched.

The owner's distinct conversational codephrase authorizes one presented scoped
high-risk operation, separate from OS authentication. Initial registration is
not operation approval. Show the actual command, exact target disk, verified
Drive receipts and recovery plan before requesting it; preserve only its private
registered hash, never the phrase itself. Destructive data actions require that
fresh authorization regardless of UID. No sudo password belongs in chat.
