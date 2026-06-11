# Import GitHub ruleset for `main` (bot gates + Actions bypass)

One-time operator setup so workflow jobs can push directly to `main` (PR bot matrix sync, mobile auto-release) while keeping bot merge gates for **human** PRs only.

**Operator script (prints policy + import steps + local verify):**

```sh
npm run github:bot-gates:operator
npm run github:bot-gates:operator -- --verify-pr 310
```

**Bot skip policy** (chore + `github-actions[bot]` PRs) lives in repo code (`scripts/lib/pr-gate-exempt.mjs`), not in the ruleset JSON. The ruleset always lists the two gate checks; workflows skip them when exempt.

**Artifact:** [`.github/rulesets/main-bot-gates.json`](../.github/rulesets/main-bot-gates.json)

Mirrors legacy branch protection on `main` (verified via `gh api repos/yanniedog/AR-local/branches/main/protection`):

| Setting | Value |
|---------|-------|
| Required checks | `bot-feedback-gate`, `bot-presence-gate` (strict / up-to-date) |
| Conversation resolution | Required |
| Force push | Blocked |
| Branch deletion | Blocked |
| Admin bypass | Off (`enforce_admins` — no bypass actors for admins) |
| GitHub Actions bypass | Always (`actor_id` 15368, GitHub Actions app) |

The REST API returns **422** when POSTing this bypass on `yanniedog/AR-local`; import via the GitHub UI instead.

## Import steps

1. Open **Settings → Rules → Rulesets → New ruleset → Import a ruleset**.
2. Select [`.github/rulesets/main-bot-gates.json`](../.github/rulesets/main-bot-gates.json).
3. Review the imported ruleset:
   - **Target branches:** `refs/heads/main` and `~DEFAULT_BRANCH`
   - **Bypass list:** GitHub Actions, mode **Always**
   - **Rules:** required status checks, pull request (0 approvals, conversation resolution), block force push, block deletion
4. **Save** and set enforcement to **Active**.
5. **Remove legacy branch protection** on `main`: **Settings → Branches →** rule for `main` → **Delete**. Both layers enforce independently; keeping legacy protection blocks workflow pushes even when the ruleset bypass is correct.
6. **Verify** direct-to-main workflows:

```sh
npm run pr:bot-matrix-commit:verify
npm run pr:bot-matrix:verify
```

Then run **Actions → pr-bot-spreadsheet → Run workflow** (`workflow_dispatch`). Expect the job to commit `reports/pr-bot-matrix.{md,html,json}` to `main`.

```sh
gh run list --workflow=pr-bot-spreadsheet.yml --limit 3
```

If push fails with `protected branch hook declined`, the workflow logs `MATRIX_PUSH_BYPASS_HINT` from `scripts/lib/pr-bot-matrix-commit.mjs`.

## Related docs

- [`docs/PR_BOT_MATRIX.md`](PR_BOT_MATRIX.md) — matrix workflow and bypass rationale
- [`scripts/apply-branch-protection.mjs`](../scripts/apply-branch-protection.mjs) — legacy API protection (no Actions bypass)
- [`.github/MERGE_POLICY.md`](../.github/MERGE_POLICY.md) — squash auto-merge for PRs
