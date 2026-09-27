# AR-local payload contract for AR-app

AR-local is the data producer. The installable Expo application, APK build,
updater, and app-release automation are owned by
[yanniedog/AR-app](https://github.com/yanniedog/AR-app).

## Repository boundary

| Concern | Owner |
| --- | --- |
| CDR discovery, ingest, normalization, history, and provenance | AR-local |
| Payload construction and publication | AR-local |
| App source, bundled offline fixture, user interface, and app tests | AR-app |
| APK signing, builds, updater metadata, and app releases | AR-app |

Install and release instructions must always point to the
[AR-app README](https://github.com/yanniedog/AR-app#readme) and
[AR-app rolling install release](https://github.com/yanniedog/AR-app/releases/tag/app-apk-latest).
Historical AR-local app tags and release assets are retained as history, but are
not the current install channel.

## Production payload flow

```text
CDR providers -> AR-local ingest -> finalized exports -> app_payload.py
                                                     -> app-payload-YYYY-MM-DD
                                                     -> app-payload-latest
                                                     -> AR-app client
```

The producer reads finalized exports and packages the current schema-v1 app
payload. The rolling manifest is published at:

`https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json`

Immutable dated releases use `app-payload-YYYY-MM-DD`. The rolling release also
owns its dates index and optional compact history assets. Publication is derived
from real finalized exports; AR-local has no committed app sample that may be
republished as production data.

The v1 payload surface is implemented by `app_payload.py`,
`app_payload_build.py`, and the related payload modules. Dormant v2/v3 contracts
remain versioned separately and must not be advertised as the active app contract
until their capability and promotion gates are enabled.

## Build and verification

Build a payload from a finalized run export:

```bash
python app_payload.py build \
  --exports runs/<date>/_exports \
  --out runs/<date>/_exports/app-payload
```

Publishing remains opt-in through the guarded daily producer path. The
`AR_LOCAL_APP_PAYLOAD=1` environment switch and release credentials are managed
by the existing Pi installation scripts. A publication failure is non-fatal to
the ingest, and operators must verify the resulting manifest and immutable dated
release before treating data as available to consumers.

Run the complete producer suite before changes merge:

```bash
python -m pytest tests/ -q
```

The `app-ci` workflow runs that same full Python suite for relevant producer
changes. App-side compatibility, rendering, and APK verification belong in
AR-app CI and release processes.

## Change coordination

Changes to manifest fields, asset names, URLs, compression, encryption,
rate units, taxonomy, product identity, or history semantics are
cross-repository contracts. Update and test the AR-local producer first, then
make the matching consumer change in AR-app. Do not restore a local app tree or
sample-to-production publisher in this repository.

## Deferred bank rate history capability

The critical schema-v1 core excludes both raw history namespaces and retains its
512 KiB compressed limit. The optional catalogue is outside `manifest.files`, so
older installed clients ignore it instead of eagerly downloading and parsing it:

```json
"bank_rate_history_catalogue": {
  "schema_version": 1,
  "file": {"name": "bank-rate-history-catalogue-<date>-<sha12>.json.gz",
           "bytes": 123, "sha256": "<asset hash>", "url": "<release URL>"}
}
```

The file is ordinary gzipped JSON with this envelope:

```json
{"schema_version":1,"run_date":"YYYY-MM-DD","core_sha256":"<manifest.files.core.sha256>",
 "catalogue":{"sha256":"<decoded inner JSON hash>","bytes":123,
              "gzip_base64":"<canonical padded base64 of gzipped inner JSON>"}}
```

The inner catalogue remains schema 2: historical tier descriptors, date-scoped
evidence and spans, plus exact source receipts and explicit unavailable dates.
Canonical inner JSON uses sorted keys, compact separators, unescaped UTF-8 and
no nonfinite values; gzip has mtime zero. The outer descriptor's hash/length bind
the stored gzipped envelope (or legacy ARE1 encrypted file when `enc` is present).
`core_sha256` always binds the final core descriptor, including its ARE1 hash when
applicable. ARE2 release transport wraps these unchanged domain bytes, including
manifests, indexes and the optional asset; authenticated readback remains required.

The outer archive is limited to 8 MiB compressed and 24 MiB decoded. Its inner
archive is limited to 16 MiB compressed and 128 MiB decoded. Both decoded length
and SHA-256 must pass before adoption; strict source/tier/evidence validation is
unchanged. The existing total release budget remains 8 MiB. Consumers validate
the asset basename and exact trusted repository/tag URL, then fetch, verify and
decode after first paint. Network/cache failure must preserve currently verified
history while leaving current-core authority and correction checks intact.

Revision identity includes this complete optional namespace except `file.url`,
the same routing-only exclusion used for legacy file URLs. Archive and preservation
retagging changes only that URL; hashes, byte counts and encryption metadata stay
bound. Publication uploads and verifies the asset before selecting the immutable
revision or advancing an alias. Exact-candidate app audit must include the optional
asset in its inventory before Pi activation can pass; producer merge alone is not
runtime or installed-consumer acceptance.

`app_payload_prepack_history.py` builds the same contract from byte-verified
selected public core/details inputs into a new private output directory. It emits
the slim core, unchanged schema-2 catalogue, gzipped envelope and verification
receipt. It has no credentials, network, publication or revision-selection path.
