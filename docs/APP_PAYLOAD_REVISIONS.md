# Immutable app payload revisions

This is the additive v1 protocol owned by `app_payload_revisions.py` and consumed
by AR-app. It does not enable the separate v3 payload format.

## Activation and ownership

Keep `AR_LOCAL_PAYLOAD_REVISIONS=0` until the revision-capable app is shipped and
verified. Activation also requires `AR_APP_REVISION_CONSUMER_SHA` to contain the
40-character commit of that shipped consumer. A valid-looking SHA records the
operator's verified rollout decision; the publisher does not independently prove
an APK installation from the SHA alone.

The Pi is the single publication writer. The caller holds the production
operation lock through archive creation, index promotion, and dated/rolling
compatibility publication. The coordinator additionally holds a separate
publication lock. Its `state_dir` must survive deployments and observation
staging cleanup. There is no distributed GitHub compare-and-swap primitive:
publishing concurrently from another host is unsupported.

## Wire format

`dates-index.json` retains its existing fields and adds:

```json
{
  "revision_protocol": 1,
  "revision_heads": {
    "YYYY-MM-DD": {
      "revision": 1,
      "generation_id": "sha256-<bundle-sha256>",
      "manifest_url": "https://github.com/<owner>/<repo>/releases/download/app-payload-YYYY-MM-DD-r000001/manifest.json",
      "manifest_sha256": "<sha256-of-exact-manifest-bytes>",
      "bundle_sha256": "<bundle-sha256>"
    }
  }
}
```

Each archived manifest includes `payload_revision` with `schema_version: 1`,
`revision`, `generation_id`, `bundle_sha256`, and `parent_revision` (null for the
first selected revision). Every asset URL points to that same immutable release.
The supported revision range is 1–999999 per day.

Bundle SHA-256 uses canonical UTF-8 JSON: sorted keys, compact separators,
unescaped non-ASCII text, and no non-finite numbers. It includes every manifest
field except `generated_at`, `tag`, and `payload_revision`. File descriptors
include all fields except `url`. This binds every asset, coverage field, and
`source_observation`, including its export-contract and event identities.
Timestamp-only rebuilds are idempotent. Details, optional assets, provenance, or
coverage corrections advance the revision even if core rates are unchanged.

## Publication and recovery

1. Validate local hashes and reserve a durable revision number. Reuse an
   interrupted reservation only when its bundle and selected parent both match.
2. Before migrating a date, archive any displaced dated and rolling payloads.
   Preserve the original manifest bytes as `source-manifest.json` and every
   referenced asset; a rewritten manifest provides stable archive URLs.
3. Upload the new full bundle and product/rate delta without clobbering any
   existing archive asset. Download every object and compare exact bytes.
4. Preserve the exact predecessor index and a durable promotion intent. Check
   the public predecessor again, replace the selected index, and read back exact
   bytes with a fresh URL that bypasses stale GitHub redirects.
5. Publish the dated and rolling compatibility manifests from the verified
   archive, then verify their exact public bytes. Optional assets are never
   merged from another generation.

A killed index replacement can leave GitHub's mutable asset absent. On restart,
the coordinator restores the latest prepared predecessor (or the already
committed index when a receipt exists), without clobbering a newly appearing
index, then resumes normal verification and promotion. Missing/corrupt local
recovery bytes fail closed. An uncertain archive upload succeeds only after an
exact public byte match.

`revision-delta.json` contains added/removed/corrected product identities, complete
rate-row fingerprint multiplicities, and changed asset names. A removed row is
an observed difference; it is not automatically classified as a withdrawn
product. Reservations, archives, deltas, and publication provenance are retained.
Returning to an earlier bundle creates a new revision with the current parent.

The legacy refresher refuses to regenerate an index after public revision
adoption, including when an environment flag was accidentally omitted. Legacy
alias writes cannot downgrade a revision-aware manifest, and pruning only acts
on the rolling alias. Immutable revision and legacy-preservation releases are
never pruned by this publisher.

## Verification

`tests/test_app_payload_revisions.py` exercises retained real CDR product/rate
fixtures, details/optional/provenance-only changes, interrupted uploads,
interrupted index promotion, collision handling, downgrade refusal, and byte
preservation. These are protocol regression checks, not proof of a live Pi
deployment, public publication, installed consumer, or natural daily execution.
