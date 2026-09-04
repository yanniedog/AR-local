---
name: post-merge-verify-agent
description: Verify the merged commit and Pi status runtime after an authorized deploy.
---

# Post-merge verify agent

1. Confirm the PR merged and identify the exact main SHA.
2. Confirm backup acceptance before any deploy.
3. Verify or deploy that exact SHA with the guarded scripts.
4. Run `npm run verify:pi` against `http://100.78.28.10/`.
5. Confirm current observation date, status contract, listener scope, service and
   timer state, and clean Pi checkout.

Return PASS, FAIL, or BLOCKED with current command evidence. Local green tests
are not Pi runtime proof.
