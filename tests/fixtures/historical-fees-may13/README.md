# Retained May 13 embedded-export excerpts

`embedded-excerpt.json` SHA256
`9e4bc07d29cc32e21d28db638f9298d351f252f121fd44f8c94ef0e4521f8541`
contains 45 complete product records and their 919 flattened fee rows from the
retained May 13 bank export, SHA256
`5da7f5ebc1ee11591a062b086757a737d4da92c9fbc95e44e0214e38823b73d6`.
It includes every measured legacy value conflict, both discriminators for
variable-zero placeholders, null-marker bounds, discounts and the products with
the 38 pre-existing numerical rate normalizations.

Original export product/rate/fee array indices and public section row indices
are explicit in the fixture. The corresponding original public asset hashes
are retained in `anchor_asset_sha256`. Product `details_json` strings retain
their exact decoded UTF-8 content; source bindings use two-stage pointers into
that encoded string and its parsed object. Enclosing rows are exact parsed
subsets, serialized with decimal-preserving JSON. No original HTTP response is
supplied or fabricated; `source_file` remains an unverified reference string.

This is a deliberately labelled protocol-test excerpt, not a complete export,
published manifest, source calendar observation or financial acceptance result.
Tests inject malformed identities, indices, decimals and ordering only to prove
refusal or preservation boundaries. The actual candidate admission separately
requires the complete approved export, original public anchor, recovery
receipts and independently reviewed unpublished taxonomy parent.
