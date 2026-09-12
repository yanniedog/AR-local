Eight retained Bankwest Easy Saver product/rate slices, extracted read-only on
2026-09-13 from September 6–12 primary exports and the selected September 13
revision `obs-2026-09-13-3016aa9b4dff9f26`.

Fixture SHA256: `79a2e923685ea9a7f021dc9a1572986c13edbf8c23e9e0eabec1cdc0db73c941`.
The extraction completed in 9.6 seconds with unchanged before/after source stat
identities, indexed queries bounded to one product and 100 rates, and two-second
statement deadlines. Each day has one product and 13 rates. The fixture retains
the original marker/contract hashes, contracted SQLite descriptor and exact
selected product/rate fields. Empty/absent WAL and rollback journals permitted
read-only immutable SQLite connections. No provider request or source write was
made. Whole database hashes were not recomputed by this bounded extraction;
the contract descriptors are recorded provenance, not a new full-source audit.

The original rows mark 0.115 standard on September 6–12 and non_standard on
September 13. The ordinary 0.05 remains standard on all eight days. Every day's
retained details contains the actual restriction. Projection tests add only
the parent product's retained category to its SQLite rate rows, matching the
banks.json representation, and preserve all actual prices and conditions.

The current public v2 manifest was separately downloaded and verified:
SHA256 `4311b9aabdb5379616c03d06116970fd388fbd209a63132237cc06ab082e3167`,
generated `2026-09-12T21:19:22Z`, selected product history 132488 bytes/SHA256
`6f17f3649829389e06eb9fd43740c5ab7cc9f2ba174c788b85b417e7056602e4`.
It contained an artificial September 13 movement of -650 bps from 0.115 to 0.05.
This regression repairs derived standard-cohort history without rewriting any
observation or assuming that a missing ordinary rate is zero.

Malformed identity/absent-detail cases and the relocated direct-tier information
case are explicit parser/metadata fault controls, not financial acceptance data.
