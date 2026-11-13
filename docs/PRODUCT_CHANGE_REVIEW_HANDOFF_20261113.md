# Product-change review follow-up — 2026-11-13

Follow-up to merged PR #1130, fresh branch
`agent/change-provenance-followup-20261113` from main `865a854`.
No Pi mutation or historical export rewrite.

Six late review threads were assessed against reachable source behavior:

- **Known failure hidden by population-absence reason:** fixed. Provider index/
  holder failures now take precedence, then known product detail/classification
  failures, then unexplained absent exported population. Suppression behavior
  itself remains conservative; counters identify the known cause.
- **Workbook reason map rendered as Python dictionary:** fixed. The generated
  `change_summary` sheet emits `suppression_reasons_json`, matching the existing
  `products_json` convention. JSON exports retain their actual object field.
- **Empty-index fixture not checked:** improved. The regression explicitly calls
  the production index-capture validator on the unchanged captured Westpac body
  and confirms its empty product array before export/diff assertions. The exporter
  intentionally guards an absent population regardless of why it is absent.
- **Complete nonempty index, but all current detail captures fail:** the PR's
  deliberate whole-export-population uncertainty guard still suppresses removals.
  An index-only retirement path needs independently verified complete listing,
  identity and current observation provenance; a bare index/diagnostic is not
  sufficient authority to relax that guard. No positive withdrawal claim added.
- **Leftover details after empty index:** `parse_banks_run` already enumerated
  detail files before #1130; the change does not add carry-forward. The controlled
  same-day reuse path explicitly treats a fresh empty catalogue as unconfirmed,
  retains same-day captured evidence, and records incomplete status. Making an
  empty index authoritative would conflict with the observed upstream empty-index
  failure mode. Broader retained-product freshness remains a separate audit item.
- **Handoff verbosity:** no change. The user explicitly requested a detailed,
  progressively published handoff; UI presentation guidance does not override it.

Validation: 108 tests passed in 5.18s, with complete JUnit and isolated-runner
completion. Five existing openpyxl default-style warnings are non-failing.
Controls exercise failure precedence for four phases and parse the actual
generated workbook field as JSON. Captured-fact tests continue guarding false
removals. Independent review and exact-head hosted CI remain required; root owns
merge. No runtime acceptance is implied.
