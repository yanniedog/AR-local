# Historical bank-rate catalogue

Every core may include the additive `bank_rate_history_catalogue` field. The
existing schema1 `bank_rate_history` remains unchanged for earlier consumers.
Schema2 represents every retained historical tier, including withdrawn products;
filters apply to each observation's own descriptor and product evidence.

```typescript
type Source =
  | {kind: 'selected_contract'; generation_id: string; contract_digest: string;
     banks_sha256: string; bytes: number}
  | {kind: 'retained_legacy_export'; banks_sha256: string; bytes: number}
  | {kind: 'published_core'; core_sha256: string; details_sha256: string;
     manifest_sha256: string};
type Evidence = {status: 'unknown'} | {
  status: 'known';
  identity: {provider: string; product_id: string; product_key: string;
             category: string; dataset: 'Mortgage' | 'Savings' | 'TD'};
  detail: {description?: string; eligibility?: object[]; constraints?: object[];
           facts?: object[]};
};
type Tier = {
  row: object;
  spans: [start: number, count: number, rates: number[], evidenceId: number][];
};
type Catalogue = {
  schema_version: 2;
  run_dates: string[];
  sources: Record<string, Source>;
  unavailable_dates: Record<string, string>;
  evidence: Evidence[];
  sections: {Mortgage: Tier[]; Savings: Tier[]; TD: Tier[]};
};
```

`run_dates` is the complete ascending calendar axis. Prices in spans are
percentage points, sorted with multiplicity retained. The tier descriptor is
the compact core row without `rate`, `comparison_rate`, `ongoing_rate`,
`last_updated`, `rate_index`, `exact_alert_eligible`, or `bank_rate_tier`.
Array indices identify tiers only within their section. Evidence index0 is the
shared unknown entry. Known evidence must match the tier's complete identity
and section. Empty, missing, conflicting or malformed detail never acquires
evidence from today's product. Missing dates have no spans; consecutive spans
merge only when rates and evidence ID are unchanged and observations contiguous.

The detail projection preserves description, eligibility, constraints and all
feature fact variants. Positive feature evidence must pass the existing
conservative `feature_facts` projection when sourced from raw CDR: narrative,
conditions, linked scope, effective-date boundaries and conflicts cannot grant
unassessed feature eligibility. Published input preserves its existing typed
feature facts; `feature_set` alone never grants a feature. The app evaluates
historical filters in an explicit historical context and does not change the
installed current-core eligibility gates.

Selected export sources bind the verified ledger contract and bytes actually
read. Legacy exports carry their consumed byte digest without claiming a later
ledger identity. Published cores and details must belong to the same indexed
immutable manifest, with domain SHA256, length, date and revision identity
verified before use. Source receipts contain no private paths.

Private prepacking from public artifacts uses `dates-index.json`,
`manifests/YYYY-MM-DD.json`, `cores/<sha256>.gz`, and `details/<sha256>.gz`.
This local-only path does not publish, reserve revisions or alter source files.
Production publication still belongs to the guarded Pi revision coordinator.

The Sept26 proof with all 134 public observations, both history schemas and
current rows is 55,482,003 decoded bytes and 2,718,749 gzip bytes. The core has a
4 MiB compressed transfer cap; details, search and other per-asset caps and the
8 MiB total remain enforced. Filters and bank selection reuse local packed data
after acquisition. Budget reports continue to disclose slow-network transfer
times instead of describing the initial download as instantaneous.

Private output must be a new directory and never an existing acquired-input
directory. It may be a new child of the same private cache workspace: acquisition
reads only the explicitly indexed manifest/core/details paths, never discovers
derived files recursively, and verifies source hashes before reading them.
