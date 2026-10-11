# Direct GitHub app delivery

**Historical migration record, superseded on 2026-10-11:** the operator selected
Cloudflare app-data delivery. Production packaging no longer emits the direct
delivery marker, and canonical revision publication never invokes the public
companion, including retries of previously marked editions. The public branch
and bootstrap tools remain preserved; they are not an active publication or
release prerequisite. Do not delete already-published bytes. The procedure below
documents the retained migration implementation, not current deployment authority.
See `services/app-data/README.md` and `PACKED_BANK_HISTORY.md` for current delivery.

New apps read `https://raw.githubusercontent.com/yanniedog/AR-local/app-payload-public/`.
This dedicated orphan data branch contains only validated app inventory:

- `tags/<canonical immutable tag>/<declared asset>` and its exact `manifest.json`.
- `latest/manifest.json` and `latest/dates-index.json`.

Canonical tags remain `app-payload-YYYY-MM-DD-rNNNNNN`. Manifest release URLs,
sizes, SHA256 receipts, source identities and revision bindings remain canonical;
only the app's transport adapter maps them to the raw data branch. Raw GitHub
supports browser CORS, so web and native use the same path without a Worker.

New manifests declare `delivery: {"mode": "github-public-v1"}`. Their domain
assets are ordinary gzip, with no inner ARE1 encryption. Existing canonical
build configuration requesting inner ARE1 is rejected explicitly and must be
disabled before adoption; it is never silently ignored. Existing canonical
release publication still requires authenticated ARE2 transport and retains its
encrypted releases for older apps. No key is embedded in either app or branch.
The initial migration may mirror an existing unmarked manifest unchanged.

The publisher enumerates the validated manifest, including declared optional
assets, and rejects private control files, encrypted descriptors, symlinks,
incorrect sizes/hashes and unfrozen contract families. It never uploads a
directory glob. Private provenance, preservation, source/base manifests, deltas,
logs and archives remain excluded.

Publication creates Git blobs, a tree retaining all previous immutable files,
and a commit. Every intended object is read back by commit SHA before a single
non-force branch update exposes both selectors. Existing immutable bytes cannot
be replaced; index regressions, conflicting heads and concurrent writers fail.
Both selectors are then read back by branch name. A partial failure preserves
the previous public selection or records an unconfirmed readback; retrying the
same canonical bundle repairs the public mirror. Raw availability of a staged
commit is a live gate, not something unit-test stores establish.

## Initial transport-only migration

Run from the reviewed merged producer source. First prepare an exact snapshot:

```text
python app_payload_public_bootstrap.py --output <private-staging-directory> --state <private-receipt-directory> --expected-manifest-sha256 <reviewed-current-head-sha256>
```

The default reader authenticates published ARE2 using the existing private local
key configuration. If only the existing authenticated delivery service is
available, `--legacy-service-migration` explicitly selects it as a one-time
migration source. This option does not configure an ongoing publisher or app
fallback. Every manifest and asset must still match its canonical receipt.

After code, tests, review and current-selection checks, repeat the same command
with `--publish`. It authenticates the complete inventory again, stages and
verifies its Git objects, rechecks the canonical index immediately before
promotion, and writes a receipt only after public selector readback. It holds a
local bootstrap lock and uses a non-force public branch update; it does not
acquire a Pi lease or modify any Pi runtime, release revision or schedule.
Canonical selection changes abort the attempt rather than mirroring stale data.

Populate and verify the current public branch before releasing the app that
requires it. Initial migration includes only the current selected immutable
edition and complete index; historical heads remain receipts. READY supplies
historical rates without fetching every old core. Older uncached optional assets
may require a current refresh. Historical ARE1 editions are not rewritten.

## Historical subsequent prepared-history activation plan

After the consumer app is shipped and verified, follow `CDR_QUALITY_PIPELINE.md`
and the controlled Pi canary/seal process for the exact producer candidate.
Publish a new immutable revision carrying READY, verify both canonical ARE2 and
direct public bytes, then measure complete native payload processing. Code
merge, public bootstrap, native timing, Pi adoption and subsequent natural-cycle
evidence are separate gates. No Cloudflare deployment is required for new apps.
Do not create, enable, resume or start scheduled tasks or resume Drive writes.
