# Ready history compiler

## Current proposed producer artifact (2026-10-31)

The compiler and manifest in this checkout are exact Git blobs from AR-app
release `app-v1.0.256`, source commit
`0f217f0a573dd072c019bef93b26f3b71d038d7d`. The compiler SHA-256 is
`c6d1ff733a579a5fef1d17105922aee20bf73d96e66adc60aaa637ff2c1cec9b`.
Use this pair for regeneration and candidate validation; the older pins below
are historical records, not alternative current artifacts.

The released app's unchanged validator accepts output from this compiler.
Independent compilation of the verified October 31 catalogue matches the
released app's TypeScript compiler exactly, with source dates, products and
cohorts preserved. This establishes local compatibility, not Pi commissioning:
the producer change is not deployed, a corrected public revision has not been
published, and device acceptance has not been established by these tests.
Complete controlled deployment and publication acceptance before treating this
producer artifact as commissioned. See `docs/PACKED_BANK_HISTORY.md`.

## Artifact regeneration and validation

`compiler.cjs` is a generated standalone artifact from the reviewed AR-app
TypeScript source, including its exact access and feature classifiers. It is
intentionally retained as one executable bundle rather than manually splitting
generated code; authored code remains in AR-app. Node.js 24 or newer is required.
The compiler does not access the network, credentials or production storage.

Regenerate from the matching AR-app checkout after deterministic `mobile/`
dependency installation:

```sh
cd mobile
node scripts/export-history-ready-compiler.cjs
node scripts/export-history-ready-compiler.cjs --check
```

Copy both `mobile/contracts/history-ready/compiler.cjs` and
`compiler-manifest.json` here without changing bytes. The manifest records source
and exporter hashes. The producer checks the artifact SHA before each invocation;
the CLI stamps that SHA into the compiled result. Both repositories preserve
literal artifact bytes across Windows and Linux checkout.

The default CLI reads a raw validated historical catalogue on stdin and writes
ready cohorts/products to stdout. `--validate` checks ready input against the
same bounds and exact compiler SHA, returning `{"valid":true}` only on success.
Inputs, outputs and runtime are bounded by the Python integration. Failures defer
publication. The consumer must support this reviewed compiler pin before adopting
a new producer artifact. Do not regenerate it as an incidental deployment step.

`tests/fixtures/history-ready-real.json` is reproduced from retained real CDR
observations by the producer tests and also exercises authenticated service
readback. The app additionally checks exhaustive profile parity and native
processing performance. Neither a compiler hash nor tests prove publication.

Bundled third-party code retains the licenses in this directory.

## Historical LVR interval candidate (2026-10-15)

The October 15 LVR interval change exported compiler SHA-256
`7d717bdf3a86289876a1c5dee238df1d0e79df0634feaa0a499b2199246ab5d7`
from the matching AR-app source. Its producer and consumer copies were identical;
its retained-real fixture was regenerated from unchanged source observations.
This was a reviewed-code compatibility candidate, not a commissioned APK.
The consumer was AR-app PR #400; this compiler was exported from source commit
`cbf88fbc8cca5c3e1fb3f71c1b85780a9e1228b5`.
It integrated the redesigned consumer from AR-app main at that time and superseded
the uncommissioned `19ab1892...` candidate in AR-local PR #932; the retained-real
output changed only its compiler receipt, preserving its source observations
and prepared semantics. It also included the reviewed app corrections for
choosing the narrowest interval and filtering calculated LVR per rate without
saved-profile fallback outside published bounds. A candidate pin is not evidence
of publication.
At that time, publication required the matching app consumer to be separately
released and verified. The October 12 evidence below did not commission that
October 15 candidate. Neither historical record commissions the proposed
October 31 producer. See `docs/LVR_INTERVAL_CONTRACT.md`.

## Historical commissioned consumer evidence (2026-10-12)

This section preserves the October 12 record; it does not describe the artifact
currently in this checkout or commission the proposed October 31 producer.
The producer artifact at that time was copied byte-for-byte from AR-app's reviewed compiler
with SHA-256 `5f27f0b70b89efe7adf76d0d93a97b2c779e1953ff870efd018c14961fa17a6e`.
Both recorded commissioned app sources carried those compiler and manifest bytes:

| Consumer | AR-app source commit |
| --- | --- |
| Universal Android | `e2e375368bf5963eb6619748f806b41689c3d176` |
| ARM Android | `4fd25f679539db50a99623bb7558d0d4e95b64a9` |

The corresponding shipped Android bundles were independently read back with
SHA-256 `8a22721a42e9d797419b096082691bb509c235e2f05a24bde436285087ac6e1a`
(universal) and `f79b6ce4c554f271afaef3af620fca335465d57c34d323557c3b4a211c27fa53`
(ARM). Each contains the new compiler pin once and the previous pin zero times.
Bundle hashes identify this readback; they do not establish device acceptance.

This compiler includes the ordinary-employment eligibility correction from
[AR-app #360](https://github.com/yanniedog/AR-app/pull/360), commit
`a112964183b6bfccf2e16ff0b09812dbeaf03400`. The previous `fbd65b58...` pin has
different classification semantics and is not an accepted equivalent. The
retained-real fixture is regenerated from the unchanged source observations;
for those observations, only its compiler receipt changes.

Consumers enforce an exact compiler pin. Older apps with the previous pin
reject the new optional prepared asset and retain their bundled/retained
fallback; they do not gain fresh prepared history from it. The legacy raw
catalogue and optional packed catalogue remain available to consumers that
support those formats. Core data remains independently usable. A later compiler
update requires a matching reviewed consumer and a new compatibility check;
changing this producer artifact alone is insufficient.

The independent consumer-pin regression in `tests/test_app_payload_history_ready.py`
must advance with that reviewed contract. Run the exporter `--check` in a
checkout with its own deterministic dependency installation: a dependency
junction into another checkout changes generated module paths even when all
dependency bytes match.
