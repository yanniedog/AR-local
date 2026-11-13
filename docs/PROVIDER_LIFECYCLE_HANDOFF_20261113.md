# Provider participation lifecycle repair — 2026-11-13

## Verified cause and evidence

The hosted read-only coverage report `coverage-live-43412528732.log` reports
Wise population absence every November 1–13. This does not mean 115 current
registered providers include Wise: today's official register has 390 brands,
115 banking brands, and no Wise entry.

At 2026-11-13T10:58:01Z the former registered public endpoint
`https://au-cdrbanking-pub.wise.com/cds-au/v1/banking/products` returned HTTP 422
with CDR JSON `GeneralError/Expected`, title `Service No Longer Available`,
explicitly stating that the data holder ceased CDR participation. A second
request using the ingester's preferred x-v=6/x-min-v=1 produced identical bytes
at 10:58:43Z. Neither request used authentication or category filters; this is
not evidence of an auth, pagination, product-category or schema negotiation
problem. Both used an honest AR-local diagnostic User-Agent.

Raw provider body: SHA256
`b353d4574d1eb5a1df3c6dea46ff875585a329778af985d499a336e2953f4b96` (210 bytes).
Current official register body: SHA256
`43e1fdbc0ffb9d37775592dbbb31201c175cb6fde88eeb6c6fe887dadc493e3a` (199565 bytes).
Prior official October 14 register already retained in
`tests/fixtures/public_rates/cdr-register-20261014.json`: SHA256
`af0565aff5261fb21fffed4b8872714bf13a325a2d1a5ace2781e0e6428ebcf5` (185824 bytes),
Wise brand UUID `9c8c5e8d-5cb9-ec11-a82d-000d3a8830d6`, ABN `38616463855`, same
public endpoint. The old Wise CDR-policy page now returns 404; this is
corroboration only. Search snippets/social reports do not establish an effective
withdrawal date and are not implementation authority.

## Existing behavior and intended fix

`cdr_population_identity.population_finding_resolved` only clears an absence
after the same provider returns a complete nonempty index. Thus a confirmed CDR
departure can remain `UNVERIFIED_SOURCE_ABSENCE` forever. Preserve that fail-closed
behavior for unexplained absences. Add a generic, independently validated public
evidence adapter for explicit cessation, tied to the prior registered identity,
official current register absence, observed date and immutable response bytes.

Do not infer product withdrawal, create `product_removed` events, refill today's
products with historical rows, backdate the observation, or silently exclude a
brand. Reappearance in the current register defeats the cessation disposition.
Keep the evidence and lifecycle explanation in the observation report/contract.
No Pi changes or live deployment have been performed by this worktree.

## Progress / next worker

Root authorized source implementation and a separate PR, with root owning merge.
Branch `agent/provider-lifecycle-20261113`, based on main `6143102` (PR #1130).
The publication repair PR #1131 was independently synchronized and pushed as
`5c46171ccb288266708a0f857a1d4155d93fc782`; its fresh CI is separate.
Implemented offline generic evidence adapter in `cdr_provider_participation_evidence.py`
and `cdr_population_lifecycle.py`. No bank name exclusion exists in code. The
curated bundle contains unchanged official prior/current register responses and
the provider's explicit cessation response, with source URLs/timestamps/statuses,
byte counts and SHA256. Register capture time is its local capture-write time;
the provider response time is recorded immediately after the request completed.

Current applicability requires a complete unfiltered provider set reconciled to
the raw official summary, a successful current-day journal event and matching
body hash. Only the initial 64 register events are inspected, each <=64KiB;
source bodies <=1MiB, manifest <=64KiB and <=16 evidence records. The parser
accepts registered UUIDs and interim IDs in the summary. Any same UUID, ABN, ACN,
brand name or endpoint origin in ANY current industry revokes the disposition.
Unknown/malformed response wording never establishes cessation. This narrow
adapter can be extended after reviewing a newly captured authoritative format.

Each applicable export preserves all three evidence bodies as immutable
`provider-participation-evidence/<sha256>.json` artifacts. The population report
and contract coverage retain `provider_participation_ceased` receipts and their
original uncertainty. The next observation reevaluates that original hold;
missing/filtered/stale discovery or reappearance restores uncertainty. No older
observation is edited. Applicability starts November 13, the evidence date;
November 1–12 remain historically unknown. No product withdrawal is asserted.

Source integration: `write_sanity_report` classifies after the normal historical
comparison; `_coverage` independently revalidates cessation proof before sealing;
`finalized_population_report` carries the original unresolved finding forward for
daily reevaluation. All copied bytes are included in the normal artifact inventory
and daily archive. Runtime/archive acceptance still requires the controlled Pi
workflow, not this source assertion.

Final focused regression run: 163 passed, 1 skipped in 18.78s; complete JUnit and
isolated runner completion recorded. Skip is the existing opt-in retained
real-export test. Independent review pending. A new invalid-status regression
also proves that an UNKNOWN report cannot smuggle a cessation disposition.
Future changes to the curated evidence directory trigger `pi:needs-deploy`.
Mobile projection is required before integration completion: provider, observed
date, disposition and explicit false product-withdrawal flag only. This awaits
the publication repair PR #1131 landing on main; do not duplicate that PR's commits.

Independent review found two boundary issues, now fixed: declared register
`totalRecords` must be an exact integer matching the retained rows (missing meta
remains supported), and finalization cannot recreate missing captured evidence.
It only reads/verifies already archived proof; missing/corrupt files fail.
The extended population/finalization/deployment-path suite passed 259 tests with
one existing opt-in skip; the later focused lifecycle run passed all 28 tests.
Committed Git blobs were independently hashed against every raw-source digest;
`.gitattributes` preserves literal CRLF bytes on Linux and Windows.

PR #1135 review additionally required committed-journal binding. The reader now
checks promoted attempt count/head against `current.json`, refuses events beyond
that committed sequence, and verifies each inspected key pointer and the head
when reached. Added uncommitted-event, missing-key and mismatched-head controls.
The public projection helper is implemented separately and rejects malformed
withdrawal claims; transport URLs and nested historical identities never pass.
Its call sites still await #1131 integration. Latest focused lifecycle/projection
run: 35 passed in 2.79s. Draft remains intentionally unready until integration.
