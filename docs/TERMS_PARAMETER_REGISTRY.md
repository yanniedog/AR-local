# Canonical interpretation parameters

New interpretation jobs require `terms-parameters-v2` and its complete content hash
into their immutable context. The interpreter receives the same definitions
that admission validates. Altered definitions, extra nested fields and unknown
registry versions are rejected before source text can be sent to the worker.

The initial catalogue has 13 descriptive parameters: product name, description,
brand name, category and tailored flag; rate type, advertised and comparison
rates; loan repayment and purpose; fee type and method; tier application method.
V2 has no bare CDR field aliases. All 14 former leaves were reviewed: nested
`name` and `description` may identify tiers, product attributes require root
scope, and `rate` can describe a fee. The remaining leaves also need their
source containers to establish applicability. Bare leaves and natural-language
guesses therefore have no global mapping; ambiguous scope stays unresolved.
Canonical identifiers remain available for independently source-scoped terms.

Text uses a null unit; the tailored flag is a real boolean. Annual rates use
exact decimal strings with the explicit `fraction_per_year` unit. Zero and false
are values, not absence. Percent strings are not silently converted by the
interpreter admission layer. Source wording and its location remain in the
existing immutable clause records; original product/tier/package/cohort, dates,
conditions and exceptions remain mandatory parts of the staging envelope.

Unknown parameters and unreviewed rule patterns must remain source-bound
`unresolved` clauses with reasons, not invented normalized terms. Every initial
entry has an empty supported-rule-pattern list: recognition of a typed
description does not approve a calculation or establish legal applicability.
Normal independent source review and revision/publication gates still apply.

Both public enqueue paths require the exact current registry before any job
write. Historical and incorporated enqueue operations inherit this admission;
an empty caller-supplied registry or an authentic retired v1 cannot create a job.

Existing immutable jobs without a registry and with authentic
`terms-parameters-v1` keep their original staging contract. The complete v1
definition and hash remain unchanged. They are not relabelled as v2-validated
or automatically replayed. These retained contexts are read compatibility only,
not an option when creating or re-enqueuing jobs.
Adding parameters or aliases requires a reviewed version and source regression;
existing version definitions must remain immutable for retained jobs.

Deterministic schema and staging-value failures terminally block the affected
job with `invalid_staging_schema`. They do not set an account cooldown or retry
the same model input. Transport, quota and resource deferrals retain their
separate retry handling.

## Verification boundary

Tests admit the name from retained real September CDR bytes through staging and
revision, reject mutated names/units/types/context and executable patterns, and
retain unmatched wording as unresolved source clauses. Numeric boundary cases
are protocol tests, not fabricated banking acceptance fixtures. The registry is
an initial vocabulary, not whole-corpus coverage or completion of T-004. Runtime
deployment, complete semantic mappings and every-product applicability remain
separate acceptance gates.
