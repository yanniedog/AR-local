# Product evidence implementation and recovery routes

Design/acceptance review updated 2026-09-14. **Code foundations are tested; full
product coverage and live acceptance remain incomplete.** The detailed checklist is
[PRODUCT_EVIDENCE_ACCEPTANCE.md](PRODUCT_EVIDENCE_ACCEPTANCE.md). This document
records scoped implementation requirements and the implemented boundaries below.
It is not permission to replay historical operational commands or activate a Pi
worker before the outstanding operational gates pass.

## Implemented worker boundary and outstanding activation gates

The optional finalization capture, immutable evidence store and acquisition queue
are implemented separately from public payload promotion. The dedicated
`pi_terms_worker.py` cycle first admits work against production priority and disk
reserve, then supervises a bounded sequential acquisition batch for 120 seconds
and at most one due interpreter for 720 seconds. The batch admits at most 32
attempts/64 MiB, stops admitting at 105 seconds and reserves 15 seconds for durable
completion. No due acquisition starts no HTTP request.
Acquisition remains independent of subscription authentication and quota cooldown.
The queue's 180-second acquisition lease recovers an interrupted fetch; the
900-second interpretation lease rejects stale completion. A 15-minute timer is
an outer retry bound, with no persistent catch-up during the protected window.

Admission stops new cycles at 21:45 Hobart. Running work yields at 22:00. Every
resource tick checks production locks, ingest cgroup membership, publication
pending state and backup source processes using read-only observations. An
unavailable observation fails closed. The optional resource-supervisor callback
does not change existing callers' default behavior and only signals descendants
in the dedicated, undelegated worker cgroup. It never signals or reclaims an ingest,
publication or backup owner. A slow priority observation still fails the existing
two-second maximum sampling-gap check. Native simultaneous-start and actual timing
proof remain required.

The unit retains CPUQuota=100%, IOWeight=10, MemoryHigh=2G, MemoryMax=3G,
MemorySwapMax=0, TasksMax=128, a 16-minute service bound, read-only original data,
private auth/evidence write paths, empty capabilities and protected system/home
paths. On systems without an enforceable memory controller, the existing sampled
aggregate RSS, 2 GiB reserve plus headroom, swap/PSI, process identity and cleanup
guards still apply. Nothing in these additions weakens their thresholds. The
approval marker keeps the unit dormant; code existence is not activation proof.

`pi_terms_codex.py` accepts only a private saved ChatGPT session, strips inherited
API/GitHub/Drive/proxy environment variables, forces ChatGPT login and the OpenAI
provider, and disables tool/plugin/shell/browser/agent features. It runs in a
private job directory with a read-only sandbox and a bounded input, output and
diagnostic budget. Only the explicitly reviewed public product/registry context
fields can reach the interpreter; unknown context fields fail before creating an
input file, preventing customer profiles from entering this extraction transport.
The installed Pi CLI must prove these exact flags and sandbox
are supported; incompatibility is a blocker, never grounds to relax protection.
Normal CLI OAuth refresh persists in the dedicated private auth file; the worker
reads it afresh and reconciles authentication failures automatically. It cannot
repair revoked authorization by inventing credentials or switching to API billing.
These authentication semantics are documented in the
[official Codex authentication guide](https://developers.openai.com/codex/auth).

Controlled transport deferrals write an immutable receipt before returning.
Receipts bind the input, schema, lease binding and diagnostic hashes. Resource PASS
means only that the process stayed within the resource contract and cleaned up;
staging additionally requires a successful transport receipt, matching result
bytes, JSON schema and the current queue lease/source. A superseded source can
commit its superseded event and then raise: the controller now preserves that
event rather than trying an invalid transition to blocked. A format-valid staged
answer remains unreviewed legal interpretation and cannot publish or enable rules.

`interpreter-state.json` is durable private account-wide cooldown state. A quota
failure suppresses calls for every queued product, including after process restart.
Only a recognized terminal CLI error with an explicit integer reset epoch can
supply a reset deadline; model text, quoted errors, prose dates, invalid epochs
and unknown event schemas cannot. A trusted reset adds a one-minute safety margin
and at least a 15-minute wait. Otherwise quota retries start at two hours and cap
at 24 hours, authentication retries at one hour and cap at 24 hours, transport
retries at 30 minutes and cap at six hours. Repeated failures back off exponentially.
Production-priority deferrals start at 15 minutes and cap at one hour. Changed valid
saved credentials can reconcile an authentication block, but cannot bypass a quota
deadline. Actual Pi CLI structured reset compatibility remains unverified; the
conservative path remains available without parsing untrusted model content.

Verification evidence is in the current acceptance checklist. No live Codex
inference, paid API, Pi mutation, Drive write or runtime activation was used for
the local worker tests. Before activation, root must verify the live persistent
Drive hold; canonical nonoverlapping evidence/auth/source paths and ownership;
the exact installed CLI's isolation and subscription authentication; bounded native
success/failure/quota/priority-yield canaries; natural scheduler operation; and the
review/publication/consumer gates. The full legal corpus, OCR/fixed-point linked
document traversal, reviewed canonical registry and every-product applicability
adapter remain unfinished.

Historical interpretation now has an explicit immutable target in `historical.py`:
`enqueue_historical` binds observation IDs, raw hashes, document version, extraction,
context and UTC capture dates. It can stage a retained older version after the
source URL advances. Priority 2 alone never bypasses source safety. The worker's
`STAGED_HISTORICAL` receipt and mandatory `historical_only` result scope prohibit
current publication; legal effective dates and Hobart observation days are not
inferred from UTC timestamps. The May 19 deterministic fee repair uses its own
dated source contract, separate from this interpreter.

## Bounded incorporated-document graph (D-002)

`cdr_terms/graph.py` adds a durable candidate frontier in the dedicated append-only
evidence database. A root binds one successful acquisition check and every raw CDR
applicability pointer associated with that request. Each edge binds its parent
node, exact document version and extraction, HTML anchor occurrence, original href,
resolved URL and label. Shared URLs reuse acquisition requests within an ingest;
distinct URLs keep distinct version identities even when their bytes share one
content hash. Cycles and repeated anchors remain visible. These candidate edges
do not add reviewed product applicability or public terms. Usable child text now
enters the existing interpretation queue with a pinned candidate-only context;
the expansion and job commit atomically under the exact processing lease. Its
worker result remains `STAGED_INCORPORATED_CANDIDATE`, with applicability unreviewed
and current term promotion prohibited. See
[INCORPORATED_INTERPRETATION.md](INCORPORATED_INTERPRETATION.md).

The existing collector performs at most one offline retained-node expansion and
one bounded sequential acquisition batch per cycle. Expansion, edges and new frontier requests
commit atomically; interrupted expansion restarts idempotently. Existing acquisition
leases govern fetch ownership. Only an exact lease-accepted successful capture
activates its seeded graph, including when its interpretation remains unavailable.
An uncompleted or superseded lease cannot activate it. New observations supersede
old scope only after their complete-ingest marker exists; unfinished captures stay
as evidence. Changed completed observations, parent versions or final URL locations
stop current traversal, with an explicit retained disposition. Malformed HTML or
unreadable retained bytes receive durable failed expansion records, so a broken
node cannot indefinitely prevent sibling requests from progressing.

Default limits are depth 3, 32 URL nodes per root and 128 followable anchors per
node. The extractor retains at most 256 anchor occurrences and records the exact
remaining count against the retained original bytes. Depth, node and link limits,
unsafe references, non-document assets and unapproved hosts have explicit reasons.
No unsupported PDF/plain-text reference detector or empty HTML link set establishes
legal closure. Scans, OCR, dynamic content, HTML base overrides and material clause
coverage still require additional work and independent review.

Host grants come from exact original CDR references or an explicit retained review
receipt; no linked page can grant another domain or subdomain. Network DNS/IP and
redirect guards remain enforced. Relative HTML links use the acquisition's verified
final URL. Conditional validators are sent only to their exact retained final URL;
an unbound 304 or changed redirect destination is a failed check, never an inferred
unchanged document. Old bytes/checks remain intact. Graph-only captures retain
today's actual observation time and never become historical legal evidence.

The graph contract is described in
[`document-graph-v1.md`](../contracts/product_terms/document-graph-v1.md).
Local tests do not establish deployed behavior or whole-catalogue completion.
The recorded baseline has 1,565 normalized URLs but only 73 admissible scheduled
cycles per day. The former one-fetch schedule required at least 22 days before
recursion or retries. The implemented batch cap permits up to 32 sequential
attempts per cycle; configured capacity is not measured daily recheck proof.
Current runtime activation and full-catalogue throughput remain unverified.

## Authority and reviewed material

The current operator approved implementation of comprehensive current/historical
Mortgage, Savings and TD terms capture, linked account/package analysis, customer
eligibility and exact cost/return comparison through AR-app. The operator requires
the Google Drive backup to remain unchanged and scheduled Drive writes held until
explicit approval to resume. Pi-hosted Codex CLI uses the existing subscription;
separate paid API usage and a Windows-dependent analysis scheduler are excluded.

Read current `AGENTS.md`, `WORKFLOW.md`, `docs/CDR_QUALITY_PIPELINE.md`, the full
1,881-line controlled `PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md`, the complete latest
tracked handoff decision D-027 and the latest accepted section of the private
September 14 Drive continuation. The 36,834-line tracked handoff was indexed across
the full file to locate chronology and controlling decisions; every repeated old
receipt was not independently semantically re-reviewed. Its latest decision and
the current `AGENTS.md` prioritize the daily quality policy and applicable older
controls. Older evidence remains unchanged and is not an executable run sheet.

Applicable rules include `pi-host-not-localhost.mdc`, `no-mock-test-data.mdc`,
`data-first-ui.mdc` and the verify-only Pi watchdog policy. The private handoff is
an operational input and must not be copied into public Git or releases.

The implementation owner must record the new hold/worker authority in the active
append-only operational record, with reasons, scope, compensating controls and
revised proof criteria. This explicitly supersedes daily Drive writes for this
task without withdrawing source immutability or natural-ingest protection. The
agreed emulator substitutes for this task's phone testing; it does not establish
physical-device or physical-recovery proof in older programmes.

## Operating constraints

| Boundary | Required behavior |
| --- | --- |
| Pi ownership | One live mutation owner. Pause existing automation and obtain prior-owner safe-idle acknowledgment before takeover; no duplicate competing continuation. |
| Backup hold | Persistent refusal at all dispatch boundaries and disabled write schedules; retain requests and receipts. A disabled daily timer alone is insufficient because terminal events and queue timers also dispatch. |
| Existing upload | Reconcile actual terminal state before hold/control transition; never kill an unknown job or clear its lock. Preserve reclaim restoration independently. |
| Natural ingest | Keep 01:00 Australia/Hobart timer unchanged. All new work yields to actual ingest/publication activity and the 00:30 freeze. |
| Heavy work | Use existing priority, lock, capacity, deadline and resource controls. Recovery/activation is within 03:30–22:00; late ingest defers work. |
| Resources | Preserve measured RSS/address-space, reserve, PSI, disk, CPU/I/O, no workload swap/new host swap-out and descendant cleanup gates. Nominal systemd MemoryMax is insufficient where memory cgroups are disabled. |
| Activation | Exact tested candidate, controlled canary, immutable receipts, rollback proof, deployed hash, live smoke, two-hour soak and natural-ingest proof. Merge does not prove deployment. |
| Git workflow | Fresh default-base topic checkout, focused PR, applicable CI, substantive dispositions/resolution, tracked `pr:merge` wrapper, post-merge audit. No watch loops or direct protection bypass. |
| Windows | No UAC, unsafe old dispatcher, or `os.kill(pid, 0)`. Use native liveness and hidden isolated process-control tests with complete summaries. |
| Browser | External Chrome, preserving tabs. Pi acceptance at `http://100.78.28.10/`; no in-app browser or localhost substitute. |
| Source history | No in-place migration, reconstruction, integrity-build or output creation under retained evidence. Read verified private copies when SQLite journal recovery is needed. |
| Publication | Consumer before producer; archive/download verification before pointers; history correction cannot move newest rolling date backwards. New terms correction uses a higher immutable revision. |

The old controlled runbook describes a withdrawal-triggered rolling downgrade
protocol; that is not a general rollback tool and is not the new terms correction
mechanism. The accepted plan instead calls for a new higher corrective revision.
Do not alter the old protocol or pointers merely to reuse its terminology.

## Existing behavior to extend deliberately

| Existing implementation | Useful capability | Limitation relevant to this task |
| --- | --- | --- |
| `cdr_clean_export.py` | Current normalization/export pipeline | Generic cleaning removes many URL fields; only selected top-level references survive. Discover from raw CDR first. |
| `cdr_product_facts.py` | Deterministic primitive facts and reviewed narrow taxonomy | Hundreds of thousands of leaves do not prove complete legal/financial semantics. Keep unmatched clauses. |
| `cdr_product_changes.py` | Normalized fact changes, conditions, wording and identity ambiguity | Extend source/effective/cohort provenance rather than duplicate diff engines or infer missing facts were removed. |
| `cdr_quality_sources.py` / `cdr_quality_audit.py` | All retained observation/log inventory, membership and public reconciliation | A source audit PASS does not mean every linked document or fine-print rule is captured. |
| `cdr_quality_sqlite.database_view` | Private-copy WAL/rollback recovery with source inventory checks | New callers still need controlled source hashing, safe path/owner checks and a bounded temporary location. |
| `cdr_historical_*` | Locked corpus, canonical row multisets, explicit unavailable populations and conflicts | Dormant, fixed 92 dates, no network or publisher, blocked preservation drift; never widen its locks into a current production contract. |
| `app_payload_revisions*` | Immutable per-date revisions and public asset/readback verification | Requires shipped consumer SHA and outer production lock; stage complete bundle and CAS current dependencies. |
| AR-app `productHistory` acquisition | Lazy dated cores and revisions | Existing date-list/current-core cache reuse misses corrected historical heads; pin per-date identities. |
| AR-app `userRateScenario` | Encrypted native profile and existing switch assumptions | Preserve migration; product type presence is not customer eligibility. |
| AR-app `projections` | Existing illustrative monthly scenarios | Annual/12 and average-month cashflows do not satisfy exact bank-specific calendar calculation. |
| AR-app fee/stay-switch presentation | Unpriced fee/claim availability distinctions | Preserve unknown cost semantics while adding all fees and conditional dependencies. |

## Contract and storage boundaries

New records are independent from original observations and retain explicit schema
versions. Use a dedicated append-only database with foreign keys and immutable
records, content-addressed files and create-once receipts. Mutable queues/pointers
are separate, transactionally updated and rebuildable from verified history.

| Record | Minimum semantic responsibilities |
| --- | --- |
| `DocumentVersion` | Original content digest, length/media type, original/final safe URL, acquisition metadata/time, source issue/version/effective dates if stated, predecessor/replacement evidence, extractor identity and text/table/page coverage. Same bytes may have multiple URLs/check events. |
| `SourceClause` | Document identity, stable page/section/table/cell/footnote or text-span locator, exact source meaning/text reference, scope/definitions/cross-references, extraction method and unresolved status. |
| `ProductApplicability` | Explicit bank/product/tier/account/package/cohort relationship, observed and effective intervals, dependency references, exclusions, evidence and unknown scope. Content dedupe must not merge applicability. |
| `TermRevision` | Canonical parameter ID, typed exact value/unit/operator/range/rounding/cadence, conditional formula, source clauses, applicability, observed/effective times and supersession reason. |
| `RuleSet` | Immutable declarative supported rules, rule registry/evaluator versions, dependency closure, validator/benchmark provenance and applicability. No arbitrary executable code. |
| `TermChange` | Before/after term IDs, source/interpretation change category, exact affected products/cohorts/dates, discovery/effective dates and removal/replacement proof. |
| `TermsCoverage` | Separate discovery/acquisition/extraction/interpretation/executable-calculation states; denominators, verified counts, unresolved references/clauses, unsupported rules, pending/stale/conflicting data and material impact. |
| `CalculationReceipt` | Profile/scenario identity and private inputs, horizon/dates/cashflows, exact dependencies and evaluator version, assumptions/unknowns, eligibility result, deterministic dated ledger/result/rounding trace and recomputation linkage. |

Use exact decimal/rational arithmetic for money, rates and thresholds, with explicit
rounding at the evidenced event boundary. Floating-point formatting of source data
is not a normalization proof. Numbers, zero, false, empty and unknown must survive
serialization distinctly. Reject NaN/infinity, malformed ranges and orphaned scope.

Two clocks are required: what was observed when, and which customer contract was
effective when. Do not backdate an observation after discovering an older dated
document; mark the source fact's evidenced effective interval separately. A new
version is not automatically applicable to all existing customers or fixed terms.

## Processing and trust boundaries

1. **Collector** discovers raw references and checks all applicable documents at
   every ingest. Fetches are bounded and restricted to verified official public
   resources, including all redirect targets. Store full original bytes privately
   before parsing. Preserve status for inaccessible/incorporated references.
2. **Extractor** retains page/table/footnote/definition structure and a complete
   clause inventory. It records unsupported or partially extracted pages. Binary
   changes and normalized text changes are separate facts.
3. **Interpreter** runs as one resource-limited Pi Codex job with existing
   subscription auth in a private restricted workspace. Document content is data;
   the model cannot execute instructions found in it or access production/backup/
   publishing credentials. It returns schema-bound staging records only.
4. **Validator** checks numeric/unit/date/scope evidence, canonical mappings,
   dependency closure, supported patterns and benchmark coverage independently of
   model confidence. Unresolved materially affecting clauses prevent executable
   completeness, not independent verified-rate publication.
5. **Publisher** is the separately authorized deterministic process. It performs
   source/dependency CAS, creates a new immutable term asset/bundle revision,
   independently verifies public bytes and advances the selected head last.

Queue identity includes content, extractor version, rule/registry context and
applicability inputs. Reanalysis due to changed context is legitimate even if
document bytes are unchanged. A 304 requires a known retained validator/content
pair. Missing ETag/Last-Modified, a redirect or failed request cannot become
"unchanged" merely because no replacement file was saved.

Queue records distinguish pending, leased, retry-deferred, validated, rejected,
superseded and published. Use durable leases and unique idempotency keys; stale
workers cannot promote after a newer source/applicability/rule generation. Resource
or quota rejection preserves work with its due time, never a false successful empty
queue. A guarded 15-minute retry must exit without a Codex call when nothing is due.

The worker must not infer completeness from a document hash match, a parse exit,
primitive leaf counts or a second AI opinion. Real annotated supported-pattern
benchmarks and a held-out corpus determine readiness. Changes to code, schemas,
canonical parameters or executable patterns follow normal PR review; routine
validated source updates can use the controlled data-promotion path.

## Deterministic customer comparison

One reviewed evaluator must serve the app and audit harness, rather than
independently ported finance algorithms that drift. Keep private customer values on
device. Dynamically request missing relevant inputs; a missing age, income, account
opening date or linked account cannot be treated as failing or passing by default.
Store user-negotiated terms separately from published bank facts.

Declarative eligibility supports bounded nested AND/OR/NOT, exact comparisons,
inclusive/exclusive ranges, calendar windows, counts and linked-account conditions.
It returns meets-published-criteria, does-not-meet or needs-information with traces.
Unsupported rule syntax, missing scope and material unknowns propagate explicitly.

The calculation engine uses a dated event ledger: opening balance, settlement,
deposits/withdrawals, interest accrual/posting, repayments, fees, waivers, rate/term
changes, maturity and rollover. Define same-day event order, day-count convention,
leap years, month-end handling, compounding, rounding and whether tier rates apply
to whole or marginal balances from the actual contract. Unknown conventions must
prevent exact bank-cost claims. Preserve the older monthly model only as labelled
illustrative behavior where it remains useful.

Comparison includes all linked/package costs once under evidenced precedence.
Separate principal movement from interest/fees and compare equal dates/horizons and
cashflow assumptions. Unpriced break/exit/government/variable charges stay unknown;
they cannot become zero. A known subtotal is not the complete cost. Cheapest/best
claims require all material compared inputs and rules to be valid for the scenario.
Future bank changes are assumptions unless an announced effective revision proves
them. Receipts retain the precise inputs, assumptions and dependency revisions.

## Safe historical correction route

Create a new contract/namespace for derived corrections, separate from
`contracts/historical/*` and the original dated exports. Inventory every retained
date, generation, source projection and failure before selecting repair inputs.
Support variable current history size; the old 92-date lock is an historical fact.

The correction input manifest should bind source path/role, size/hash, original
observation date, variant/generation, provider/product/raw row identity, source
schema, exact transformation version, output fields, evidence clauses and unresolved
issues. Rehash inputs before and after execution. Output to a resolved separate
scratch root; never inside or overlapping preserved source roots.

For finalized main-only SQLite, immutable/query-only access is suitable. Where WAL
or rollback journal content matters, freeze and hash the whole source set, copy to
private scratch, verify all copied bytes and apply recovery only to that copy. Do
not open preserved WAL databases using `mode=ro` alone: it can change SHM. The old
dormant reader intentionally ignores WAL/SHM; that historical contract cannot be
silently repurposed to assert recovered current content.

| Defect | Safe recovery route | Required unresolved disposition |
| --- | --- | --- |
| May 13 missing taxonomy on 10,394 rows | Join each original row to exact retained same-day structured detail/rate evidence with provider/product/family/index and semantic checks. Apply a reviewed deterministic classifier in separate derived output; preserve source row and classifier version. Verify the full row multiset, unchanged prices and one output/disposition per source row. | Missing or ambiguous classification remains unknown. A current classifier's dataset/name fallback is not evidence of historical eligibility or account type. |
| May 19 broken archive plus two projections | Keep `_broken-2026-05-19-empty` as undated diagnostic evidence. Inventory the legitimate 1,632-product/10,554-rate export projection and 1,618-product/10,514-rate SQLite/dashboard/payload projection separately. Trace common/missing/different raw rows and artifact provenance. Only select a derived view when explicit coherence/accounting proves it. | Parallel variants are not parent/child corrections and cannot be silently unioned. Report projection ambiguity; never infer that the entire day is missing. |
| May 31 AMP `AMP_LAND_HL` collision | Retain both original records/indices. Compare same-day raw product IDs, complete details, source path and rates. Distinct proven source identities can receive collision-safe derived identifiers with alias provenance; byte-identical duplicates remain source multiplicities. | Unresolvable conflicting identity stays quarantined. Never overwrite dictionary entries, choose the larger rate or invent another product based on name. |
| 8,372 legacy 12-month fallbacks | Use the existing strata only as inventory: 552 compound ISO, 1,564 structured range, 5,796 text evidence, 460 no evidence. Reinterpret exact source scopes using reviewed parsers and real fixtures. Retain duration units/range boundaries rather than force all into one month number. | Text evidence is not automatically a unique exact term; payment/accrual frequency is not tenure. The 460 no-evidence rows remain null unless new dated evidence resolves them. |
| Semantic tier collisions | Preserve canonical multisets, raw indices and every raw semantic field. Distinguish 763 conflicting groups/1,876 rows from 95 same-value groups/190 rows. Resolve only when retained same-day tier/cohort scope separates values. | Conflicting indistinguishable tiers stay out of exact history and alerts. Same-value duplicates must not be incorrectly counted as conflicting prices. |
| May 14 and June 26 calendar gaps | Search explicitly named verified retained run/archive/raw/log/export/public-release sources and official dated documents. Record each search and source date. Restore a publication only if a valid captured observation survives; otherwise publish a separately labelled dated-facts reconstruction only under the new contract. | No observation survives: retain May 14 known gap / June 26 unclassified gap and explain the evidence limit. A dated rate table cannot prove a complete registered/provider population or a successful historical ingest. |
| August 16 failed RAM attempt | Preserve `ram-1786806121645314910` raw/log evidence; identify whether another finalized same-day generation exists. Report attempt and selected date outcomes separately. | Missing finalized database means incomplete attempt. Never relabel it successful or infer that all observations on the date failed. |
| Missing historical document versions | Use retained full documents or verifiably dated official versions with explicit product/cohort applicability. Preserve observed-versus-effective time and confidence/disposition. | Present-day terms never fill an earlier unknown. Missing source means unknown fees/eligibility, not free/unrestricted/removed. |

Do not run `scripts/backfill_app_payload.py` over preserved originals. Its
`dry_run` branch can call `build_payload` into `exports/app-payload` when missing;
`--force` bypasses failed observation gates; dates-index failure is nonfatal in
that legacy workflow. It is not a safe repair controller. Likewise,
`cdr_rate_normalize.py` uses magnitude-based divisors and a small-lending-rate
multiplier; historical re-export must not silently run prices through those
heuristics. Normalize only where explicit field/schema/source evidence establishes
the unit, retain original values, and quarantine ambiguous/mixed scales.

Before any correction publishes: verify source invariance, exact row/membership
accounting, field-level evidence, deterministic output, conflict disposition,
schema/bounds, selected predecessor identity and consumer compatibility. Use the
new approved contract to create a higher per-date immutable revision via the
existing revision machinery, with external production lock, durable revision state,
consumer SHA, complete assets and public readback. Updating an old date must retain
all newer heads and cannot replace a newer rolling observation. App history must
invalidate the changed date using its selected manifest/core identity.

## Report and operational completion

The final report is a searchable HTML artifact plus CSV tables and JSON evidence,
not only a narrative summary. Include bank/product/date identifiers, coverage
denominators, source generations, every parameter/value/unit, exact source and
effective dates, normalized/executable status, dependencies, repairs and remaining
gaps. Include retired products, duplicate variants, attempts and excluded rows with
clear status rather than dropping them from denominators.

For R-002 report fields, `sections` records only observed published rate sections;
`product_families` uses those sections when rate rows exist. Without rate rows,
only `TERM_DEPOSITS` maps to `TD` and `RESIDENTIAL_MORTGAGES` to `Mortgage`.
`family_basis` records `published_rate_section`, `reported_category` or `unknown`.
Combined transaction/savings categories remain unknown without rate evidence and
appear under Other / unclassified. These classification fields do not add rate
rows or alter published counts, values or detail fields.

Inventory existing metrics as well as newly added fields: rates and comparison/
ongoing/base/bonus components; rate tiers, LVR, balances, term and repayment/purpose;
fees/features/eligibility/constraints and facts; provider attempts/failures and
product dispositions; historical changes and gaps; bank min/max/mean/median/counts;
RBA decisions/pass-through/cohort/baseline-window measures; scenario eligibility,
costs, returns and assumptions. Trace each formula to implementation and state
units, selection rules, completeness requirements and denominator. Primitive fact
counts must not be presented as distinct fully understood legal terms.

Complete catalogue accounting, public asset verification, live Pi smoke/browser
checks, native candidate/released APK tests and a naturally scheduled Pi cycle
without Windows are separate exit gates. Preserve Drive hold evidence throughout
and at closeout. Task status remains partial while executable semantics, processing
backlog, exact calculation, historical disposition or required runtime proof is
unfinished; externally unrecoverable sources remain explicitly disclosed limits.
