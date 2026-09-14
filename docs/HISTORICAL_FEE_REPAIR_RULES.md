# Historical fee correction rules

Source admission and field correction have separate identities. The May 13
embedded-export and May 22 archive admission schemas continue to bind the same
exact source scopes. They do not grant broader date, archive, parent or
publication authority when a field correction rule changes.

New embedded-export corrections use `variable_zero_placeholder_v3` for the only
permitted old-field deletion: the misleading legacy `value` of a variable-zero
fee. Its variable discriminator is the existing, hash-pinned fee projection's
`amountStatus`. That projection strips surrounding whitespace and normalizes
case when interpreting `feeType` and `feeMethodUType`. Source strings, display
labels and retained structured values are never rewritten or normalized.

All remaining conditions still apply together: `value` is the only conflicting
old field; the projection supplies no replacement `value`; both source `amount`
and old `value` are finite exact numeric zero, excluding booleans and unknowns;
and every present recognized lower bound is finite exact numeric zero. Full product,
rate, fee-array, flattened-row and exact source membership precedes this rule.
Display-field differences continue to withhold the whole product's fee array.

The lower-bound check recursively inspects dictionaries and lists for
`minimumAmount`, `minimumValue`, `minAmount`, `lowerBound` and `lowerAmount`
(case-insensitive keys). An absent bound is permitted. A present null, `"null"`,
`"none"`, blank string, boolean, container, nonfinite value, unreadable value or
any exact nonzero value withholds the entire conflicted fee unchanged. A zero
bound elsewhere cannot override it. Unrelated unknown metadata is preserved and
does not by itself block a correction. Both literal and normalized variable
discriminators use this v3 guard; source spelling and numeric types are retained.

Each new deletion records the explicit v3 `rule_id` in `changes.jsonl`, with its
exact source spelling in the existing derived amount-status proof. The May 13
receipt's rule totals and both adapters' source-hash bindings preserve that
identity. Existing v1/v2 receipts and sealed candidates remain unchanged. Those
versions allowed some present unknown bounds; v3 narrows the destructive rule
and does not relabel or replay their results. The structural change verifier
accepts only named v1, v2 and v3 deletion rules so retained earlier changes can
still be reconstructed; it rejects unknown future deletion rules. Structural
restoration alone does not validate any version's original source proof or
retroactively apply v3 semantics to earlier evidence. The independent May 19 raw
response repair remains on its existing v1 rule and is unchanged.

Membership indexing rejects present non-string textual identities with a
controlled `ValueError` before sorting or using them as bank/product keys.
`rate_index` and `item_index` require actual integers, excluding booleans and
numeric strings. Their positive-range and complete-array checks remain in
place. No malformed identity is coerced into an invented key or provider name.

Protocol verification uses fault-injected memory copies of the checked-in
retained May 13 excerpt. It does not open original archives, images or databases,
rewrite prior candidates, infer missing terms, or establish legal applicability,
complete product costs, publication or runtime acceptance.
