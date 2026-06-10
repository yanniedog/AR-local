# Merge policy (AR-local)

All PRs to `main` use **squash auto-merge** by default.

## Agent / automation command

After `npm run pr:gates:check -- --pr <n>` exits **0**:

```sh
npm run pr:merge -- --pr <n>
# equivalent:
gh pr merge <n> --auto --squash --delete-branch
```

`--auto` queues merge until required checks pass (and updates branch when protection requires up-to-date). Do not merge on CI green alone — complete bot wait and thread closure per `WORKFLOW.md`.

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

Bot gates on `main`: `npm run branch-protection:apply` (see `WORKFLOW.md`). Protection blocks merge until checks pass; it does not replace squash-only repo settings above.
