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
