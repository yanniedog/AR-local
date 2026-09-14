# Candidate document graph v1

This private graph extends the dedicated schema v1 additively. It never modifies
original CDR databases or the public terms-v1 contract. All graph tables inherit
the evidence store's append-only triggers and foreign-key enforcement.

| Record | Immutable binding |
| --- | --- |
| Root | Acquisition request, exact successful check, policy and host-grant provenance; capture timestamp |
| Scope | Root plus each original applicability ID; joins retain provider/product, raw observation/hash, source JSON pointer, original fragment and relation |
| Node | Root plus canonical fetch URL/document ID; first parent, depth and shared per-ingest acquisition request |
| Edge | Parent node, exact document version and extraction, original href/resolved URL, HTML anchor ordinal, line/column, bounded label, optional child node and disposition |
| Expansion | Node, exact check/extraction, processing observation time, extraction status/reason, anchor counts, omitted count and limit reason |

Fragments belong to edges, not fetch identity. Different source URLs retain
different document/version identities even if original-byte hashes match. Multiple
product/tier/package/cohort pointers remain separate scopes; their presence is
candidate applicability, not an assertion that every clause applies to every scope.
Effective legal dates remain unknown unless separately evidenced and reviewed.

`DocumentGraph.seed(request, check, policy=...)` validates retained request/check
identities with canonical hashes. Only an exact lease-accepted event bound to a
successful capture activates expansion; interpretation failure does not hide
image-only document links. A raw orphan successful check cannot activate it.
Priority 2 never converts a new network fetch into historical evidence.
The existing historical-target contract remains the route for retained old versions.

`advance_one()` performs one offline node expansion. It checks the root observation
against completed ingest captures and every captured ancestor version/location,
resolves links against the verified
final URL, and commits edges and requests in one transaction. A crashed expansion
restarts; a stale source leaves a durable unresolved disposition. Shared acquisition
requests retain their existing atomic leases, bounded retries and completion CAS.
Failed requests retain their old versions and link edges. No failure implies removal.
Malformed HTML and unreadable retained bytes have durable failed expansions with
unknown discovery scope, so later queued siblings remain reachable. Partial newer
ingests cannot supersede an older completed observation. Equal-time distinct
completed source identities remain ambiguous rather than choosing one silently.

The default per-root limits are depth 3 and 32 URL nodes; each node follows at most
128 links. HTML extraction records at most 256 anchor occurrences plus an exact
omitted count and original-byte identity. Only one pending expansion and one fetch
are processed in an admitted collector cycle. Permanently blocked nodes are not
reported as due work. These are operational limits, not completeness thresholds.

Every exact raw CDR reference host can grant traversal within its own hostname.
New hosts require a retained JSON review receipt whose content hash is supplied in
`GraphPolicy.reviewed_hosts`. The receipt requires `schema_version: 1`,
`kind: "official_document_host_grant"`, the exact canonical `host`,
`decision: "approved"`, a nonempty `reviewer` and explicit timestamp `reviewed_at`.
This API belongs to the trusted review/controller boundary; model output and HTML
cannot approve hosts. A grant for a domain does not grant any subdomain. DNS/IP,
HTTPS, redirect, timeout and byte policies still apply to every request.

`inventory(root_id)` returns the full bounded graph and joined source scopes,
acquisition statuses/errors, parent-source dispositions and extraction receipts.
`legal_completeness` is always `unknown`. An empty frontier does not certify all
PDSs, terms, incorporated clauses, hidden dynamic links or PDFs were discovered.
Graph edges create no analysis jobs, term revisions, reviews or publication assets;
an independent explicit source-applicability review is still required.

Tests retain exact May 19 and September 7 public CDR bytes. HTML and transport fault
snippets test protocol behavior only and are not fabricated financial acceptance
data. Their clocks do not backdate live evidence. No Pi activation, network crawl,
Drive backup change or full legal-corpus acceptance is implied by this contract.
