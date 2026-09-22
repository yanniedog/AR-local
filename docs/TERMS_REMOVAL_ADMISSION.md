# Term removal admission

A failed fetch, vanished link, changed URL or complete extraction is insufficient
to remove a term. Original revisions and documents remain append-only.

An independently reviewed removal receipt must bind the before/after revision
pair and retain `passed: true`, `kind: removed`, and
`full_replacement_validated: true`. It must also contain:

- `replacement_applicability`: the exact previous term applicability, including
  product, tier, package, cohort and effective bounds.
- `replacement_parameter_keys`: distinct parameter keys explicitly covered by
  the reviewed replacement, including the removed parameter.
- `replacement_observation_id`: the current accepted product observation.
- `replacement_document_version_id` and `replacement_extraction_id`: the exact
  retained version and complete extraction applicable to that observation.

The replacement's latest observation-bound acquisition must be successful and
still select that version. Neither acquisition nor extraction may postdate the
removal observation time. Original document, extraction text and product source
blobs are revalidated. Unchanged original versions cannot prove a bank amendment.

These mechanical checks do not establish legal replacement authority. The
independent reviewer must establish scope and completeness from source evidence;
unknown applicability remains unknown and must never be guessed or treated as
universal scope. Incomplete old-format receipts fail closed until supplemented.

Change validation and insertion share one immediate transaction, preventing an
intervening source or review write. The controller refuses an existing caller
transaction without committing or rolling it back. Repeating the same admitted
receipt is idempotent. This operation does not publish, deploy or delete evidence.
