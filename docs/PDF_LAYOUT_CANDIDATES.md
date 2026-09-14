# Private PDF geometry candidates

This optional offline builder preserves pypdf 6.10.0 geometry observations beside
an existing immutable PDF/text extraction. It does not modify the extractor,
store, clauses, graph, revisions, queue, worker, public schemas or app. It makes
no network request, installs nothing and executes no PDF action or OCR engine.
It is not connected to an ingest job or a timer. No Pi or backup operation is
part of this slice. The user's Google Drive write prohibition remains in force;
local protocol tests do not prove a live backup hold is installed.

## Calling contract

`cdr_terms.pdf_layout.build_pdf_layout` accepts PDF bytes, a `RetainedExtraction`,
a new private output directory, and optionally ordered unique physical page
numbers and lower `LayoutLimits`. The returned object is the private manifest.
Use an external isolated process with a 120-second timeout. The operation uses
one shared cooperative deadline capped at 105 seconds, including input binding,
parser callbacks, candidate discovery, output verification and seal preparation.

The retained record carries document ID/version ID, PDF SHA-256, extraction ID,
extractor version, text, text SHA-256, status and coverage. Before output, the
builder checks exact PDF/text bytes, the existing store's document-version and
extraction digest formulas, and all retained page-span hashes and offsets.
The document ID is a caller-supplied retained identity; these checks do not
independently establish an acquisition URL, registration in a database or legal
applicability. The caller must supply the reviewed retained source/extraction
pair. No document or extraction registration is performed here. Empty/failed
parent extraction states remain possible and do not authorize complete evidence.

Existing page-span separators and identities are preserved. Retained metadata is
strictly admitted, including the existing optional annotation-scan status. An
unknown future span structure is refused for review. The source, parent and
policy are checked again before sealing. No new dates or applicability are
inferred, and no prior extraction receipt is rewritten or resealed.

## What a locator means

Page ordinals are physical, one based. MediaBox, CropBox, Rotate and UserUnit are
retained with raw pypdf text-callback ordinals, event order, text, CM/TM matrices,
font name and size. Empty and duplicate callbacks remain separate. Finite numeric
observations are decimal strings derived from parsed numbers; they are not
original PDF number tokens or financial quantities. Invalid geometry is null and
explicitly flagged while text is retained where possible.

These locators are parser callback observations. They are not original PDF byte
or object offsets, glyph bounding boxes, visual reading order, cell boundaries
or exact canonical-text spans. Forms and other extraction behavior can duplicate
callbacks or produce text in a different order from `extract_text`'s return
value. `source_text_span` is always null and alignment stays unverified. No
repeated-string first-match alignment or silent deduplication is performed.

A bounded operator allowlist retains path/matrix/painting observations. Forms,
clipping, curves, shading, external graphics state and inline images receive
explicit unsupported-operation flags. Arbitrary operator operands, PDF objects,
embedded programs/actions and resource dictionaries are not serialized. Counts
identify observed but unretained nongeometry operator callbacks. Geometry is not
normalized to a universal coordinate system; transforms, clipping, form scope,
font metrics and page rotation still need review.

## Candidates and unknowns

Four retained line/rectangle operators plus nonempty text create one table-review
candidate pointing to those four observations. This deliberately weak pointer
can identify a ruled contents page or decoration as well as a possible table.
It supplies no cell values, boundaries or semantic grouping. An asterisk, dagger
or double-dagger at the start of a text callback creates a footnote-review
candidate. Font size alone creates none. A marker may belong to ordinary body
text; its association remains null. No heading, footer or definition is silently
promoted to a footnote or incorporated-reference graph edge.

Zero candidates means the policy detected none. It does not mean the page has
no table or footnote. Page text visibility is reported separately from geometry
status. No observed text requires nontext review; incomplete or omitted text is
explicit. No page is automatically declared blank or in need of OCR. The
retained Bank of us page 43 artwork disposition is sample-specific human review,
not a reusable classifier. All manifests remain `partial`; OCR is not performed,
table structure and footnote associations remain unreviewed.

## Limits and interruption

Default ceilings are 16 MiB PDF bytes, 512 physical pages, 100,000 characters per
page and 2,000,000 document characters, 20,000 text callbacks per page/100,000
total, 50,000 operator callbacks per page/250,000 total, 16,000 characters per
callback, 1 MiB JSON per page/16 MiB total written output, and 128 candidate
regions per page/1,024 total. Text callback character accounting is conservative
and includes duplicates; it can stop before the canonical-text character limit.
Only lower positive integer limits are accepted.

Oversized text callbacks are omitted with ordinal, size and reason, never
truncated into apparently complete source text. Page-level limits retain prior
observations and allow later pages where document budgets permit. Unknown
remaining callbacks, omitted candidates and unprocessed page ranges are explicit.
The builder does not traverse all remaining pages merely to count omissions.
One unreadable page does not erase valid siblings. Insufficient room for the
manifest, a deadline or a write error leaves unsealed private artifacts and
raises; it never gets a fresh budget just to claim completion.

The parser, JSON encoder and OS calls cannot be preempted within Python. The
byte/callback ceilings and external process timeout are required together.
These local bounds are not Pi memory, priority, swap/PSI or natural-schedule
acceptance, and no worker resource limits are changed by this builder.

## Files and final visibility

The output directory must be new and private; reuse, cleanup and automatic resume
are refused. Parent symlink/reparse paths are refused. The builder receives bytes,
so the caller is responsible for keeping the output directory separate from
immutable source directories. Pages are create-only `page-NNNN.json` files. The
manifest binds PDF, retained extraction/text/spans, actual parser version,
policy/limits, reviewed module/schema hashes and every page artifact hash.

Each file is flushed, fsynced and read back. All page identities and hashes are
rechecked before final sealing. The manifest first becomes a create-only
`manifest.pending.json`; completed flush/fsync/close/readback and identity checks
must pass under the same deadline before a no-replace hardlink exposes
`manifest.json`. The pending link is retained on success and failure. Collisions,
unknown files and replacements are preserved. No rollback unlink occurs.

There is no claim of a transaction across arbitrary namespace mutation, an
arbitrarily blocked final hardlink, or directory-entry durability after power
loss. The final hardlink is the visibility point and no fallible work follows it.
A pending file alone never constitutes a completed sidecar. A separate reviewer
must verify the manifest and all bound pages before using private candidates.

## Verification and acceptance gates

Run the isolated repository Python environment with:

```text
python -m pytest tests/test_cdr_terms_pdf_layout.py -q
```

The generated PDFs and fault injections test protocol/geometry behavior only;
they are not bank data. Source-policy acceptance uses the retained current
44-page Bank of us document, SHA-256
`ea7c8ddff603d8c2f1bc59ebee1b6d91494df00c108b4df88a29c5fbc6091974`,
and retained text SHA-256
`bc9f29f5cba6ec413bd27c470af8849d6501e7b66be75d1329bd30d96ac0aae2`.
Development pages are 3 and 8. Policy-frozen holdouts are 5, 35 and 43. Record
separate pre/post source identities, page-span/callback invariants, parser/policy
hashes, timing, memory and output sizes. Full source bytes remain private.

Protocol review precedes a separately approved real-source canary. These pages
do not supply a verified complex multicolumn pricing table, positive footnote
association, OCR benchmark or catalogue-wide legal applicability. Those gates,
independent real-source review, runtime integration and full legal-evidence
coverage remain open. No source page test can mark all product terms complete.
