# Packed bank history transport

The producer emits `bank_rate_history_catalogue_packed` alongside the unchanged
`bank_rate_history_catalogue`. Neither capability belongs in the legacy eager
`files` list. Existing applications retain the original catalogue; applications
supporting the packed capability select it first.

The new namespace is `{schema_version: 1, file: {name, bytes, sha256, enc?}}`.
The name is `bank-rate-history-catalogue-packed-<date>-<sha12>.json.gz[.enc]`.
The descriptor deliberately contains no URL. Consumers derive the URL from the
validated manifest repository, release tag and filename. This keeps the bundle
hash compatible with older applications, which hash unknown namespaces verbatim,
and preserves the same identity when the revision coordinator retags a release.

The asset uses the existing gzip envelope:

```
{schema_version: 1, run_date, core_sha256,
 catalogue: {sha256, bytes, gzip_base64}}
```

The inner receipt describes the packed JSON bytes, not the expanded catalogue.
The packed document is `{format: "ar-history-dag-v1", root, nodes}`. Nodes are JSON
primitives, `[0, references]` arrays, or `[1, shapeReference, references]` objects.
A shape references an earlier array of unique string keys. References are unsigned
base64 VLQ using `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/`,
five data bits and continuation bit 5, with no separators. All references point
to earlier nodes, and the root is the final node. Nonminimal and truncated VLQ
encodings are invalid. Decoded containers can share immutable child values.

Limits match the application: one million nodes, four million edges, depth 64,
10,000 object fields, 64 MiB of string code units and 128 MiB of logical expansion.
The packed JSON has an additional 10 MiB decoded-byte limit. Both capabilities
count toward the existing 8 MiB overall compressed transfer budget. If the optional
packed projection exceeds its structural, decoded or transport budget, packaging
retains the legacy capability and reports the omission. Malformed data or receipt
failures remain errors; they are not treated as budget omissions.

Both formats retain every observation, source identity and evidence record.
Packing requires a lossless bounded round trip before emitting an asset. Release
inventory, immutable revision upload/readback, local validation, candidate app
proof inventory and mandatory ARE2 transport include the packed asset.

`tests/fixtures/history-dag-v1-interoperability.json` is a small cross-language
codec fixture, including shared values, Unicode and prototype-shaped JSON keys.
The producer tests also use retained real CDR observations. Before runtime
activation, test the complete cold application decode/validate/install path on
the intended device against the few-second processing requirement. Compressed
size and desktop codec timing alone do not establish that acceptance result.

## Runtime activation order

Code merge alone does not activate this capability. Follow the controlled Pi
recovery runbook and latest chronological handoff, preserving the pinned runtime,
Drive write hold and current ownership until the guarded transition is approved.
The runbook's production-environment approval requirement is at
`PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md`, Phase B, together with the immutable main
candidate and canary evidence requirements.

1. Deploy the reviewed automatic delivery service allowlist from
   `services/app-data/` and verify authenticated packed-asset routing and exact
   gzip bytes. Its explicit filename allowlist otherwise rejects the new family.
   Service deployment is separate from Pi deployment and requires the privately
   held hosting token; retain its prior version for rollback.
2. Validate the exact merged producer candidate, including updated consumer app
   proof for both asset inventories. Admit the controlled Pi transition through
   the shared task queue and production lease, respecting current resource,
   quiet-window, canary, approval and rollback gates. Then activate that exact
   candidate, not a moving branch.
3. Build and publish a new immutable revision from verified existing source
   observations. Preserve historical releases, upload assets before the manifest,
   and authenticate public service readback of both descriptors, envelope/core
   binding, bytes and hashes, selected manifest and rolling index.
4. Measure cold and cached native application processing, including validation and
   installation, against the few-second requirement. Record native and subsequent
   natural-cycle evidence separately from code, service and publication checks.

This activation does not create, enable, resume or start scheduled tasks and does
not resume Drive writes. Missing runtime evidence remains pending.
