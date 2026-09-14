# Incorporated document candidate interpretation

The scheduled collector now connects a usable child-document extraction to the
existing interpretation queue. Previously a graph-only child stopped after link
expansion. Direct CDR references retain their existing processing path.

The exact graph expansion and its candidate analysis job commit in the same
SQLite transaction. The existing processing lease and source guards run before
and after context storage and job writes. Context blobs can remain orphaned after
a rejected transaction; they are not runnable jobs. Existing capture, parser
retry/backoff, child lifetime, resource, priority, quiet-window and single
interpreter limits remain unchanged. Empty or failed text still receives a graph
disposition without a fabricated analysis job.

`incorporated_target` pins the child extraction/content, root identity/policy,
accepted checks and final URLs for up to nine ancestry nodes, parent anchor edge
identities, and each distinct raw product/reference scope. It is bounded to
64 KiB and at most 1,000 source scopes; larger contexts retain an explicit parser
failure/backoff disposition. Product scope conflicts fail closed. Readiness scans
check context/record identities without rereading source bodies. Actual admission
verifies originals and text, as well as current root observations and ancestry.

The worker accepts only this constructed context, produces
`expected_incorporated_scope`, and requires the result to copy the exact
`incorporated_candidate_only` scope and `applicability_status: unreviewed`.
Successful format/source/lease validation returns `STAGED_INCORPORATED_CANDIDATE`.
No customer profile, inferred effective date, or historical attribution is added.
Historical-only and incorporated candidate targets cannot be mixed.

Discovery is not legal applicability. Staging adds no applicability row, reviewed
term revision, executable rule, or public projection. Current term admission
explicitly refuses this candidate context, even if another source path separately
references the same document. An independently reviewed applicability adapter is
still needed before these candidate terms can contribute to comparisons.

Exact old processing receipts remain verifiable after a source advances; they
cannot admit new interpretation against stale ancestry. A completed expansion
already present before this code was installed is not silently replayed. Future
accepted captures proceed through the connected path; any bounded backfill of old
expansions requires a separately reviewed work identity/queue migration.

Local tests use retained CDR identities and labelled markup/transport controls.
They prove connected queue, worker staging, transaction rollback, scope and
promotion refusal mechanisms; they do not establish actual bank clause accuracy,
full recursive closure, Pi deployment, or complete comparison readiness.
