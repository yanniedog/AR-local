# Optional terms delivery

`build_payload(..., terms_root=..., source_observation=...)` can package already
published current terms projections. `build_and_publish_dual` accepts the same
optional root only in immutable revision mode, with the existing shipped-consumer
gate. No environment variable automatically enables delivery. The consuming app
must support terms index schema 2 before activation.

The evidence database is opened with SQLite `mode=ro` and `query_only`. Its complete
capture receipt must match the payload's generation, contract digest and source
run date. Every included publication must still belong to the current exact
observation and equal a freshly validated projection. A stale projection fails
the build; absent publications stay absent. This path creates no interpretations,
reviews or local publication records, and cannot attach today's terms to an older
source generation. Unverified applicability and calculation coverage stay unknown.

Terms index schema 2 maps product keys to `terms_shard_NNN` manifest keys. Each
shard is `{schema_version: 1, run_date, products}` with ordinary product-terms-v1
values. Every shard is a top-level manifest asset, included in bundle identity,
archive upload and download verification. There are no nested release URLs to
rewrite during immutable revision reservation. The app resolves descriptors from
the selected manifest, verifies exact compressed bytes and each product's canonical
identity, and fetches only the selected group. Legacy index schema 1 remains valid.

Existing transfer limits remain unchanged: 64 KiB manifest, 1 MiB for each optional
compressed asset and 8 MiB total. Additional limits are 20,000 products, 512 KiB
uncompressed per shard, 24 MiB cumulative input and 512 MiB retained-blob verification
work. Exceeding a limit fails explicitly instead of dropping terms. Encrypted
payload mode refuses terms until its consumer channel supports that combination.

The opt-in builder does not itself deploy, activate collection, authorize a release,
or prove complete legal coverage. Dedicated Pi ownership, persistent Drive hold,
consumer/native testing and controlled publication remain necessary.
