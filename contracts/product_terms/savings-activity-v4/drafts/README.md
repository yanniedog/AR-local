# Activity wire4 draft: review boundary, not frozen

Fifteen schemas (including shared primitive/projection files) and a 26-field material inventory. No production dispatcher, migration,
source store or app reader is changed. Frozen v1/v2/v3 bytes are untouched.

Subject policy shape is in savings-policy.schema.json. A single bonus assessment
owns dateBasis/settlement/accountRole once; metric objects cannot override them.
Rule ops use the existing engine `compare`, `and`, `or` names (the plan's all/any
were prose). Deposit/withdrawal metric fields are fixed activity_deposit_total and
activity_withdrawal_count. Threshold units are AUD and count decimal facts; counts
are integer strings. Both base and bonus annualRate are fractional, additive.

Private input is the actual existing SavingsPeriodInputs plus activity and
confirmedBonusAnnualRates. New public schemas contain no customer account ID or
events. No caller assessment/facts/aggregate is admitted. Profile remains the
existing separately bound private profile parameter, not part of public payloads.
One shared private dateBasis is structurally enforced across the event list;
subject/stream equality, exact rate inventory and cross-document identities need
the semantic gates below. No schema check alone claims those gates are complete.

## Freeze paused: actual v9 proof pending

Actual v8 execution refuses any activity when the mandatory fee schedule is
present, including an explicitly empty schedule (feeValidation.ts:139). The
portfolio path also requires assessments inside its frame. Therefore these draft
schemas and22structural/partial-semantic controls do not establish an executable
v8 adapter. Do not omit fees, fabricate authority or widen the application frame.
The app author is designing an explicit NEW evaluator version for disjoint,
completed preceding assessment and no-fee scope while preserving v8 behavior and
existing arithmetic. Root has approved the separate product-terms-engine-v9 dependency and
calculateSavingsActivityLedger entrypoint design. New draft dependency only is
updated; old frozen schemas stay unchanged. Producer implementation and byte
freeze remain paused pending actual v9 focused proof and root review.

## Mandatory semantic gates before byte freeze implementation

1. Canonical IDs and exact subject/asset/approval/routing tuple; index/shard product
   membership and every manifest filename/hash/byte descriptor are exact. Common
   graph primitive reference schemaVersion1 remains unchanged; subject/transport4.
2. Combined assessment start through application end <=366 days, both nonempty;
   assessment end <= application start; applies bounds equal scope and gap-free
   base intervals. Every event lies within the exact preceding assessment window,
   binds the one private account, and shares the source assessment dateBasis.
3. Unique event IDs, metric IDs/kinds/fact fields, disjoint included/excluded
   classifications, source-complete classification inventory. Unknown status,
   classification or coverage never silently passes; settled-only pending
   treatment comes from source policy. No purchases/refunds/growth/linked accounts.
4. Rule leaf inventory equals declared metric inventory exactly, with matching
   decimal unit and integer count domain. No generic profile/user aggregate key.
   With one metric use compare; with two use a single and/or with two unique leaves.
5. Exact confirmedAnnualRates intervalId/tierId and confirmedBonusAnnualRates
   componentId/tierId inventories match every applicable source tier. Reject
   missing, repeated key even at a different value, extra, wrong value or stale
   confirmation. A local confirmation never establishes the rate's authority.
6. All inherited base rate/interest/posting/no-fee/no-withholding/cleared-opening
   restrictions still hold. Bonus is added once, never on top of a combined
   headline rate. No assessment event becomes an application ledger movement.
7. Material field projections compare to exact retained source term values with
   independently reviewed clause positions, unit, source scope and interval. New
   fields: assessmentWindow/activityAccountRole/activityDateBasis/settlementPolicy/
   classificationInventory/metricThresholds cover assessment; bonusRates and
   rateComponents cover application; bonusApplication binds both windows;
   activityExclusions covers both. Existing 16 fields retain original projections.
   Field inventory totals26; noBonusIntro is removed, never synthesized as true.
8. New authority graph field coverage unions cover each used interval without
   gaps; supersession is limited to actual overlaps. Retained observations/dated
   official clauses are independently verified, current category/row/details bound,
   both periods completed under source cutoff, used successor material reviewed.
9. Independent reviewer identity normalization, current-source/current-slot/CAS,
   predecessor links and revocation remain mandatory. Storage003 is a future
   additive view/table change only: preserve001/002 bytes and every old raw row.
10. Actual connected private source -> benchmark -> independent review -> immutable
    package -> revoke must pass without a benchmark stub. Independent expectation
    comes from Fraction math/classification, not copied engine/adapter output.

## Draft proof and remaining gates

controls-receipt.json proves schema syntax, local reference closure, a complete
technical subject/private input with32bonus tiers and leading-digit evidence hashes,
and22bounded structural/cross-input controls. Full material/source semantic proof,
003 SQL, bank source corpus and new adapter output are not supplied or claimed.
Root and app must review these bytes and benchmark-projection.json before coding.

Shared writer map: producer pr755 owns this draft prefix and future new v4
source/material/registry/benchmark/packaging modules. Only after freeze: producer
owns executable_registry.py/parameter registry/app_payload_optional_assets.py and
optional build/revision/report wiring. App author owns activityContracts, new form,
receipt projection and shared consumer inventory/schema generator in its isolated
branch. Root owns freeze/version/acceptance decisions. No parallel shared writer.

Engine boundary: savingsValidation.ts admits32tiers per component. Wire4 base and
bonus components and private confirmations use that bound; larger source tier
inventories are explicitly unsupported and never truncated. Activity amounts
represent exact cents; trailing decimal zeroes are accepted. Event IDs use the
actual engine identifier grammar. Source evidence references use lowercase SHA256,
including leading digits; semantic metric/role identifiers are a distinct domain.

V9 boundary clarification: engine fee definitions are empty, while the source
category inventory remains nonempty and every category is none_applicable; no
deferred obligations. Unknown private event kind yields incomplete, never zero
or a known-false qualification. Known unsupported purchase/refund/growth inputs
are refused. This dependency update is not evidence that v9 execution passes.
