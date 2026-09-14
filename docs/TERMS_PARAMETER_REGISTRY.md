# Canonical interpretation parameters

New interpretation jobs bind `terms-parameters-v1` and its complete content hash
into their immutable context. The interpreter receives the same definitions
that admission validates. Altered definitions, extra nested fields and unknown
registry versions are rejected before source text can be sent to the worker.

The initial catalogue has 13 descriptive parameters: product name, description,
brand name, category and tailored flag; rate type, advertised and comparison
rates; loan repayment and purpose; fee type and method; tier application method.
Exact CDR field aliases follow the existing structured-fact vocabulary. Generic
`amount` and `value`, and natural-language guesses, have no global alias.

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

Existing immutable jobs without this registry keep their original staging
contract. They are not relabelled as registry-validated or automatically replayed.
Adding parameters or aliases requires a reviewed version and source regression;
existing version definitions must remain immutable for retained jobs.

## Verification boundary

Tests admit the name from retained real September CDR bytes through staging and
revision, reject mutated names/units/types/context and executable patterns, and
retain unmatched wording as unresolved source clauses. Numeric boundary cases
are protocol tests, not fabricated banking acceptance fixtures. The registry is
an initial vocabulary, not whole-corpus coverage or completion of T-004. Runtime
deployment, complete semantic mappings and every-product applicability remain
separate acceptance gates.
