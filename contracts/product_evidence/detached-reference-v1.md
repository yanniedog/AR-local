# Held detached product evidence references

This pure adapter is not wired into daily publication, asset upload, pruning,
readback or the app store. It grants no selected-source or publication authority.
The separate snapshot, normalized delivery and original-response contracts keep
their existing scope and limits. All local test results remain source evidence.

`product_evidence_v1` and `product_response_evidence_v1` are optional top-level
manifest fields, never entries in eager `files`. Each has exactly:

```
schema: ar-product-evidence-reference-v1 | ar-product-response-evidence-reference-v1
source: {generation_id, observation_date, observation_state, contract_digest}
core_sha256: actual compressed core domain bytes SHA-256
details_sha256: actual compressed details domain bytes SHA-256
capability: {name, sha256, bytes, decoded_bytes}
```

Source fields must equal the selected manifest's explicit `source_observation`;
date also equals `run_date`. No fallback from absent source state to coverage or
zero failures. Held source states complete/partial/failed remain representable;
the operational publication policy must independently admit a selected source.

Capability filenames are exactly `product-evidence-capability-<64hex>.json.gz`
or `product-response-capability-<64hex>.json.gz`. The lowercase SHA-256 identifies
compressed domain bytes. Both compressed and decoded limits are 65,536 bytes.
The single gzip member decodes to canonical JSON of the existing held capability
schema. No extra URLs, encryption fields, unknown schemas or recursive references
are accepted. The capability commits its complete index/shard inventory. The
root manifest remains at most 65,536 bytes regardless of shard count.

`encode_reference` returns deterministic bytes without writing. `decode_capability`
checks declared limits before inflation/parsing and binds full capability source
and core/details to the compact reference. Database/snapshot/journal metadata
remain publisher attestations; a phone has not independently verified those full
source files merely by reading a hash-bound capability.

`verify_local_inventory(root)` requires a clean, isolated staging directory with
exactly `manifest.json` plus its direct and transitive assets, at most 1,024 files.
It reads every byte, verifies every fact route/original-body reconstruction using
the existing bounded readers, checks cross-lane bindings, and rechecks membership
and file identities. It rejects links and unbound/partial files; it does not use
writable locks or modify any source. It is not a validator for an archive with
reservation or other protocol-control documents. Runtime adapter integration must
define those control inventories explicitly, not silently ignore them.

Existing core 1 MiB/details 8 MiB/aggregate 16 MiB budgets apply unchanged to the
base asset inventory. Each explicit evidence lane retains its independent held
limits. Unknown namespaces cannot claim the exemption. The result reports base,
lane and full transfer totals separately, with `selection_verified=false` and
`publication_authorized=false`. A source generation ID and payload bundle
generation ID are different identities.

`immutable_asset_url` derives only fixed-repository, hash-bound adopted assets
under an exact immutable revision tag. A detached capability must reproduce its
reference digest before it can authorize index/shard URL resolution. Mutable
latest/dated aliases and observed-candidate routes are not evidence locations.
The existing ARE2 upload and authenticated data-service unwrap remain required;
this module neither uploads nor creates a plaintext delivery exception.

Before runtime wiring: independent selected contract/completion/raw-journal
adoption, exact app release qualification, complete transitive archive/readback/
prune integration, narrow secure-upload/immutable Worker route support, explicit
optional failure/retry policy, and source/selection fences are still required.
Missing optional preparation is not a complete-evidence claim. Once a namespace
is advertised, corruption or omission must fail that candidate, preserve the
prior edition and retain a truthful retry receipt.
