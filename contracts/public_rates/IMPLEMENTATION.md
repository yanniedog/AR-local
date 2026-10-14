# Public pricing producer implementation and validation ledger

The producer extension is additive and disabled by default. Original public
CDR response values and pointers are captured before lossy cleaning in
`public_pricing_source_json`, retained by an additive `bank_products` column.
`bank_rates.public_rate_disposition` preserves source-informed legacy safety.
Existing populated history is not reset by either column addition. Source and
pricing observations remain in the dedicated terms evidence database.

`cdr_domain/public_pricing*.py` defines explicit units, roles, tri-state
predicates, bounded declarative formulas, exact arithmetic and the shared
resolver. `cdr_public_rates_cdr.py` compiles all three sections;
`cdr_public_rates_conditions.py`, `cdr_public_rates_fees.py` and
`cdr_public_rates_metadata.py` retain applicability, supported public charges,
payment timing and maturity boundaries. Unknown source types, non-string
rate scalars, undisclosed assessment relationships and unfamiliar material
pricing prose remain unresolved. Adjustments alone and comparison rates cannot
be amortisation inputs. Source prices and array positions are not identities.

`app_payload_public_rates.py` writes the detached index and bounded shards,
deduplicates fees, binds the selected ingest/core/details hashes, verifies bytes
and prevents captured candidate data from enabling a programme. Iterator,
revision, archive retagging, bundle identity and network-budget integrations
include the capability. It adds no startup-core fields. Source validators and
immutable candidate filenames retain their exact-byte hashes.

The full current inventory cannot fit hashed programme IDs and repeated product
routes in a 256 KiB index. The index now carries provider/category coverage and
shard routing; full canonical product records are in discovery shards. Disabled
programmes remain in the chunked immutable internal candidate/evidence archive,
while discovery preserves their count, reasons, public source and check dates.
Only reviewed executable programmes and their evidence enter pricing shards.

The retained public inventory sizing fixture contains 2,934 product identities
and 16,396 published legacy-row counts. It is marked transport-only and supplies
no pricing evidence. Its catalogue index measured 9,477 bytes gzip / 262,453
decoded; two discovery shards brought the complete catalogue to 1,942,736
decoded bytes. All products and suppressed-count controls survived readback.
Generic CDR percentage-style values such as `6.84` in a fraction field are
unsupported rather than converted by magnitude. Invalid adjustments cannot
regain a formula during base binding. CDR bonus and discount amounts must be
non-negative, as defined in the [official rate types](https://consumerdatastandardsaustralia.github.io/standards/#product-lending-rate-types).
Malformed negative adjustments remain unresolved; reviewed signed margins use
their explicit role in the general pricing model.

The structured compiler bounds each product to 512 lending/deposit rates, 256
fees, 64 constraints and eligibility declarations, and 128 tiers and
applicability conditions per rate before grouping. Over-budget or malformed
structures retain product discovery and public source dates with an explicit
unresolved reason. Product-wide fees are compiled once, with unchanged
product-scoped evidence and identities. The retained NAB capture's 172 source
rate records remain supported. A disclosed savings base related to bonus or
introductory pricing is retained as a reference component; its standalone
programme has no payable formula. Base-only products remain supported.
Programme `materialFootnotes` retains verbatim sorted public rate notes,
including asymmetric minimum/maximum disclosures and the base notes used in
an adjusted rate. Material changes stay bound by the structure review hash;
legitimate range grouping and stable offer identity remain intact. Oversized
notes and programme groups retain unresolved discovery instead of truncating
material evidence. The app retains this field without rendering marketing text.
Pricing source traversal is bounded to 32,768 nodes and depth 16, with text/key
ceilings checked before semantic grouping. The aggregate compiled programme
bytes for one product are capped at 4 MiB before evidence-store persistence.
This also bounds repeated product-fee/footnote expansion; an over-budget product
keeps its public discovery/source dates with an explicit unresolved reason.

`cdr_public_rates_runtime.py` connects the existing natural and queued dual
publisher through `AR_LOCAL_PUBLIC_RATES_PUBLISH=1`, absent by default. It
requires the existing `AR_LOCAL_TERMS_ROOT` and immutable revision publisher.
Pending pointers freeze the selected candidate path and byte hash. Completed
late checks, including failed checks, request the existing durable payload-only
retry lane with candidate-hash idempotence. Deferred/incomplete rate processing
cannot request executable pricing publication. Accepted dirty source status
instead requests metadata-only warning publication. A newer complete same-generation pointer explicitly
supersedes an older automatic retry; that retry is settled without publication
and the current snapshot stays queued. Automatic retries never silently replace
their frozen evidence, and controlled historical rollback uses the separate
existing operator path. The pending-marker lock protects concurrent requests.
The immutable publisher checks the exact current candidate after archive
readback and immediately before selected-head promotion and each compatibility
manifest replacement. The short cross-platform `public-rate-snapshot.lock`
fence is shared with candidate CAS installation; it covers the selection check
and selection/manifest mutation, with all acquisition and data uploads outside
the fence. A staged older archive may remain, but cannot restore verified-current
claims after a newer complete failure snapshot.
Accepted registered-source completion uses the same fence before its dirty-event
transaction, closing the acceptance-before-acknowledgement race. The bounded
read-only publication guard inspects committed source events, including failures
whose deterministic processing has not run.
Source status follows accepted completion time across all subscriptions to the
same public document. A delayed older-ingest failure invalidates the active
generation without rewriting retained historical generations. Deterministic
interpretation completion wakes the origin and active generation again, so an
interim status snapshot cannot consume the final result. Reuse of interpreted
bytes requires the exact document, adapter version and registered context;
another lender or a changed adapter cannot donate a verified interpretation.

`cdr_public_rates_warning.py` reproduces status-only immutable candidates from
the original candidate and actual committed source state. No programme price,
fee or formula is changed; every originally approved programme is suspended.
Public reference values retain their last-verification dates under deferred
freshness. Coverage exposes deferred reference/acquisition, pending extraction
and interpretation, and unknown costs. The `queue_source_warning` callback runs
after accepted source completion releases its transaction and fence. An opt-in
hook in the existing watchdog recovers a crash before that callback; it neither
collects nor prices and consumes no additional collector admission. Existing
publication quiet windows/admission/cooldowns still decide when the queued
warning may publish. A confirmed immutable/rolling publication records an
idempotent control acknowledgement without acknowledging pending source work.

When selected G2 is ready before its pricing candidate and the last complete
candidate is G1, the status-only G2 header retains G1 dated discovery/reference
evidence as history, clears every executable programme and chunk route, and
preserves suppressed counts. It binds G1 original bytes, G2 selected generation
and actual G2 source-event state. Core/details and catalogue assets bind G2;
the guard rejects a changed selection or source state. This path cannot rebind
an old offer or reference as G2 current pricing.

An optional operator-configured `AR_LOCAL_PUBLIC_RATES_APPROVAL_TEMPLATE` must
validate the original shadow candidate, reviewed policy and the selected
shipped consumer. Exact initial publication reuses that receipt. Ongoing price
updates require its explicit `allowsValidatedPriceUpdates: true`; a derived
receipt binds the new candidate while preserving the approved final natural
shadow candidate and every source, consumer, operator and canary attestation.
The publication gate rechecks structure for each update.
Changed or missing reviewed programmes are suspended individually, while
unchanged reviewed programmes remain enabled. The full original shadow report
is validated even for suspended cases; zero remaining enabled programmes still
requires the original approval bindings. Warning candidates also bind their
exact source-status projection in the derived receipt. Without a template,
only discovery and reference evidence are packaged. These configuration names
are documented interfaces; this implementation sets no runtime flags and
creates, starts or enables no schedule, daemon or worker. Existing Pi admission,
quiet windows, cooldown, resource and readback controls remain the publication
boundary.

While the capability is absent, existing payload packaging preserves its
accepted legacy policy. A candidate or enabled capability uses the strict
absolute-rate filter, dropping raw adjustments, source minimum/maximum values
and unvalidated unit conversions from legacy lists. The detached discovery
catalogue preserves those products and their precise unresolved/range state.

A review-only local build can be made with the existing builder:

```text
python app_payload.py build --exports <selected-exports> --out <candidate-directory> --public-rates-root <immutable-sha256-candidate.json> --source-observation <selected-observation.json>
```

An explicit `--public-rates-receipt <reviewed-receipt.json>` supplies the separate
controlled publication decision. A direct CLI publish of a new capability is
refused; use the existing immutable revision publisher with the shipped
consumer and operator admission/canary gates. This command creates no timer or
daemon and performs no Pi operation.

Public acceptance captures are retained under `tests/fixtures/public_rates`.
The mortgage capture is the public NAB CDR product response, with a genuine
open upper LVR tier intersected separately by its 95% product limit. Live ANZ
Progress Saver and personal term-deposit responses were collected publicly on
2026-10-14 with `x-v: 7`; the ANZ products list negotiated version 5. Public NAB
term-deposit evidence also verifies that undefined customer relationship
conditions do not become an exact rate. No customer email, uploaded document,
private contract or personalised offer contributes to these fixtures.

`fixtures/resolver-golden-v1.json` contains the public captures' source URLs and
hashes, explicit local test scenarios and independent Decimal expectations:
NAB high-LVR 6.84–7.24% public range; ANZ Progress Saver 0.01% base plus 3.99%
bonus under its explicit qualifications; ANZ one-month maturity TD 0.05%.
These scenarios are calculation assumptions, not lender approvals. The app
copies the same bytes for Python/TypeScript parity verification. Git attributes
preserve literal public response and golden bytes on Windows and Linux.

Focused verification covers public acceptance, boundaries, changed prices,
reordered and malformed arrays, failed/stale/future data, unit precision,
unsupported types/semantics, missing fees, immutable transport, download
corruption, budgets, policy separation and populated/idempotent migration.
The locked pending-publication wrappers and their checked-in implementations
remain bound by the rollback compatibility fingerprint. Historical fee
projection identities remain frozen; a separately reviewed current code pair
accepts the optional public-pricing filter without changing the default legacy
behaviour or any fee-rendering function. Unknown or mixed code pairs fail closed.
The root agent owns the complete isolated `python -m pytest tests/ -q`, app CI,
PR feedback/merge and rollout ledger. Passing local fixtures does not establish
three natural daily ingests, public publication, deployment or native-device
acceptance. Those remain separately evidenced gates. Runtime schedules and
the accepted public payload have not been activated or modified by this work.
