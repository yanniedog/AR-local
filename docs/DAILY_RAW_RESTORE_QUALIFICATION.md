# Daily raw archive restore qualification

Progressive implementation handoff, 2026-11-13. Owner: coverage worker; root owns integration/runtime approval. No Pi action, remote download or production restore has occurred.

## Missing route and evidence

`pi_daily_cdr_day_archive.py` creates `MANIFEST.json` followed by regular files in a single checksummed zstd/PAX tar. Each manifest file binds logical path, SHA256, size, mode, UID/GID and nanosecond mtime. Generation-specific `raw-progress.jsonl` PASS rows separately bind date, generation, source fingerprint, exact remote object, compressed bytes and hash. Upload read-back proves compressed bytes, not independent restoration or SQLite semantics. Plain-backup recovery uses a different catalog/pack format.

## Implementation boundary

New standalone `pi_daily_raw_restore.py` reads an already downloaded local archive plus an exact retained progress row and its independently supplied SHA256. Explicit generation selection is mandatory. It creates a new private workspace outside production roots, preserves inputs, streams bounded decompression/extraction, rejects unsafe/duplicate/link/device entries, reconciles manifest/member metadata and hashes, and emits an independent receipt. It does not contact Drive or modify selection, ingest, archive progress, production databases or services.

SQLite originals and sidecars remain exact extracted evidence. Separate private copies permit native WAL/rollback recovery; committed views undergo integrity and foreign-key checks with row inventories. A successful receipt qualifies only the captured generation, not missing upstream data, an entire historical series, system recovery or physical boot.

## Invocation and output

```sh
python pi_daily_raw_restore.py --archive /absolute/download/DATE.tar.zst --receipt /absolute/evidence/selected-progress-row.json --receipt-sha256 RECEIPT_SHA256 --generation-id obs-DATE-GENERATION --workspace /var/tmp/daily-raw-restore-NEW
```

Use the exact remote filename from the selected receipt, including its generation suffix when present. The receipt is one retained `raw-progress.jsonl` JSON row, not a rewritten upload success assertion. Bind its exact bytes with an independently recorded SHA256. This tool never downloads. The runtime owner must separately authorize copy-only read-back to new scratch through the existing approved transport/configuration.

Workspace must not exist and its parent must already exist. Every `/srv/ar-local` path and production archive/backup/control root is forbidden. Use new private `/var/tmp` scratch on Linux, or a canonical absolute new Windows directory. POSIX0700 or a protected Windows user/SYSTEM DACL is applied. Original tar metadata is verified and retained in `MANIFEST.json`; extracted file permissions stay private instead of applying source ownership or setuid bits.

- `exact/`: byte-identical archive members, never opened by SQLite.
- `sqlite-working/`: independent copies, including captured journals; only these undergo native recovery.
- `committed/`: SQLite backup snapshots containing committed journal state.
- `restore-result.json`: PASS/FAIL, generation/object/receipt/manifest hashes, file counts, byte counts and per-database integrity/FK/table counts. Failures preserve scratch evidence.
- Matching `data/state/export-contracts-v2/DATE/GENERATION.json`, when present, is fully validated by the existing contract loader and crosschecked against date/generation. Absence is explicitly reported; generation remains bound only through retained receipt plus manifest fingerprint.

Defaults: compressed16GiB, extracted64GiB, manifest256MiB,500000files,3600seconds, free-space floor1GiB. CLI `--max-archive-bytes`, `--max-unpacked-bytes`, `--max-manifest-bytes`, `--max-files`, `--max-seconds`, `--max-free-space-floor` set explicit integer budgets. Zstd window128MiB and PAX16KiB limits reuse reviewed restore guards. Manifest records stream into an on-disk index; casefold collisions require the independently verified case-sensitive workspace described below. SQLite inventory is limited to10000databases,100000tables across all databases,4096-byte names and8MiB cumulative results, checked before accumulating table mappings. WAL header/frame checksums are verified; recycled old-salt tail is preserved and reported rather than counted as replayed committed data. Truncated or corrupt current WAL frames fail qualification.

Time and disk guards are cooperative. Filesystem calls that never return need the existing external supervisor/timeout; this source does not claim a hard RSS or kernel I/O deadline. SQLite copies and committed views consume additional disk and remain subject to the free-space floor.

## Verification evidence

Tests build the actual producer archive format around unchanged retained Defence Bank CDR details. Generated SQLite fixture rows contain those captured product bytes; archive/generation metadata are explicitly test-only. This is format/security regression evidence, not a production restore receipt. Positive WAL control verifies the exact main database alone has zero rows while its separate committed view has the captured row; originals remain byte-identical. Fault cases cover receipt/generation/fingerprint/hash/size mismatches, duplicate JSON/members, path traversal, absolute names, links/devices, metadata/count/body mismatches, bad SQLite/orphan journals, corrupt WAL, truncated/extra zstd frames, file/byte/manifest/report limits, free-space/deadline and existing scratch protection.

Focused verification: `python -m pytest tests/test_pi_daily_raw_restore.py tests/test_pi_plain_backup_restore.py tests/test_pi_daily_cdr_day_archive.py tests/test_ar_local_restore_integrity.py -q`: **165 passed**, Python3.10.9,21.47seconds through the persistent Windows isolated runner. Python3.11.7's installed pytest/plugin mismatch prevented collection and is not a passing result. Complete JUnit and runner receipt are retained privately under `.work/restore-tests.xml` and isolated run `20261113-224709-1aa0cfe4`. `git diff --check` passed. Exact integrated CI and real downloaded-generation restoration remain pending.

## Outstanding

- Complete independent review and final integrated exact-head CI; root owns integration PR/runtime authorization.
- Locate an actual retained raw archive for independent runtime qualification; do not fabricate a production acceptance receipt.
- Verify exact-head CI and feedback, then use the root/runtime owner's controlled read-back and execution path. Source merge is not restore acceptance.

## Case-distinct Linux paths

The verifier tests the newly created protected workspace and two newly created
descendant directories with exclusive case-variant files. It verifies distinct
file identities and original contents, then removes only identity-matched probe
artifacts. The receipt records each level's actual behavior; operating-system
names or a parent flag alone are insufficient evidence of inheritance.

Only a fully verified case-sensitive workspace may restore distinct paths such
as `AXIS Lending` and `Axis Lending`. Other filesystems retain conservative
case-folded name checks, including directory-prefix aliases with different leaf
filenames. Exact duplicate paths, file/directory conflicts, unsafe paths and links
remain errors. All logical identities stay literal strings rather than
case-folding Windows `Path` keys.

The verifier never changes filesystem settings, requests elevation, renames
original paths or merges provider metadata. On Windows, provisioning a suitable
empty NTFS parent is a separate operator action; every subsequent restore still
proves its own root and descendant behavior. Ambiguous or replaced probe files
fail and are preserved. This support does not establish Linux ownership/mode
restoration, cloud-backup verification or production deployment.
