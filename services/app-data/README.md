# Automatic app data delivery

AR-app users need no key, account or setup. This standalone service reads only
AR-local app-payload release assets, authenticates ARE2, and returns unchanged
domain bytes over HTTPS. It never returns release keys. Product data is accessible
to app users; encrypted GitHub storage does not prevent extraction by those users.
No existing website routes, Pi services, backup jobs or release assets are changed.

Verify with `node --test services/app-data/worker.test.mjs` (Node24).
Deployment requires the reviewed, merged tree and a hosting token held privately.
Use Wrangler with `--config services/app-data/wrangler.toml`; configure RELEASE_KEYS
as a secret JSON object mapping 32-character transport IDs to 64-character AES keys.
Retain historical keys. Pass secret values through stdin/private files, never CLI
arguments or logs. No package dependencies are required by the service itself.

The public endpoint is `/v1/release/<app-payload-tag>/<asset.json[.gz]>`.
Only GitHub release-asset redirect hosts are accepted. Time, redirect, stream-size,
per-isolate concurrency and per-IP rate limits are enforced. Current asset inventory
is below the 8MiB encoded-content cap; oversized future assets fail explicitly.
Content-Encoding is intentionally absent: frozen gzip bytes and hashes must survive
HTTP delivery unchanged. Mutable aliases cache for30seconds, revision tags for1year.
Historical ARE1 decoding additionally requires the exact frozen ciphertext SHA256;
the client first verifies its original size/hash before requesting that decode.

After local and hosted checks, deploy the compatible service, set secret storage,
and read back authentic current and historical manifests/core/details. Missing keys,
modified ciphertext, unknown paths and unsafe redirects must fail without data.
Only then release the compatible app. Do not replace signed native/runtime evidence
with these service checks. Roll back a service version using hosting version history;
retain the preceding version and encrypted GitHub assets throughout.
