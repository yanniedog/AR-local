# Declared document URL corrections

Retained Australian Mutual Bank and Central West CUL responses contain four
declared URI fields with literal `%20` prefixes. These previously disappeared
from document discovery, including fees and bundle references.

Discovery removes only leading `%20` groups immediately before an HTTP(S)
scheme in a declared URI field. `sourceUrl` retains the complete original
string, `sourcePath` retains its exact scope, and `sourceNormalization` records
`leading-encoded-space-v1`. Paths, queries, fragments and other escapes are not
decoded. General URL admission and acquisition network guards are unchanged.

This correction establishes a reference, not document applicability, complete
acquisition or a financial amendment. Old observations and evidence remain
immutable; this code does not rewrite historical archives or publish changes.
