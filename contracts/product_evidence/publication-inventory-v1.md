# Complete evidence publication inventory (held implementation)

This slice extends delivery of an explicitly supplied frozen candidate. It does
not enable either optional lane, discover newly prepared packages, authorize a
source observation, change the selected generation policy, or deploy a route.

`app_payload_publication_assets.complete_assets(manifest, root=... | store=...)`
returns the entire finite tuple before exposing any descriptor. Financial-only
manifests retain the old iterator. Evidence manifests require paired explicit
status/references and the original capability gzip bytes. Capability descriptors
resolve every index/shard; missing, corrupt, unsupported or mismatched metadata
fails. The legacy iterator continues to reject these namespaces.

`verify_stage(root, expected_manifest_sha256=..., controls=None)` verifies every
asset hash/size, gzip/schema/routes, source/core/details binding and exact local
membership. Default staging is clean. Controls, if supplied by an owning
transaction, are explicit relative paths with exact byte counts and SHA-256;
they cannot overlap assets. The publication adapter independently recognizes
reservation/delta/provenance, promotion/predecessor, displaced alias, and v2
preservation receipts. Unknown files/directories fail rather than disappearing
from enumeration. All original bytes remain unchanged.

Root/capability limits stay 64 KiB; eager financial budgets remain unchanged.
The two lazy lanes retain their existing independent compressed/decoded limits.
Complete descriptors are bounded to 1,024 files and a 512 KiB receipt. Verification
has a 600-second bound. Local-only transaction controls are separately bounded
to 4,096 files, 128 MiB cumulative, 64 MiB per file; ordinary JSON controls remain
8 MiB each. Larger controls are only accepted from exact existing v2 preservation
asset descriptors. These controls are not added to upload lists or app downloads.

Revision reservation and bundle identity include strict optional status and refs.
Copying rechecks exact bounded asset bytes. Archive uploads include every declared
asset and put the manifest last; immutable readback uses ARE2. Consumer evidence
URLs are constructed from the fixed repository and a bound numbered revision.
The separate retention archive remains non-selected and cannot be routed by the
consumer Worker. Direct plaintext companion/bootstrap paths remain unsupported.

Alias publication verifies the actual encrypted selected head, immutable manifest
and complete asset set before advertising it. It enumerates authenticated GitHub
asset pages completely, rejects ambiguity/failure, and uploads at most 16 data
files per batch. Pruning remains disabled; unknown assets are preserved.

Optional retries can pass `expected_predecessor=<exact selected head>` to
`publish_revision_bundle`. Under the revision lock it rejects changed parents
before reservation. A previously selected identical candidate may resume only
after full selected readback, matching parent revision, and exact hash-bound
retained promotion/predecessor index evidence. The existing final index CAS and
source guard/fence still apply. This is not authority to replace another bundle.

Tests use retained real products/rates/facts/original bodies and offline protocol
faults. They are not Pi, public delivery, shipping app or device acceptance.
Daily frozen-candidate preparation/retry integration and coordinated app/Worker
release remain separate held dependencies; no environment flag is enabled here.

## Compatibility alias storage

The complete local inventory and the selected immutable manifest **and every
asset** must verify before an evidence-bearing compatibility alias is mutated.
Detached capability/index/shard URLs resolve only to that immutable revision.
The dated/rolling aliases therefore copy and verify their financial assets but
do not duplicate lazy evidence files. Their manifest remains identical to the
selected immutable manifest; capability references and bundle identity do not
change. Mandatory full immutable readback, encrypted financial alias readback,
source/selection guards and promotion fences remain independent requirements.

No remote objects are deleted. Complete authenticated listing and the finite
100-page bound remain; prior duplicates/unknown objects are preserved. Financial
alias asset growth still needs separately reviewed retention before service
limits are reached. This storage optimization creates no deployment authority.
