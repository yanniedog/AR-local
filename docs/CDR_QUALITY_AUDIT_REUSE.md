# Reusing completed protected source audits

A failed or interrupted canary can contain completed per-observation source
audits. Its resource/canary result remains failed. Reusing these calculations
does not accept the old run, waive a resource guard, or authorize deployment.
The new canary still runs the full test suite, all current-day and changed source
audits, every ledger/log check, candidate payload build and reconciliation, and
the protected-data/code/resource guards.

The operator may seal a **closed** protected operation only while its original
candidate checkout remains clean at the exact original commit. Preserve that
checkout until sealing has completed. This is an explicit provenance attestation
about a locally controlled operation, not a signature or a way to trust an
arbitrary downloaded cache. The original complete JUnit, resource receipt and
service log are copied and hash-bound; a FAIL receipt stays FAIL. The resource
receipt must identify this exact original worker and have `group_clean=true`.
The same attestation requires that the original Python interpreter, SQLite and
validation packages have not changed since that run. The old resource receipt
did not record package versions: the seal explicitly labels its runtime identity
as **measured at sealing**, under this unchanged-runtime attestation. Do not use
an old cache after an untracked runtime change; run the full audit instead.

Use the newly reviewed helper with the original checkout and operation paths:

```sh
/usr/bin/python3 -B /path/to/new-candidate/cdr_quality_cache.py \
  --source /path/to/original-clean-candidate \
  --operation /path/to/original-closed-operation \
  --output /path/to/new-sealed-cache \
  --expected-commit ORIGINAL_40_CHARACTER_COMMIT \
  --attest-closed-protected-run
```

The destination must be new and separate from the original checkout/operation.
The command reads the original index through the existing private SQLite
recovery helper, then uses SQLite backup to produce a standalone snapshot with
committed WAL content. It never opens historical source databases for writes.
Incomplete, corrupt or older-version result rows are excluded. It verifies the
full import closure of the unchanged source auditor against original Git blobs,
including accounting, category filters, SQLite recovery and contract schema.
Python/SQLite/jsonschema runtime identities are also bound.

Record the returned manifest path and SHA256 independently. After updating to
the newly reviewed exact main commit, add these arguments to the usual protected
canary command, using a new operation directory:

```sh
--verified-cache /path/to/new-sealed-cache/manifest.json \
--verified-cache-sha256 RETURNED_64_CHARACTER_SHA256
```

The canary mounts the sealed cache read-only. Before and after using it, the
auditor verifies the manifest and every sealed file against the pinned hashes.
Each historical candidate is freshly hashed across **all** source artifacts,
including `banks.json`, database bytes and retained journals. The current
contract/ledger and date/key/generation identities must match. Source stat
identity is checked before and after that rehash. Different content or an
incomplete cache result runs the full source audit; current-day sources always
run it. Changes to any audit dependency or runtime reject the whole import.

Reports retain the original `verified_at` and disclose a separate
`cache_reuse.content_verified_at`, origin commit and seal digest. All historical
findings remain in the new report. `--verified-cache` requires `--scrub`; it
cannot enable ordinary stat-only cache reuse. A missing historical source is
still reported even when its only earlier record is in the sealed import.

This avoids repeated SQLite integrity and JSON/accounting scans for unchanged
history. It still reads every retained artifact byte; it makes no promise about
elapsed time or production acceptance until the new protected run completes.
