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
regain a formula during base binding.

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
The root agent owns the complete isolated `python -m pytest tests/ -q`, app CI,
PR feedback/merge and rollout ledger. Passing local fixtures does not establish
three natural daily ingests, public publication, deployment or native-device
acceptance. Those remain separately evidenced gates. Runtime schedules and
the accepted public payload have not been activated or modified by this work.
