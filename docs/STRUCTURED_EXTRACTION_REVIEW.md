# Private structured extraction review

This controller protocol retains supplied transcription candidates and explicitly
reviewed table/header/unit/footnote associations. It does not run OCR or a renderer.
`tool_status` remains `tool_unavailable`; a candidate is never tool execution proof.
It does not establish bank applicability, complete document coverage, or calculation
acceptance. D003/T008 still need actual pinned-tool, corpus and runtime evidence.

## Explicit controller sequence

1. Initialize the additive private tables with `structured_store.migrate(store)`.
   Opening an EvidenceStore does not apply this migration. Original tables and
   frozen registry, staging schemas and executable SQL001/002 remain unchanged.
2. `structured_review.create_job` binds a retained PDF version, parent extraction,
   original/text/coverage hashes, selected pages, actor and time. No acquisition
   occurs. Candidate admission retains untrusted supplied page text and unknowns.
3. `propose` validates the closed `structured-review-v1.json` contract. Reviewed
   text has distinct page-relative regions; each cell names its headers and units.
   Every qualifier names its marker, note, targets and relationship explicitly.
   Unknowns remain explicit and prevent positive review.
4. A separate human structure reviewer supplies exact proposal/candidate/source
   evidence, all required checks and the observed previous review identity.
   Append-only predecessor CAS rejects late decisions. Model agreement is not a
   human review. `technical_fixture_only` evidence records simulated engineering
   checks; the tests make no actual human or bank review claim.
5. `materialize` creates a NEW partial extraction and exact clause associations.
   It preserves the original extraction. Its context extension binds the schema,
   proposal, review, extraction and association hashes. Repeated reads rederive
   the exact transcription, coverage, clause locators and identities.
6. Existing queue/staging and semantic term review remain mandatory. The worker
   receives only the bounded association payload and current context extension.
   A term using a cell must include its headers, units and qualifying notes.
   Reserved extractor versions and registered association rows both require this
   admission path; naming text cannot establish authority.

## Current claims and retained history

Positive staging, semantic review and applicable publication reads recheck the
latest structural decision. A rejection/revocation invalidates new current claims
without changing prior receipts. Reporting first excludes superseded and unrelated
source versions; a revoked old candidate cannot block a valid admitted replacement.
Historical monetary validation also checks structural decisions; partial structure
does not bypass its existing complete-extraction requirement.

Reads work with the existing read-only publisher connection. An operation may reuse
bounded immutable blob bytes (512 cached identities, 32 MiB cache capacity, with
least-recently-used eviction); it never caches review
or source-current decisions. Individual retained JSON is limited to 2 MiB, parent
PDF to 16 MiB, parent text to 8 MiB. No existing publisher budget is raised. The
cache is not an additional aggregate admission limit; underlying publisher I/O
budgets still apply to every uncached read. It is discarded after the call,
including failure; migration writes own a
transaction and roll back even on cancellation.

## Verification boundary

`tests/test_structured_review.py` uses a generated engineering PDF and simulated
human decisions. It connects source/candidate/proposal/review to worker payload,
staging, semantic review, publication and revocation. It also covers read-only
publication, shared-source reads, valid replacement selection, omitted associations,
unknown versions, both legacy bypass routes, stale-source negative review,
independence/CAS and transactional migration cancellation/reopen. These tests prove
protocol mechanics, not OCR accuracy, bank interpretation or Pi enforcement.
