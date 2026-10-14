# Public rate catalogue v1

This additive capability contains public product evidence. It never contains
customer contracts, account data, uploaded documents or personal calculator
inputs. It is absent from the manifest unless explicitly enabled. Missing values
are absent; a discount or bonus alone is not a payable rate.

The manifest `public_rate_catalogue` has `schemaVersion: 1`, `generationId`,
`runDate`, `coreSha256`, `detailsSha256`, `index: Asset` and `shards: Asset[]`.
`generationId` is the selected ingest `source_observation.generation_id`, not the
bundle-derived payload revision identity. Consumers verify that identity, the
core/details hashes and the selected immutable manifest before reading assets.
Asset descriptors have `name`, `url`, `sha256`, `bytes`, `decodedBytes` and
`encoding: "gzip"`. Content-addressed filenames prevent overwrite races.

The index has the same version and binding fields plus `products`, `coverage`
and `shards`. New catalogues keep `products: []`; complete discovery records
are in bounded discovery shards. Coverage provides every provider/category,
including unavailable sources. Its shard descriptors omit `url` and add
`productIds: string[]`, empty for discovery shards. Optional `routes` entries
are `{name,kind:"discovery"|"pricing",providerIds:string[],sections:Section[]}`.
Every route names exactly one shard. These fields select downloads, never
establish pricing applicability. Older v1 indexes with inline `products` and
without `routes` remain readable.
Only exact descriptor matches can inherit transport URLs from the manifest.
Shards have the same binding plus `programmes`, `referenceRates` and `evidence`.
Discovery shards add `products` and contain empty pricing/evidence arrays;
pricing shards contain no discovery records. Only reviewed executable
programmes are packaged. Unapproved programmes remain in the immutable source
candidate/evidence database; published discovery reports their count and
limitations without transporting thousands of unpriced programme objects.
The complete catalogue is at most 24 MiB decoded. Index limits are 256 KiB gzip
and 2 MiB decoded; each shard is at most 1 MiB gzip and 4 MiB decoded. It does not
enter the startup core. Older payloads remain readable without the capability.

Product discovery records have `productId`, `productKey`, `providerId`,
`providerName`, `name`, `section` (`Mortgage`, `Savings`, `TD`), `aliases`
(`{name,effectiveFrom?,effectiveTo?}`), `status` (`current`, `legacy`, `unknown`),
`programmeIds`, `referenceIds` and `reasonCodes`. Optional
`suppressedProgrammeCount` records programmes retained internally but not
published. `programmeIds` lists only programmes packaged in this catalogue.
Optional `freshness` and singular `sourceEvidence: Evidence` preserve the
original public product-name check independently of executable pricing.
IDs depend on semantic identity,
never price or array position. Names and common ownership do not bind pricing.

Each programme has `schemaVersion: 1`, `programmeId`, `productId`, `section`,
`offerId`, `conditions`, `components`, optional `formula` and `phases`,
`evidenceIds`, optional `effectiveFrom`/`effectiveTo`, `freshness`, `reasonCodes`
and `sourceBindings`. Source bindings retain the original JSON pointer and
one-based exported rate index for this generation; these are not stable IDs.
The pointer retains the original array position. The exported index counts
mapping records, so a malformed non-record source entry cannot shift a binding
to a different offer.
Uninterpreted programmes omit the formula and explain the gap in reason codes.

Components have `componentId`, `role` (`payable`, `reference`, `discount`,
`margin`, `bonus`, `comparison`, `reversion`), optional `value`, explicit `unit`
(`fraction_per_annum`, `percentage_points`, `basis_points`), `scopeId`,
`conditions`, `evidenceIds`, `source: {rawType,rawValue?,pointer}` and optional
`includedInPayable` or `referenceId`. Reference observations additionally have
`referenceId`, `name`, `providerId`, `effectiveFrom?`, `effectiveTo?`, `freshness`.
All numerical rates, adjustments, LVRs and bounds are canonical decimal strings
with at most 24 fractional digits. LVR scenario values are fractions.
Generic CDR rates use the declared fraction unit. Non-string scalars and
fraction values outside the supported unit bounds remain unresolved until a
reviewed provider adapter supplies the source convention; magnitude never
determines a conversion. Explicit reference observations can use percentage
points or basis points.

Conditions have `conditionId`, `field`, `operator` (`eq`, `in`, `bounds`, `known`),
`value?`, `values?`, `minimum?`, `maximum?`, `minimumInclusive?`,
`maximumInclusive?`, `description?`, `evidenceIds`. Supported fields are
`purpose`, `repayment`, `amount`, `balance`, `lvr`, `termMonths`, `channel`,
`package`, `customerCategory`, `qualification`, `effectiveDate`, `custom`.
Reviewed deposit numerical qualifications also use `monthlyDeposit`,
`withdrawals`, `balanceGrowth` and `cardTransactions`.
Day-based quoted terms use `termDays`; month-based terms use `termMonths`.
Qualification and custom conditions carry `value` as the local scenario key.
Unknown required conditions never become met. Bounds remain open when a bound
is absent; genuine product constraints are separate intersecting conditions.

The bounded formula language is:

- `{op:"component",componentId}`.
- `{op:"add"|"subtract",operands:Formula[]}` (subtract is left associative).
- `{op:"alternatives",choices:[{conditions:Condition[],formula:Formula}]}`;
  exactly one known eligible choice is required.
- `{op:"tiered",field:"amount"|"balance"|"lvr",method:"whole_balance"|"per_tier",
  tiers:[{minimum?,maximum?,minimumInclusive?,maximumInclusive?,formula}]}`.
  Per-tier yields the balance-weighted nominal annual rate and requires complete,
  non-overlapping coverage of the selected amount.
- `{op:"cap",value,formula}` (value is a fraction per annum).
- `{op:"from",formula}`; `{op:"range",minimum:Formula,maximum:Formula}`.

Formula depth is at most 16 and nodes at most 256. Source-supplied code is never
executed. Direct payable components cannot also receive adjustments marked
`includedInPayable`. Comparison components cannot enter payable arithmetic.
Multiple packages are explicit alternatives, never cumulative discounts.
Phases are `{phaseId,startMonth,endMonth?,formula,conditions,evidenceIds}`;
intervals start inclusive and end exclusive, without overlap. An unknown
reversion phase stops a complete projection at the known boundary.

Freshness is `{state:"current"|"failed"|"stale"|"deferred"|"unknown",
checkedAt?,lastSuccessAt?,reasonCodes:[]}`. The resolver recomputes the 48-hour
limit as of the requested timestamp. Failed checks immediately remove current
verification. Historical values require `scenario.allowHistorical: true` and
cannot produce verified current savings. Future observations are not applied
before their effective date.

`resolvePublicRate(programme, scenario, asOf)` returns `status`
(`exact`, `from`, `range`, `unresolved`), optional `payableRate`, `minimumRate`,
`maximumRate`, `appliedComponents: Component[]`, `phases`, `conditions`
(`{met:Condition[],unmet:Condition[],unknown:Condition[]}`), `reasonCodes`,
`evidenceIds`, effective dates, freshness and `origin` (`published`,
`publicly_calculated`, `user_entered`, `locally_calculated`). Public disclosure
of lender-assessed minimum/range pricing can retain an unknown customerCategory
condition with `lender_assessment_required`; this never permits an exact result.
Rate arithmetic uses exact decimals/rationals. Repeating weighted rates render
at 24 decimal places, half-up, with `exact_rate_rational_rounded`; trailing zeroes
are removed. Published comparison rates are separate display metrics.

Programme `metadata` retains public `rateStructure`, optional `quotedTerm`
(`{value,unit:"month"|"day"}`), `interestPayment`
(`{type:"maturity"|"periodic",frequency?:ISO-duration}`) and `tierApplication`.
This does not supply an undisclosed day-count basis or future reversion rate.
Fixed mortgage schedules stop their known phase at the published fixed period.

Public fees have `feeId`, product-wide `scopeId`, `name`, `role` (`upfront`,
`recurring`, `package`, `switching`, `cashback`, `event`), optional `currency`,
`amount`, `minimumAmount`, `maximumAmount`, `frequencyMonths`, `event`, plus
`conditions`, `evidenceIds` and `source`. Explicit zero fees remain zero; missing
amounts remain absent. `feeCoverage` has `status` (`complete`, `partial`, `unknown`),
`reasonCodes` and `evidenceIds`. An unknown event, discount, frequency, currency
or charge method prevents complete costs. A declared fee list does not establish
the cost of an undisclosed fee or another product's switching charges.

For transport, shared product fees are deduplicated into shard `feeSets`
(`{feeSetId,productId,fees,feeCoverage}`), referenced by programme `feeSetId`.
Transported programmes with `feeSetId` omit both inline `fees` and
`feeCoverage`; consumers hydrate both from the validated shared set.
Consumers hydrate only an exact product binding. Missing sets keep costs unknown
and a partially loaded catalogue cannot claim a complete cost ranking.

Candidate `enabledProgrammeIds` must always be empty. Publication derives
activation solely from the reviewed policy and a separately supplied receipt;
changing captured data cannot enable calculations. The receipt binds the exact
candidate, selected generation, three natural daily shadow cycles including an
unchanged-source cycle, independent public reproductions, consumer release,
native acceptance and existing controlled operator/canary approvals. Without
a receipt, the capability contains discovery, public reference observations
and explicit unapproved-pricing counts. The bounded internal candidate root
uses generation/hash-bound programme and evidence chunks in the same evidence
directory. Publication reads only authorised programmes and their required
evidence; the 24 MiB public catalogue ceiling does not cap the retained archive.
