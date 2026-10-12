# Ready history compiler

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
