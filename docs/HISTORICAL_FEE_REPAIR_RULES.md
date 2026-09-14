# Historical fee correction rules

Source admission and field correction have separate identities. The May 13
embedded-export and May 22 archive admission schemas continue to bind the same
exact source scopes. They do not grant broader date, archive, parent or
publication authority when a field correction rule changes.

New embedded-export corrections use `variable_zero_placeholder_v2` for the only
permitted old-field deletion: the misleading legacy `value` of a variable-zero
fee. Its variable discriminator is the existing, hash-pinned fee projection's
`amountStatus`. That projection strips surrounding whitespace and normalizes
case when interpreting `feeType` and `feeMethodUType`. Source strings, display
labels and retained structured values are never rewritten or normalized.

All remaining conditions still apply together: `value` is the only conflicting
old field; the projection supplies no replacement `value`; both source `amount`
and old `value` are finite exact numeric zero, excluding booleans and unknowns;
and no conflicting nonzero or unreadable lower bound occurs. Full product,
rate, fee-array, flattened-row and exact source membership precedes this rule.
Display-field differences continue to withhold the whole product's fee array.

Each new deletion records the explicit v2 `rule_id` in `changes.jsonl`, with its
exact source spelling in the existing derived amount-status proof. The May 13
receipt's rule totals and both adapters' source-hash bindings preserve that
identity. Existing v1 receipts and sealed candidates remain unchanged. The
structural change verifier accepts named v1 and v2 rules so retained v1 changes
can still be reconstructed; it rejects unknown deletion rules. Structural
restoration alone does not validate either version's original source proof or
retroactively apply v2 semantics to v1 evidence. The independent May 19 raw
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
