# Legacy historical candidate v1

## Status

This is a dormant reconstruction and acceptance contract. Its current private
acceptance status is `BLOCKED_PRESERVATION_DRIFT`. It cannot publish,
promote, replace an operational payload, update a rolling pointer, contact the
Pi, or contact any CDR or GitHub endpoint. Its only input is the explicitly
named, independently preserved snapshot supplied by an authorized operator.

All 92 retained observations are `partial` and `promotion_eligible=false`.
There is no “complete” historical observation in this contract. The explicit
blockers are missing official register evidence, missing complete
provider/attempt populations, known semantic ambiguity, and two irreparable
gaps.

## Locked evidence

`contracts/historical/corpus-lock-v1.json` binds:

- snapshot `20260814T202526AEST-pi5-3dc9b4677`;
- inventory `manifests/preservation-file-inventory.jsonl`, 744,155 bytes,
  SHA-256 `0482f54a47536a0971d061a13a7549ffe0a22094eb13c6bd961d714354221325`;
- 1,932 critical files and 25,586,769,110 bytes;
- an immutable critical-evidence partition of 1,756 files and 21,280,983,214
  bytes;
- the exact date-bound candidate-input union of 1,495 files and
  21,179,877,992 bytes;
- a non-candidate transient SQLite partition of 88 `-shm` files/9,797,632
  bytes and 88 `-wal` files/4,295,988,264 bytes;
- 230,852 products, 1,319,589 rates, and 8,077 serialized failures;
- 57 additive-ledger `CHANGED` dates, retaining 568 original files and
  18,177,646,221 bytes while separately inventorying 688 additions and
  147,127,281 bytes;
- 763 value-conflicting rate-semantic groups containing 1,876 rows, plus 95
  same-value duplicate groups containing 190 rows (2,066 nonunique rows total);
- 460 term-deposit rows whose legacy 12-month fallback has no term evidence.

The loader verifies every one of the ten manifest descriptors in
`docs/preservation/PRESERVATION_EVIDENCE_V1.json` before reading the inventory
or any source artifact. It then validates strict duplicate-free JSONL, portable
unique case-folded paths, the critical source mapping, and exact locked totals.
Symlinks, junctions, reparse points, absolute paths, traversal, and overlapping
source/output trees fail closed.

The manifest inventory itself remains byte-valid, but a full rehash on
2026-08-15 found two primary-snapshot WAL-index files whose length remained
98,304 bytes while their contents changed:

- `pi/data/runs/2026-05-23/_exports/local-cdr.sqlite-shm`: expected
  `404a2ce5ef441b741c2d61d115a9e2e258ec18535b96ea8baf77168d78064b96`,
  observed
  `92fd64bdfe923ed239609cc59f439ff94bbbe700f039205bce409681f49c0f87`;
- `pi/data/runs/2026-05-24/_exports/local-cdr.sqlite-shm`: expected
  `f6400fdd5f10ae1f497cae2f17c32c14f00f723a2e35cc06bc2896f606419ee2`,
  observed
  `b098009c22153fea8a395531b53f08fedc0d884d08f1a742ce7bf63ac44a6c80`.

The exact expected bytes still exist, untouched, in the restore root explicitly
recorded by `manifests/restore-copy-summary.json`. A read-only census confirmed
that restore retains all 1,932 critical files/25,586,769,110 bytes exactly, but
it is not a selectable candidate source because it is not a complete copy of
the ten-manifest control plane: six descriptors match, two differ, and two are
absent. Specifically, `pi-critical-verification.json` differs at the same 413
bytes (`d47d86b9587713a27dc8bceec753117848d4ebbb10abc63cc1547eade9fc9c1a`
expected,
`1d8f81d2ad4516de3a7e730c2d095da807c53810ff235a6cc5e4bbd07ba764d7`
present), the restore inventory is 652,910 bytes/
`678358733f9200bb1749b5be602d0d8ac3ee28e3c9b24ff822a4e2ea23bda7b2`
rather than 744,155 bytes/
`0482f54a47536a0971d061a13a7549ffe0a22094eb13c6bd961d714354221325`, and
`preservation-gate-status-20260814.json` plus `restore-copy-summary.json` are
absent. This contract does not copy, restore, normalize, or overwrite either
file. The drift was traced to a
read-only-intended forensic connection that used SQLite `mode=ro` without
`immutable=1`; SQLite permits its transient shared WAL index to change in that
mode. Future forensic work must query an isolated copy or use
`mode=ro&immutable=1` plus `PRAGMA query_only=ON`. The preservation tree should
also be OS-write-protected before any further query work.

## Dates, gaps, variants, and revisions

Coordinates are `{date, variant_ordinal, revision_ordinal}` and are one-based.
Candidate IDs are deterministic:

`hist-YYYY-MM-DD-v####-r####-<12 hex identity prefix>`

The history index contains exactly 92 observation dates and these separate gap
records:

- 2026-05-14: `known_gap`; no run exists and legacy code records the gap.
- 2026-06-26: `unclassified_gap`; no run, marker, or dated release survives.

No empty observation is created for either gap.

The minimum 95 candidate coordinates are:

- one root projection for each retained date;
- 2026-05-19 v0001/r0001 for the 1,632-product, 10,554-rate export projection;
- 2026-05-19 v0002/r0001 for the parallel 1,618-product, 10,514-rate
  SQLite/dashboard/payload projection;
- 2026-05-20 v0001/r0001 from the preserved original backup, followed by
  v0001/r0002 as an externally asserted legacy correction;
- the equivalent parent/child pair for 2026-05-26.

Parallel projections are not merged and neither is called a correction.
Correction records bind the exact same-date parent candidate digest and parent
source-manifest digest. The acceptance scan fails if an additional backup or a
new semantically different dashboard projection appears, so the locked minimum
cannot silently truncate a newly discovered variant.

The legacy ledger reports 93 checked date records while the retained run source
contains 92 partitions plus two gaps. The acceptance report records this as a
source-role difference. It never coerces the ledger population into the run
population or invents an observation.

## Data meaning

Rows are compared as canonical multisets. Duplicate rows and their original
indices are retained; provider/product keys are never used as a lossy map.
JSON, workbook, SQLite, and dashboard projections are checked independently.
SQLite main databases are opened with `mode=ro&immutable=1` and
`PRAGMA query_only=ON`; the candidate reader never opens a `-shm` or `-wal`
sidecar as input. Those 176 files remain visible in the locked preservation
inventory and drift report, but never enter a source manifest or candidate.

Financial semantics are conservative:

- comparison, advertised, deposit, lending, and application fields remain
  distinct;
- product rate fractions are not interchanged with percentage-point RBA data;
- mixed-scale and 0.2-to-1 ambiguous product rates have null typed values;
- ongoing or reversion rates are unavailable unless explicit;
- 763 indistinguishable tier groups with different values remain quarantined
  from exact rate history and alerts; they contain 1,876 flattened rows. A
  separate 95 groups/190 rows are same-value duplicates and require
  deterministic duplicate preservation, not value-conflict quarantine. The
  legacy report's 2,066 count is the sum of both nonunique populations;
- of 8,372 legacy 12-month fallbacks, 552 compound ISO terms are exact, 1,564
  structured ranges are derived, 5,796 have text evidence, and 460 serialize a
  null term because no evidence exists;
- transaction, mortgage-offset, term-deposit, business, restricted, and
  unknown products are not confirmed as ordinary Savings;
- missing fee rows mean unknown, not `$0`; missing eligibility means unknown,
  not unrestricted, unchanged, or removed;
- the duplicate 2026-05-31 AMP `AMP_LAND_HL` observation is retained and
  quarantined rather than replaced with an inferred product.

Register, registered-provider, attempted-provider, and attempt populations use
the typed unavailable form:

```json
{"state":"unavailable","value":null,"reason":"the preserved cleaned projection has no complete register/provider/attempt population"}
```

They are never zero.

## Immutable output and recovery

Generated source manifests, candidate manifests, and the history index are
canonical UTF-8 JSON with a final LF. Each filename is the SHA-256 of its exact
bytes. A full bundle is assembled under a deterministic staging digest and
renamed into `bundles/<bundle-sha256>` only after every byte has been
re-verified. Existing identical files make retries idempotent; different bytes
at any create-once location fail closed. Interrupted staging is retained for
verified retry. A failed stage is not a completed candidate bundle.

Tool provenance records the exact Git commit, a platform-independent canonical
runtime contract, and byte/hash descriptors for all five implementation files.
Discovery order is normalized, giving identical bytes on Windows and Linux.

## Verification

Portable committed tests run on Windows and Linux without private data:

```powershell
python -m pytest -q tests/test_cdr_historical_contract.py tests/test_cdr_historical_source.py tests/test_cdr_historical_parity.py tests/test_cdr_historical_candidate.py tests/test_cdr_historical_acceptance.py
```

The private corpus gate is deliberately opt-in and read-only. The operator must
provide the exact snapshot path; the code never searches for or infers it:

```powershell
$env:AR_HISTORICAL_SNAPSHOT = '<explicit verified snapshot path>'
$env:AR_HISTORICAL_TOOL_COMMIT = '<exact 40-character commit>'
python -m pytest -q tests/test_cdr_historical_acceptance.py -k private_all_92
```

The gate first re-hashes the union of the full locked 1,932-file critical
population and all 1,495 date-bound candidate inputs: 2,305 unique files and
25,666,542,785 bytes.
Any mismatch returns `BLOCKED_PRESERVATION_DRIFT` with expected and actual
length/hash, before parity or candidate construction. With an exact source, the
gate then streams one date at a time with one worker, blocks sockets, performs
cross-format row-multiset parity, and verifies the 1,495-file immutable
candidate-input population. Immediately before returning an acceptance result,
it re-hashes the same 2,305-file union and discards the in-memory candidate if
any source byte changed during the run. It emits no snapshot, restore, run,
state, mirror, release, or Pi writes.

The command-line verifier exits successfully only for the fully re-hashed
`accepted_partial_non_promotable` state. A shallow/unverified result or
`BLOCKED_PRESERVATION_DRIFT` is emitted as structured JSON with a nonzero exit
status so automation cannot mistake evidence collection for acceptance.

The current snapshot does not pass that gate and no completed candidate bundle
may be claimed. Passing a future exact-source gate would mean only
`accepted_partial_non_promotable`. Activation would
require a distinct reviewed contract and explicit authorization; neither exists
here.
