# Original product-response evidence (held, source only)

This optional namespace preserves original **HTTP-content-decoded UTF-8 body
bytes**, including nulls, empty values, array order, numeric spelling and unknown
fields. It does not contain compressed HTTP wire bytes or headers. Normalized
fact evidence keeps its separate, narrower scope.

There is no daily publisher, selection, app-store or UI integration in this slice.
`prepared.json` explicitly sets `publication_authorized` and `selection_verified`
to false. A prepared package is not permission to publish or evidence that the
source is the current selected edition.

## Source preparation

`ResponseSources(snapshot_root, exports, contract_path, expected_binding=...)`
requires the existing normalized snapshot's exact binding, including database,
contract-file, generation and snapshot hashes and the caller's core/details
hashes. It verifies the contract-bound database, promoted journal inventory and
manifest, every event/key/body relationship, the complete hash chain and current
head. Reads never invoke journal recovery or writable `FileLock` initialization.
Input file identities and journal membership are checked again at completion.

Only successful, semantically valid anonymous public CDR product responses with
the correct provider endpoint and product identity are eligible. Request/response
versions are positive integers through2147483647 when known; missing metadata
stays unknown. The returned descriptor contains safe identity/version/event
fields, never header collections, peer addresses or request URLs. An explicit
`withheld` set of body digests can retain unresolved private bodies without
publishing or modifying them. There is no broad token-name regex that drops
legitimate product fields or links.

Current detail matching requires exact canonical JSON comparison against an
exported product row, including JSON boolean/number distinctions and dataset
identity. Two explicitly named legacy projections are supported: cleaned values
with official product links, and `detail_json` with source-document references.
Unknown projection versions cannot claim a current match. Distinct raw responses
that match the same export remain ambiguous; identical retries retain all their
event references. Commit sequence alone does not select the current response.

Routes report `matched`, `ambiguous`, `projection_unverified`, `index_only` or
`missing`. An index response never substitutes for a full detail. Cached products
without a current journal-bound body remain explicit gaps; previous generations
are not silently borrowed. These states concern captured source evidence, not
complete bank/product populations or real-world applicability.

## Package and readback

`pack_responses(source, new_output)` prepares `ar-product-response-evidence-v1`.
Bodies are grouped into deterministic SHA-addressed gzip shards. Large bodies
are split at valid UTF-8 boundaries; each chunk has an original byte offset and
size. The original complete-body SHA is checked after reconstruction. Raw JSON
is never reconstructed from parsed values.

The routing index binds products, original bodies, source events and chunk
locations. Full readback verifies all routes/chunks, body hashes, inventories and
immutable bindings before installing the completion marker. Interrupted or
failed output remains available for diagnosis, without a valid completion claim.
`verify_prepared(output, expected_binding=...)` independently repeats readback;
it still grants no publication or current-selection authority.

| Limit | Bound |
|---|---:|
| Namespace descriptor |64KiB |
| Routing index, decoded / gzip |8MiB /1MiB |
| Shard, decoded / gzip |4MiB /1MiB |
| Original body / UTF-8 chunk |32MiB /256KiB |
| Shards / chunks per body |256 /256 |
| Total decoded / gzip assets |1GiB /128MiB |
| Per-body acquisition decoded / gzip shards |64MiB /16MiB |

The raw-only8MiB index cap accommodates the measured4.15MB provenance index;
normalized-fact and global app inflation caps are unchanged. Future growth beyond
these bounds fails explicitly without truncation or a completeness claim. A
paged index is a later extension, not an automatic limit increase.

The companion app reader shares the bounded evidence reservation with normalized
facts, does not cache raw indexes, checks immutable edition/cancellation throughout
and downloads only the requested body's shards. A default read requires a unique
current body. Explicit alternate/index reads retain their distinct role and
uncertainty. Rendering, current publication binding, complete raw population
coverage, longitudinal alerts and physical-device performance need separate
integration and acceptance evidence.
