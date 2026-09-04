# Frozen payload v3 contracts

These schemas, fixtures, and `contract-lock.json` are retained as immutable
compatibility evidence for historical AR-app/AR-local work. They are not an
active producer, publication path, or deployment target.

Runtime v3 generation and promotion code was removed during the AR-local
simplification. Reintroducing it requires a separate reviewed implementation,
an exact producer/consumer contract match, immutable publication storage, and
new activation approval. Do not reinterpret these frozen files as permission to
publish.

`contract-lock.json` binds the canonical JSON of the five listed schemas. CI
checks that every schema remains valid Draft 2020-12 JSON Schema and that the
set digest still matches the lock. The checked-in fixtures remain examples of
the frozen wire format only.

Financial units remain part of the compatibility contract: product rates are
fractions per annum, RBA rates are percentage points, changes are basis points,
and fee percentages are fractions of the charged amount. Unknown values remain
null or explicitly unknown; they are never inferred as zero.
