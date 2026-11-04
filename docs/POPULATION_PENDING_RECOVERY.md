# Current-day population recovery with historical uploads pending

- Admission: exactly one verified current-day hold plus valid, distinct, strictly older pointers; no queue-count cutoff absent from the pending-marker writer.
- Reject: ambiguous identities, future sources, selection retries and malformed metadata.
- Preserve: daily claims, probe/capture budgets, cooldowns and population proof. Failed or empty provider responses cannot clear membership holds.
- Supersession: require the selected same-day child, exact parent event/contract and reconciled baseline; replace only the predecessor slot and preserve historical order.
- Audit: immutable receipt retains the preceding queue and marks publication unconfirmed. Receipts exceeding the existing 64 KiB bound retain ordinary pending work; admission does not guarantee supersession.
- Crash recovery: consolidate an already-queued exact successor only after lineage proof.
- Retry: use the verified current source's exact publication key; missing sources and cooldowns cannot fall back to older uploads.
- Outcome: success removes only the published source; failure, withholding or interruption preserves it. Never assert historical upload success or promote unverified populations.
