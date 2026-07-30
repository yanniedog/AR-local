# Merge policy (AR-local)

All PRs to `main` use **squash auto-merge** by default.

## Agent / automation command

After `npm run pr:gates:check -- --pr <n>` exits **0**:

```sh
npm run pr:merge -- --pr <n>
# equivalent:
gh pr merge <n> --auto --squash --delete-branch
```

`--auto` queues merge until required checks pass. Reviewer presence is
advisory; complete substantive feedback disposition and thread closure per
`WORKFLOW.md`. Agents use single-shot gate reads and park while GitHub owns the
clock.

## `gh pr create`

Squash is **not** set at PR creation. Opening a PR does not choose merge method; use the merge command above when gates pass.

## Repository settings (squash-only)

Apply via API (admin token):

```sh
npm run repo-merge-settings:apply
```

Target:

| Setting | Value |
|---------|-------|
| `allow_squash_merge` | true |
| `allow_merge_commit` | false |
| `allow_rebase_merge` | false |
| `delete_branch_on_merge` | true |
| `allow_auto_merge` | true |

If the API returns 403, apply manually: **Settings → General → Pull Requests** (see script output).

## Branch protection

The universal gate on `main` is `bot-feedback-gate`:
`npm run branch-protection:apply` (see `WORKFLOW.md`). Applicable product CI
remains path-filtered and is not added as a synthetic universal context.
