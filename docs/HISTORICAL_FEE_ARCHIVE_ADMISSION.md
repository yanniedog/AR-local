# Historical fee archive admission — May 22 canary

This offline adapter is limited to the exact retained 2026-05-22 container,
source manifest, backup receipt, embedded export and original public anchor
pinned in `cdr_historical_fee_archive_admission.py`. Other dates and candidate
parent chains are refused. Metadata listings for 84 dates do not admit fees.
The May 13 route and its existing candidate remain separate; the optional shared
budget callbacks preserve its default transformation behavior.

## Review gate

Implementation/protocol review precedes opening the actual retained archive.
No real May 22 archive admission or fee repair is established by protocol tests.
After the operator's root review advances the canary, the manual entry point is:

```text
python -m cdr_historical_fee_archive_candidate --archive-dir <exact-retained-observation-directory> --anchor-dir <original-public-date-directory> --cache <new-private-one-date-cache> --output <new-private-candidate-directory>
```

There is no network, multi-date loop, backup cleanup, database restore/open,
publication, legal applicability or customer-profile operation. Use the locally
installed repository pin `zstandard==0.25.0`; no runtime dependency installation
or network fallback exists. Original archives and snapshots are read-only.

## Evidence and resource boundaries

The reader hashes the entire compressed file while checking one zstd frame, then
streams a complete tar inventory. Duplicate/case-colliding names, traversal,
links, sparse/global/GNU override headers, appended frames/archives, invalid end
records and nonzero padding are rejected. Local PAX timestamps are retained only
as transport metadata; a PAX path must equal the header path. Other PAX variants
are withheld for review rather than guessed. Strict framing may therefore refuse
a legitimate archive variant without proving the underlying evidence corrupt.

Only the selected export, exact public assets and two named JSON controls enter
the private cache. Unselected payloads are traversed and discarded, never
restored or interpreted as SQLite, WAL, SHM, spreadsheets or images. Individual
unselected member hashes are not recomputed; the verified whole-container hash
and complete path/type/size inventory bind their transport identity.

All phases share a 600-second cooperative deadline. Ceilings are 64 MiB
cumulative compressed reads, 256 MiB selected JSON, 512 MiB decoded tar further
restricted to manifest payload + 2 MiB + 64 KiB per listed file plus one, 1,024
headers and 1 MiB total extension metadata. Final archive verification also
counts compressed reads. This is deliberately conservative; later larger dates
need a separate reviewed admission plan. Source JSON does not inherit the older
96 MiB decoder default. Embedded product JSON retains its 16 MiB bound.

Cache/candidate writes share a 512 MiB output budget; decoded candidate details
retain their separate 96 MiB ceiling. Each output volume must have 3 GiB free at
start. Per-file verified reads are bounded and their actual bytes recorded.
Large loops call the shared deadline; standard-library JSON parsing and OS reads
cannot be interrupted within a blocking call. Run behind the isolated process
timeout and measure real canary peak memory, elapsed time and disk use before
claiming runtime acceptance. These offline limits do not change the Pi collector.

## Generation, membership and preservation

The embedded export must explicitly identify the observation date and contain an
aware generation timestamp on that Hobart day. The original public payload may
have been generated later. Backup completion and current admission clocks remain
separate, and legal effective dates stay unknown. All three original public
asset identities must occur uniquely in the same verified archive; named
controls are preserved evidence, not inferred completion authority.

The strict `archive-export-v1.schema.json` provenance variant records container,
manifest, receipt, export member, public inputs, code/policy hashes and exact
generation identities. The source is an embedded export, never reconstructed
HTTP. The existing `source_file` is an unverified string and is not dereferenced.
Every changed fee retains its outer export-string hash/pointer and decoded fee
index with direct or reviewed derived-rule proofs.

The reviewed membership/enrichment functions preserve product/rate/fee order,
multiplicity, historical values, null/false/zero/absent distinctions, conflicts
and nested unknown conditions. The only old-field deletion remains the reviewed
finite exact variable-zero placeholder exception. Core compressed bytes and
optional original asset descriptors are preserved. Typed evidence is not an
executable charging rule or a complete-cost/eligibility claim.

## Cache, interruption and verification

A cache is admitted only after its complete member verification receipt exists.
Both cache and candidate seals first write a create-once `receipt.pending.json`,
flush and fsync it, then check the same deadline after the blocking calls and
verify its bytes and identity. A no-replace hardlink exposes `receipt.json` only
after those checks. Pending files are preserved on failure and success; cache
resume requires the pending and final names to identify the same original file.
Reader policy v2 refuses older seals that lack this proof. No source identity or
previous candidate is retroactively resealed.
Exact sealed-cache reuse rechecks the same whole archive and every selected
cached file, without recopying the export. Partial caches, unknown files or
identity collisions are retained and refused. No cache is automatically deleted.

The final hardlink is the visibility point. No fallible post-commit check can
turn a returned seal into a reported pre-commit failure. This does not guarantee
an arbitrary OS-blocked link finishes within the cooperative deadline or prove
directory-entry durability across sudden power loss. Failed links/collisions
preserve pending evidence and any existing final path; no rollback unlink occurs.

Candidate journals distinguish listed, member-verified and membership-accounted
states. Only the final `receipt.json` seals a candidate as unreviewed. Failures
leave partial outputs and, if the existing operation budget permits, a withheld
disposition. An existing candidate path is never overwritten. Resume uses the
same exact sealed source cache and a separately chosen new candidate path.

Focused verification:

```text
python -m pytest tests/test_cdr_historical_fee_archive.py tests/test_cdr_historical_fee_embedded.py tests/test_cdr_historical_fee_repair.py -q
```

Synthetic tar/schema fixtures test protocol boundaries only. Compatibility uses
the checked-in hash-bound real May 13 excerpt, without relabelling its admission
date. Real May 22 fee counts and all-field/source-pointer reconstruction remain
pending the separate canary and independent review. No prior receipt is resealed.
