# Product document evidence v1

`terms-v1.schema.json` is the additive, public per-product evidence envelope.
Only reviewed `validated` term revisions may appear in it. Stage counts measure
known obligations; a null denominator means completeness is not measurable.
Acquiring every known URL does not prove discovery or interpretation complete.

The immutable identity is SHA-256 of UTF-8 JSON with lexicographically sorted
object keys, no insignificant whitespace, preserved Unicode, finite values,
and `identity_sha256` omitted. Financial quantities in `value` use exact decimal
strings. Zero and false are meaningful; null means unknown. `observed_at` is
when evidence was observed; effective dates require separate source evidence.
Unknown tier/package/cohort applicability must not be treated as universal.

The proposed additive manifest descriptor is `files.terms_index`. It uses the
existing immutable manifest-file contract. Its JSON is `{schema_version: 1,
run_date, products: {product_key: ManifestFile}}`. Each per-product file belongs
to that same immutable release and binds name, URL, byte size and SHA-256.
The producer must not activate this optional asset until consumer acquisition
is shipped and verified. Source-only or terms-only changes require a new payload
revision under the existing per-date revision protocol.

`documents` contains metadata, never archived document bodies. `clauses.text`
contains only source context for promoted facts, at most 2,000 characters per
clause; `excerpt_truncated` distinguishes a shortened excerpt from the full
private clause. Character offsets refer to the retained extraction's Unicode
code points, page numbers are one-based. Raw originals and complete extractions
remain private in the dedicated `cdr_terms` content-addressed archive.

The controller's append-only SQLite records are DocumentVersion, source-bound
SourceClause, ProductApplicability, staged TermRevision, reviewed RuleSet,
TermChange and immutable product publications. Reviews are separate append-only
records. A model worker has no publication method or database credentials; the
runtime controller must enforce this separation with OS permissions.

Unknown/disappeared URLs and failed requests never withdraw clauses or fees.
Removal requires explicit reviewed replacement evidence. A complete acquisition
alone cannot authorize a removal. Revised interpretation of unchanged bytes is
an `extraction_corrected` event, separately from a source amendment.

CalculationReceipt and the executable evaluator remain consumer contracts;
this archive does not certify calculation correctness. Full document discovery,
OCR/layout review, semantic benchmarks, applicability adjudication and automatic
ingest scheduling are separate acceptance gates, not implied by this schema.

## Private controller interface

`python -m cdr_terms --store <private-directory> --help` lists bounded inventory,
archive, fetch, extraction and coverage commands. There is deliberately no
publish command. A retained CDR response with `links.self` is registered as a
`cdr_source` document using its original bytes and capture time; fetch batches
skip that already captured API response. Do not relabel a historical capture as
current. Source timestamps and raw file hashes must come from ingest evidence.

`EvidenceStore(root)` creates a dedicated SQLite database and private `blobs/`
tree. It refuses unrelated existing databases; never supply a source database
directory. The database enables foreign keys, FULL synchronous writes and WAL,
and denies UPDATE/DELETE on evidence tables. It is owned by the controller.
Back up this archive only after the user's Drive hold is explicitly lifted.

`TermsQueue(store).enqueue(extraction_id, context, priority=...)` binds the exact
extraction and context content hash. Context requires `product_keys` and should
also bind observation hashes, canonical registry, extractor/evaluator versions,
and scope evidence. Priority 0 is changed current data, 1 unfinished current,
2 historical. Identical inputs reuse one job without another model call.

`claim(now, lease_seconds=900)` atomically claims the next due job and returns
`lease_id` and `lease_expires_at`. It first records expired running leases as
retry events. The runner supplies that lease to `event(..., lease_id=...)` or
`save_staging(job_id, output, lease_id=...)`. Expired/replaced workers cannot
complete a newer claim. A source change supersedes the old job. Auth/quota
failures use `retry_wait` with an explicit future `retry_after`, or `blocked`;
unchanged completed inputs produce no due work. Runtime systemd locks and
resource controls remain necessary in addition to the database lease.

Historical priority alone is scheduling metadata and never relaxes validation.
Use `enqueue_historical(extraction_id, observation_ids, registry_context=...)`
or the `enqueue-historical` CLI to create an explicit **historical_only** target.
`historical-target-v1.schema.json` pins document and extraction identities, byte
hashes, extractor version, document acquisition time and up to 1,000 retained
source observations. Each observation preserves its source hash, ingest identity,
timestamp and explicitly named `observation_date_utc`; that date is not an AR
local run date or a legal effective date. The target has its own canonical hash.

Historical pins are rebuilt and every source blob checked before claim and
staging, independent of a newer successful version at the same URL. Raw CDR
pins must match the exact observation bytes; other documents must have explicit
source applicability references. This reference is evidence for interpretation,
not certification that every clause applied on the observation date. Current
jobs retain latest-version invalidation. Expired historical leases reject stale
workers just as current leases do.
Latest check selection orders normalized evidence observation timestamps before
insertion sequence. Importing an older retained check cannot replace a newer
source version or make a historical failure appear to be the current fetch state.

Historical model output and controller receipts must preserve the exact
`historical_scope` including target/version/extraction identities and explicit
UTC observation dates. Missing or altered scope is rejected. These results
stay in analysis staging: their context cannot enter `stage_term`, and their
envelope cannot enter current product publication. Historical review and a
separate immutable historical publication contract remain acceptance gates;
retained bytes alone establish neither effective dates nor complete coverage.

The Codex subprocess receives only a private read-only job workspace containing
the pinned extraction/context and `analysis-staging-v1.schema.json`. It does
not receive the controller database, archive, environment credentials or tools
for publication. `save_staging` validates schema, exact quantities, source span
bounds and product scope, then retains output as **staged**. Those mechanical
checks do not verify semantics, complete coverage or eligibility.

Controller review records bind independent source/applicability/value/exception/
effective-date checks by hash. Display-only human-reviewed terms may have null
`rule_set_id`; deterministic reviews require a registered benchmarked pattern.
The existing structured CDR fact/change taxonomy remains authoritative. This
package never generates executable code or discovers new executable patterns.

`build_product_asset` reports gaps and only independently validated terms whose
source documents still match. `publish_product_asset` additionally compares
the expected observation and previous publication identity inside a transaction.
It records a local immutable projection, with no network or release mutation.
The release controller must independently gate and publish a new higher payload
revision; it must never lower anti-rollback pointers to restore older evidence.

## Ingest and collector activation

`AR_LOCAL_TERMS_ROOT` explicitly enables the `cdr_daily` finalization hook. With
that variable absent, the hook creates no files or requests. When enabled, it
archives the complete raw product responses before RAM cleanup and writes one
immutable capture receipt bound to the finalized generation. The archive must
be outside the source runs, raw stage, export and ledger trees. Capture limits
are 10,000 products, 512 MiB and 120 seconds by default; exceeding a bound fails
the whole capture rather than truncating it.

No HTTP or Codex call occurs during ingest. Each unique supporting URL receives
one acquisition request per ingest generation, irrespective of CDR `lastUpdated`
or unchanged product bytes. Shared requests retain every product observation
binding. They become runnable only after the whole generation's capture receipt
is complete. A repeated generation verifies the original archive and reuses its
receipt; a new generation checks its documents again. Same document/extractor/
context content reuses one interpretation job even across ingests.

Capture failure writes a separate `state/terms-capture-receipts` failure record,
preserves the raw stage and leaves the verified rate completion marker unchanged.
The already-finalized/recovered paths retry the capture without rerunning ingest.
The retained stage still needs the existing verified cleanup path after repair;
capture recovery by itself does not delete source staging.

The scheduled resource-controlled collector runs one
`python -m cdr_terms --store <private-directory> acquire-next` child at a time.
No due acquisition means no HTTP and no model call. Requests use recoverable
leases, retain every failed check and retry at bounded future deadlines, with
four attempts before a blocked state. A new natural ingest creates fresh check
requests. The collector queues available extracted text for interpretation;
unsupported PDF/OCR and other extraction failures remain explicit gaps.

The caller must apply the Pi operating window, operation locks, disk reserve
and existing resource supervisor. Keep the acquisition child below 120 seconds
inside its 180-second lease. HTTP defaults cap a document at 16 MiB and 30 seconds,
with five redirects, pinned public DNS, no credentials/proxies and HTTPS only.
PDF parsing still needs the outer resource/deadline limit. The collector's
independence from subscription quota ensures that an interpreter cooldown does
not stop official document acquisition.
