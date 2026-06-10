# PR bot feedback matrix

Automated in-repo matrix tracking how each review bot responded to merged PRs. The workflow commits colored HTML and machine-readable JSON — no Google Sheets or external secrets.

| Dimension | Content |
|-----------|---------|
| **Rows** | Merged pull requests (newest first) |
| **Columns** | Gemini, Codex, Sourcery, Copilot, CodeRabbit, Greptile |
| **Colors** | Green / yellow / grey / red (see below) |

## Viewing the matrix on GitHub

| Artifact | Path | How to view |
|----------|------|-------------|
| **Colored table** | [`reports/pr-bot-matrix.html`](../reports/pr-bot-matrix.html) | Open the file on GitHub, click **Raw**, or paste the raw URL in a browser — the HTML renders with cell background colors. |
| **JSON** | [`reports/pr-bot-matrix.json`](../reports/pr-bot-matrix.json) | Browse on GitHub or consume in scripts/CI. |

Raw URL pattern (replace `OWNER/REPO` and branch):

`https://raw.githubusercontent.com/OWNER/REPO/main/reports/pr-bot-matrix.html`

## Cell colors

| Color | Meaning |
|-------|---------|
| **Green** | Bot gave substantive feedback (comment, review, or thumbs reaction) **and** all actionable threads were addressed before merge. Declined / won't-fix / deferred replies count as addressed (same rules as `pr-bot-feedback-check --audit-merged`). |
| **Yellow** | Bot gave substantive feedback but at least one actionable thread was still open at merge (unresolved, no disposition reply). |
| **Grey** | No bot activity on the PR (no comments, reviews, or thumbs from that bot login). |
| **Red** | Bot posted but only quota/limit notices — no substantive feedback before merge. Uses `scripts/lib/bot-noise.mjs` `isQuotaBotMessage` patterns (rate limit, out of credits, trial expired, unable to review, etc.). |

A bot with **both** a limit notice **and** later substantive feedback is classified from the substantive outcome (green/yellow), not red.

## Bot roster

Columns match `scripts/lib/bot-wait-config.mjs` plus optional reviewers:

| Column | GitHub logins |
|--------|---------------|
| Gemini | `gemini-code-assist[bot]`, `google-github-actions-bot[bot]`, … |
| Codex | `chatgpt-codex-connector[bot]` |
| Sourcery | `sourcery-ai[bot]` |
| Copilot | `copilot-pull-request-reviewer[bot]` |
| CodeRabbit | `coderabbitai[bot]` |
| Greptile | `greptile-apps[bot]` |

## Workflow

Workflow: [`.github/workflows/pr-bot-spreadsheet.yml`](../.github/workflows/pr-bot-spreadsheet.yml)

Triggers:

- **Daily** 06:00 UTC (`cron`)
- **On PR merge** (`pull_request` closed + merged)
- **Manual** `workflow_dispatch` (optional `--limit`, single `--pr`)

After sync, the job commits matrix artifacts **directly to `main`** via `npm run pr:bot-matrix:commit` (no PR loop). `pi-deploy-on-main` ignores `reports/**` pushes.

### Direct commit to main (one-time GitHub setup)

Protected `main` requires `bot-presence-gate` and `bot-feedback-gate`. A workflow push does not run those checks first, so GitHub rejects the push unless **GitHub Actions** is on the ruleset bypass list.

**Settings → Rules → Rulesets** (repo uses legacy branch protection today; add a ruleset bypass — do not remove human merge gates):

1. Open the `main` branch ruleset (or create one mirroring required checks: `bot-feedback-gate`, `bot-presence-gate`, conversation resolution).
2. **Bypass list → Add bypass → GitHub Actions** (mode: **Always**, or scope to workflow file `.github/workflows/pr-bot-spreadsheet.yml` when available).
3. Save. Re-run `pr-bot-spreadsheet` (`workflow_dispatch`) to confirm the push succeeds.

If push fails with `protected branch hook declined`, the workflow logs `MATRIX_PUSH_BYPASS_HINT` from `scripts/lib/pr-bot-matrix-commit.mjs`.

Legacy matrix PR `bot/pr-bot-matrix-sync` is obsolete after this change — close any open bot matrix PR once direct push is verified.

Uses `GITHUB_TOKEN` with `contents: write` only (no `pull-requests: write`).

### Optional secret

| Secret | Required | Purpose |
|--------|----------|---------|
| `BOT_GATE_TOKEN` | No | PAT with `repo` read if `GITHUB_TOKEN` is insufficient for `gh` API |

## Local commands

```sh
# Classify recent merged PRs; print paths only
npm run pr:bot-spreadsheet:sync -- --dry-run --limit 10

# JSON report to stdout
npm run pr:bot-spreadsheet:sync -- --dry-run --limit 5 --json

# Single PR
npm run pr:bot-spreadsheet:sync -- --pr 253 --dry-run --json

# Write artifacts locally
npm run pr:bot-spreadsheet:sync -- --limit 30
```

## Implementation files

| File | Role |
|------|------|
| `scripts/pr-bot-spreadsheet-sync.mjs` | CLI entry |
| `scripts/lib/pr-bot-matrix-writer.mjs` | HTML + JSON artifact writer |
| `scripts/pr-bot-matrix-commit.mjs` | Stage/commit/push matrix files to `main` |
| `scripts/lib/pr-bot-matrix-commit.mjs` | Matrix commit paths + bypass hint |
| `scripts/lib/pr-bot-roster.mjs` | Bot column definitions |
| `scripts/lib/pr-bot-spreadsheet-fetch.mjs` | GitHub GraphQL fetch |
| `scripts/lib/pr-bot-cell-status.mjs` | Green/yellow/grey/red logic |
| `scripts/lib/bot-noise.mjs` | Quota/limit patterns (shared) |
| `scripts/lib/gh-pr-review-threads.mjs` | Thread address detection (shared) |
| `reports/pr-bot-matrix.html` | Generated colored matrix (committed) |
| `reports/pr-bot-matrix.json` | Generated machine-readable matrix (committed) |
