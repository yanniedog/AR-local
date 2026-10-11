# Prepared bank history transport

The app's graph path uses `bank_rate_history_ready`, a required producer-compiled
projection of exact rate distributions. Its URL-free namespace is
`{schema_version: 1, file: {name, bytes, sha256, enc?}}`; filenames begin with
`bank-rate-history-ready-`. It uses the same core/date-bound envelope below.

The inner `ar-history-ready-v1` document pins `compiler_sha256` to the reviewed
standalone compiler in `contracts/history_ready/`. The compiler is generated from
the app's exact classification, dated evidence and feature-scope predicates;
Python does not approximate these decisions. Compilation requires Node.js 24 or
newer, which producer CI installs. Compiler pin, semantic validation, processing
budget or runtime failures defer publication explicitly. They never silently
replace ready history with raw history for new clients.

Each section has cohorts keyed by bank, exact structural profile dimensions,
dated-evidence availability, broad availability and the curated feature bitmask.
Cohorts carry sorted date/rate frequency changes. Multiplicity is preserved so
filtered minimum, maximum, mean, median and counts remain exact. Separate product
best-rate spans serve product history. Calendar gaps, source receipts and the
Savings term-deposit quarantine are preserved. Null dimensions remain distinct
from empty strings. Consumers can filter and summarize these small distributions
without reclassifying thousands of products or loading their evidence.

Ready JSON is capped at 4 MiB, its decoded envelope at 2 MiB and its delivered
asset at 1 MiB, including any encryption framing. Packaging reserves room for ready history before
the optional packed raw archive and keeps the unchanged 8 MiB transfer budget.
The full legacy history asset remains independently available for compatibility
and evidence; the raw packed asset remains available when budget permits.

The producer emits `bank_rate_history_catalogue_packed` alongside the unchanged
`bank_rate_history_catalogue`. Neither capability belongs in the legacy eager
`files` list. Existing applications retain the original catalogue; applications
supporting the packed capability select it first.

The new namespace is `{schema_version: 1, file: {name, bytes, sha256, enc?}}`.
The name is `bank-rate-history-catalogue-packed-<date>-<sha12>.json.gz[.enc]`.
The descriptor deliberately contains no URL. Consumers derive the URL from the
validated manifest repository, release tag and filename. This keeps the bundle
hash compatible with older applications, which hash unknown namespaces verbatim,
and preserves the same identity when the revision coordinator retags a release.

The asset uses the existing gzip envelope:

```
{schema_version: 1, run_date, core_sha256,
 catalogue: {sha256, bytes, gzip_base64}}
```

The inner receipt describes the packed JSON bytes, not the expanded catalogue.
The packed document is `{format: "ar-history-dag-v1", root, nodes}`. Nodes are JSON
primitives, `[0, references]` arrays, or `[1, shapeReference, references]` objects.
A shape references an earlier array of unique string keys. References are unsigned
base64 VLQ using `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/`,
five data bits and continuation bit 5, with no separators. All references point
to earlier nodes, and the root is the final node. Nonminimal and truncated VLQ
encodings are invalid. Decoded containers can share immutable child values.

Limits match the application: one million nodes, four million edges, depth 64,
10,000 object fields, 64 MiB of string code units and 128 MiB of logical expansion.
The packed JSON has an additional 10 MiB decoded-byte limit. Both capabilities
count toward the existing 8 MiB overall compressed transfer budget. If the optional
packed projection exceeds its structural, decoded or transport budget, packaging
retains the legacy capability and reports the omission. Malformed data or receipt
failures remain errors; they are not treated as budget omissions.

Both formats retain every observation, source identity and evidence record.
Packing requires a lossless bounded round trip before emitting an asset. Release
inventory, immutable revision upload/readback, local validation, candidate app
proof inventory and mandatory ARE2 transport include the packed asset.

`tests/fixtures/history-dag-v1-interoperability.json` is a small cross-language
codec fixture, including shared values, Unicode and prototype-shaped JSON keys.
The producer tests also use retained real CDR observations. Before runtime
activation, test the complete cold application decode/validate/install path on
the intended device against the few-second processing requirement. Compressed
size and desktop codec timing alone do not establish that acceptance result.

## Runtime activation order

Code merge alone does not activate this capability. Follow the controlled Pi
recovery runbook and latest chronological handoff, preserving the pinned runtime,
Drive write hold and current ownership until the guarded transition is ready.
The current `CDR_QUALITY_PIPELINE.md` authority and latest handoff govern runtime
work. The runbook's Phase B GitHub route requires a configured production
environment and exact canary evidence. The D-027 local sealed activation route
is a separate supported path; an absent GitHub environment does not alone block it.

1. Deploy and verify the reviewed Cloudflare app-data service with the READY and
   packed catalogue filename allowlist before publishing those capabilities.
   Follow `services/app-data/README.md`: retain historical release keys, authenticate
   canonical ARE2 transport, and return exact gzip domain bytes with CORS and no
   Content-Encoding. Existing encrypted releases and older clients remain supported.
   The retained direct GitHub bootstrap is not an active publication dependency.
2. Validate the exact merged producer candidate, including updated consumer app
   proof for the complete declared asset inventory. Admit the controlled Pi transition through
   the shared task queue and production lease, respecting current resource,
   quiet-window, canary, approval and rollback gates. Then activate that exact
   candidate, not a moving branch.
3. Build and publish a new immutable revision from verified existing source
   observations. Preserve historical releases, upload assets before the manifest,
   and authenticate canonical release and Cloudflare readback, envelope/core
   binding, bytes and hashes, selected manifest and rolling index.
4. Measure cold and cached native application processing, including validation and
   installation, against the few-second requirement. Record native and subsequent
   natural-cycle evidence separately from code and publication checks.

Do not create, enable, resume or start scheduled tasks or resume Drive writes.
The local sealed activator stops and then starts previously active watchdog and
runtime-health timers, including on rollback. That restoration is a material
boundary under a no-start instruction: resolve authorization before activation;
do not bypass or alter the guarded procedure. Missing runtime evidence remains
pending.
