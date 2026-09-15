# Import the main branch ruleset

The checked-in template has no bypass actors. Preserve existing branch protection;
matrix reporting uses read-only permissions and needs no protection changes.

Run `npm run github:bot-gates:operator` to validate the local template and print
setup instructions. This does not verify or modify live GitHub configuration.

## Import steps

1. Open **Settings → Rules → Rulesets → New ruleset → Import a ruleset**.
2. Select [main-bot-gates.json](../.github/rulesets/main-bot-gates.json).
3. Review the template against the intended repository policy before applying it:
   - Target branches: `refs/heads/main` and `~DEFAULT_BRANCH`.
   - Bypass actors: empty, including GitHub Actions.
   - Pull requests: squash only, conversation resolution, zero required approvals.
   - Force pushes and branch deletion: blocked.
   - Universal check: `bot-feedback-gate`. Preserve applicable product CI in
     existing protection. [WORKFLOW.md](../WORKFLOW.md) makes reviewer presence advisory.
4. Save only the reviewed configuration. Preserve existing branch protection.

## Matrix report verification

```sh
npm run pr:bot-matrix-commit:verify
gh run list --workflow=pr-bot-spreadsheet.yml --limit 3
```

The matrix workflow publishes an Actions job summary and downloadable artifacts.
It does not push to main. A protected-branch rejection from the legacy local
matrix commit command is not a report setup requirement.

## Related documents

- [PR_BOT_MATRIX.md](PR_BOT_MATRIX.md) — report artifacts
- [WORKFLOW.md](../WORKFLOW.md) — current PR closeout policy
- [MERGE_POLICY.md](../.github/MERGE_POLICY.md) — squash auto-merge
