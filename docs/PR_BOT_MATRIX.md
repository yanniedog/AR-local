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

After sync, the job opens (or updates) PR `bot/pr-bot-matrix-sync` with the matrix artifacts and enables squash auto-merge when checks pass. Protected `main` rejects direct pushes without required checks; matrix-only PRs still run `bot-presence-gate` and `bot-feedback-gate`, but those jobs exit immediately when `scripts/lib/pr-reports-only.mjs` detects only `reports/**` changes (same skip in `npm run wait-for-bots`). Uses `GITHUB_TOKEN` with `contents: write` and `pull-requests: write`. Matrix-only merges should not re-run Pi deploy (`reports/**` is ignored by `pi-deploy-on-main`).

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
| `scripts/lib/pr-bot-roster.mjs` | Bot column definitions |
| `scripts/lib/pr-bot-spreadsheet-fetch.mjs` | GitHub GraphQL fetch |
| `scripts/lib/pr-bot-cell-status.mjs` | Green/yellow/grey/red logic |
| `scripts/lib/bot-noise.mjs` | Quota/limit patterns (shared) |
| `scripts/lib/gh-pr-review-threads.mjs` | Thread address detection (shared) |
| `reports/pr-bot-matrix.html` | Generated colored matrix (committed) |
| `reports/pr-bot-matrix.json` | Generated machine-readable matrix (committed) |
