# Isolated observed-population publication

`app_payload_observed.py` is a transaction adapter, not an automatic publisher or
ingest repair. It publishes only independently accepted immutable candidates in
`yanniedog/AR-local`'s `observed-population-v1` channel. It never modifies legacy
discovery, aliases, operational receipts, source holds or Drive. The delivery
service and app's explicit capability activation are separate changes.

## Coordinator contract

The caller supplies an `Acceptance` containing the exact manifest SHA256, private
one-day index SHA256 and original `source_observation` from completed independent
source-closure and consumer acceptance. Computing those hashes from an arbitrary
new fixture does not establish acceptance. The adapter preserves financial bytes,
source date, partial state, counts and provenance; it does not resolve unknown
provider membership or independently redo domain/accounting validation.

```python
from app_payload_observed import (
    Acceptance, ObservedStore, load_candidate, publish_candidate,
)

# Paths and accepted bindings come from the admitted coordinator's exact evidence.
manifest, _, _ = load_candidate(candidate_dir, accepted)
receipt = publish_candidate(
    candidate_dir, private_state, accepted,
    production_lock_path=production_lock, store=ObservedStore(manifest),
)
```

Use a qualified runtime with the existing publisher service environment and key
storage. Never print/export/recreate keys. The supervisor retains the existing
shared queue, window, resource and ownership gates. The function acquires the
global production lock itself; do not nest that non-reentrant lock. All publishers
must share it because GitHub does not provide compare-and-swap for release assets.
Persistent state must be private coordinator-owned storage outside the immutable
candidate, preserved across interruption and rollback. The state directory
and the production lock (including its recovery control file) must be disjoint
from the candidate and from each other: equality or containment in either
direction is refused before lock acquisition or staging. Paths must be canonical,
without symlink aliases; existing lock/control files must be singly linked regular
files. Coordinator-owned parent directories must remain stable during publication.
Each new state directory is created with POSIX mode 0700 under an already existing
parent. Existing state
directories must have that exact mode and belong to the current effective user;
otherwise publication refuses before staging or egress, without changing existing
permissions. Publication is unsupported on non-POSIX platforms: mode bits do not
establish Windows ACL privacy. No CLI, timer or automatic activation is introduced.

Backends must explicitly implement `ObservedBackend` and validate their exact
candidate reservation before staging. The ordinary `GitHubRevisionStore` and
uncontracted duck-typed objects are rejected before even acquiring the publication
lock. The real `ObservedStore` verifies repository, edition, reservation metadata
and asset allowlists against the accepted candidate; this preserves prerelease
and encryption behavior rather than accepting a generic legacy backend.

## Commit ordering and recovery

1. Validate exact accepted canonical bytes, source date/identity, isolated URLs,
   bundle/revision identity and core/details descriptors. Additional capabilities
   are unsupported. Construct and validate the final index within 1 MiB, retaining
   all previous date heads, before reserving the local transaction or egress.
2. Persist exact predecessor/target index bytes. Reserve or verify the immutable
   prerelease by metadata binding to the accepted manifest and source identity.
   New releases use `--prerelease --latest=false`; incompatible occupied tags fail.
3. Upload ARE2 core/details, then manifest, without clobbering immutable assets.
   Authenticate/decrypt remote bytes and compare every asset to accepted originals.
4. Recheck the predecessor, then replace only
   `app-payload-observed-v1-candidate/dates-index.json`. Every observed-store read,
   including inherited commit/recovery checks, requires ARE2. Verify exact final
   index bytes before writing a success receipt.

Retries retain exact reservations. Interrupted uploads use authenticated readback;
missing-index crashes restore only the recorded predecessor before continuing.
Changed predecessors, rollback, revision collisions and corrupt bytes fail. Never
erase transaction state to bypass a refusal. A same-day existing head must match
the candidate's parent revision before advancement. A first index may select R2
whose R1 parent is preserved privately; this does not claim R1 was ever hosted.

The immutable tags are `app-payload-observed-v1-YYYY-MM-DD-rNNNNNN`. The mutable
candidate tag contains only the isolated index. Legacy clients must not discover
these tags through the legacy index, routes or caches. Use the dedicated service
path `/v1/capabilities/observed-population-v1/release/<tag>/<asset>`.

## Validation and rollout limits

Run portable protocol controls with:

```sh
python -m pytest tests/test_app_payload_observed.py -q
```

These use retained real May19 products/rates from existing repository fixtures;
only publication-protocol metadata and faults are constructed. They are not
source-membership, observed-population domain or installed-app acceptance.
Encryption/backend controls use synthetic keys and mocked wire/CLI transport,
never real credentials or network requests.
On Windows, protocol tests explicitly substitute the private-directory seam; they
do not claim Windows ACL or POSIX filesystem validation. Separate real POSIX tests
verify creation mode, ownership and refusal without permission rewriting on Linux.
Non-POSIX production refusal and pure mode/owner predicates are tested separately.

For the separately accepted private Nov3 R2 fixture, set
`AR_OBSERVED_PUBLICATION_FIXTURE` to its unchanged directory and run the same suite.
The fixture manifest is independently pinned to
`1e171689f3e0a3492ed748ffcd41b31fe79c3f33c94051120190cf6aa8767281`, and its one-day
index to `ed3a14dd5599c19ab9fa303c64034dfd258e89633ef58dc2f9cb7305509299b5`.
The fixture's original source generation is `obs-2026-11-03-7081ca4414e37e42`,
contract digest `a314f09195bb69dbf07d4e35191514c43c3d927df1a7cf9cf6e16cfe89042630`.
No private financial fixture is added to the repository.

Publication receipts explicitly leave hosted isolation and native activation
false. Hosted cold/warm cache tests in both request orders, old/versionless route
rejection/isolation, exact legacy pre/post hashes, actual native storage/refresh
and visible partial/unknown disclosure remain separate acceptance requirements.
Archive-only retention does not advance the installed app's date. Only the
compatible app explicitly selecting the verified isolated edition does that.
