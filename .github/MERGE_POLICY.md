# Merge policy (AR-local)

All PRs to `main` use **squash auto-merge** by default.

## Agent / automation command

Use the canonical one-shot helper:

```sh
npm run pr:arm-and-park -- --pr <n>
```

It verifies the exact default base, marks a draft ready, syncs when needed, and
arms squash auto-merge with branch deletion. Exit 0 means ready or merged, exit
2 means pending-only/parked, and exit 3 means actionable. Never invoke bare
`gh pr merge`; the legacy `npm run pr:merge` wrapper is guarded but not the
preferred agent entrypoint.

## `gh pr create`

Squash is **not** set at PR creation. Opening a draft PR does not choose the
merge method; `pr:arm-and-park` marks it ready and arms the canonical method.

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
