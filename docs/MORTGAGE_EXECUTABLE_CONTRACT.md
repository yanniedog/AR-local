# Mortgage producer contract

This adds the `mortgage_calculation` capability to the existing append-only
wire-3 registry and publication controller. It does not approve a bank product,
activate ingestion, publish assets, or change SQL migrations 001/002. Existing
term-deposit, eligibility and Savings contract bytes remain unchanged.

## Source interpretation

New jobs use `terms-parameters-v4`. The added key
`monetary.mortgage_field_v1` accepts only the closed eighteen-field material
contract. Old v1/v2/v3 registry contexts remain readable with their original
aliases, schema identities and validation. New jobs cannot reuse those older
contexts. The v4 staging schema has its own identity; the worker derives a
context-specific generation schema and still admits output through the stronger
canonical schema. Generation guidance is not an approval gate.

The fields cover rate, interest-bearing components, payment allocation/phase/
rounding, accrued settlement, day count and daily/posting rounding, posting
inventory, obligation calendar, opening state, fees and their settlement,
excluded effects, and eligibility. Each used source interval and clause must
match a validated typed revision's exact field, scope, dates and material.
Description strings and customer confirmations do not establish policy.

Private retained observations must match actual finalized capture membership,
raw source, manifest and asset identities. Current routing is separately bound
to the adopted core/details and source generation. The source and details
category is `RESIDENTIAL_MORTGAGES`. A selected rate variant additionally binds
its exact Mortgage row, ordinal, hash and fraction rate; a product target needs
no invented rate row. Historical successor and negative-review checks remain
effective within the used authority intervals.

## Private execution and approval

The adapter is `aud-mortgage-confirmed-obligations-v1`, using
`product-terms-engine-v8`. Local account balances, confirmed offer rate, opening
components, original obligation anchor, cleared payments and external fee
settlements stay private. Scenario-owned facts cannot fall back to profile
answers. Ordinary payments must match the due date, source payment phase and
obligation limit. Unpaid obligations cannot produce a complete benchmark result.

Benchmark admission verifies retained code and gzip context, raw input hashes,
exact adapter projection, eligibility trace and independently derived Fraction
arithmetic. It requires a distinct expectation author, a complete positive and
holdout, and actual rate/opening/period/target refusals. Source closure proves
bounded literal local dependencies and locked external metadata; it does not
prove execution of arbitrary external package bytes. Positive approval still
requires current source validation and predecessor CAS. Revocation creates no
new authority and removes the capability from later current routing.

Publication remains explicit, default off and immutable. Mortgage and Savings
use separate index/shard routes in the existing URL-free namespace. Removal
tombstones are internal; no empty public subject asset is emitted. Shared
operation and packaging budgets span both capabilities, rather than resetting
per family. Historical retained members keep their 2 MiB/member, 32 MiB raw and
24 MiB decoded limits; adopted public assets use their separate 24 MiB budget.

## Evidence boundaries

`tests/fixtures/mortgage-v3` retains an engineering-only actual app capture from
commit `74fa58126237ecf527d8eb71f4d17f66f90364a1`. Its two successful cases exercise
principal-only periods without active payments, obligations or fees. The four
refusals came from the actual adapter/transport. Separate hand-derived controls
exercise all five debt components, payment phases, external fees and month-end
posting. Those controls do not claim another source-approved adapter capture.

The connected test reconstructs the actual technical source store, checks the
same captured subject without identity rewriting, verifies benchmark/review,
writes and reads back private package artifacts, then revokes and omits the
route. A prior missing-category technical capture remains private diagnostic
evidence; the corrected details were generated from the original engineering
record by `build_details`. None of this is bank, native, deployment or runtime
acceptance.
