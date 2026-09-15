# SQL002 draft review notes

DESIGN ONLY, 2026-09-15. Companion to ../MONETARY-STORAGE002-PRODUCER-DESIGN.md, not a competing design. No SQL executed, database opened, source approved, repo edited or runtime changed. SQL is deliberately unapplied pending producer review/freeze and isolated verification.

## Revision2 policy rereview

Both prior findings are resolved: monetary-wire3-draft/README.md revision2 requires private all-opening-funds-cleared confirmation if any interval uses cleared_only, with false/missing/unknown refusal. Complete postingInventory.dueDates must equal all source-derived dates; interval posting sets must agree without omissions/duplicates, and requested period filtering is start-inclusive/end-exclusive. No further policy review performed here.

## Baseline and additive changes

Baseline inspected producer HEAD d01f350274857abdd258ade46ebde8250a60f0b5. Frozen001 file contracts/product_terms/drafts/eligibility-v2/001_executable_registry_v2.sql raw SHA256=3b7b03fab6df44df146fdede08ad75d8687918e18e17560478323035e7e3c560. Preserve those bytes and the existing001 marker/receipt. This draft adds v3 tables and dependency links, CAS/collision/immutable triggers and atomically replaces only the two shared read views. No old row copying or normalization.

The SQL follows producer metadata naming executable_registry_migrations_v3. Its002 marker references001, records both DDL identities plus preservation/schema receipt identities. The extra metadata table is necessary because frozen001 marker has a singleton CHECK; it is not another approval registry.

Subjects record exact wire_version/capability/kind/adapter/evaluator and compare JSON projections. Scope identity remains capability+canonical scope, so a future reviewed policy successor can replace its same capability/scope without kind silently creating a second slot. Initial controller allowlist is ONLY (3,savings_calculation,aud_savings_base_period_v1,aud-savings-base-v1,product-terms-engine-v8); reserved storage capability names confer no execution authority.

Historical observation/authority/document/revision/member links support exact dependency revalidation. They must equal the canonical subject graph inventories, never a partial subset. Official-clause authorities must not gain manufactured observation links. Blob hashes are verified through the existing content store; SQL does not invent a FK to a nonexistent blob table. Current routing observation is separately checked against product/generation.

## Removal choice — root decision

Keep public asset.subjects minItems=1. An internal append-only publication state=removed has NULL payload_json; it is not a public asset. Hash its typed controller tombstone preimage (schemaVersion3, capability, productKey, exact routing observation, state=removed) into identity_sha256, and include identity/predecessor/time in publication_id as for active records. A removal requires a fresh validated current candidate-set read: explicitly negative dispositions or no current eligible slots, never treating unresolved/unreviewed/source-invalid candidates as removed. Active invalid candidates fail publication.

The packager reads latest per-product/per-capability publication. A removed product is omitted from the newly built capability index; omit an empty capability route. Never fall back to an older positive row, v2 eligibility, or another capability. Existing adopted edition retains its as-of semantics until a new verified edition is adopted; current handles/results then invalidate. Savings removal must leave unrelated products/routes and frozen v2 usable. Add those exact packager/current-selection controls before implementation acceptance.

## Transaction and resource obligations for migration implementation

Use producer's single migration/controller entrypoint. Check foreign_keys=ON and no caller transaction, then BEGIN IMMEDIATE BEFORE reading either marker or inspecting installation state. Recheck001/002 under lock. Existing002 with exact DDL/schema identity is idempotent only after verifying expected installed objects; mismatch/partial install refuses. Run the SQL statementwise; never executescript. Marker is last, in the same transaction as view replacement, immutable triggers and verification. On any exception roll back everything; concurrent first initializer sees completed002 after acquiring lock. No downgrade/drop-data path.

Stream every baseline v1+v2 raw row in stable rowid order, preserving SQLite value types, JSON text bytes and sequence values in a typed digest; do not decode/reserialize embedded JSON. Precheck raw column byte sums before fetching each row: max1MiB/row, max100000rows per table, max32MiB aggregate retained verification input; exceed => bounded refusal, not sampling. Check actual encoded digest-record size too. Snapshot each original table/index/trigger definition and sqlite_sequence entry, and old view definitions/old-column outputs. Compare before/after inside the SAME write transaction. Old definitions/rows must be byte-identical; only new trigger objects and intended view definitions may differ. Stream old-column view outputs for equality. PRAGMA foreign_key_check must yield no row (do not fetchall). Store immutable compact receipts; blobs left by rolled-back attempts are unreferenced evidence only, never proof of applied migration.

Current lookup: filter product+capability+exact current routing observation, select MAX(sequence) per scope, THEN LIMIT33; reject33 rather than truncate. Missing approval on a staged successor blocks the old approved subject. Reviews require independent actor, source/authority graph/benchmark check and exact predecessor under write lock; negatives remain possible after source drift. Revalidate both current routing and historical dependencies on read/publish. Publication CAS partition is product+capability. No global sequence ordering across v1/v2/v3.

Required isolated checks remain those in producer design, plus: rollback during DROP/CREATE VIEW; idempotent002 detects missing trigger/view; byte-preservation including JSON whitespace/Unicode and sqlite_sequence; raw-row bound before fetch; exact graph/link inventory; wrong capability JSON/stored projection; internal removal versus public empty asset; unrelated route/v2 availability after removal. This draft has not run those checks and must not be described as a migrated database.
