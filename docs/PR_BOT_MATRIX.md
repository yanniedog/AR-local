# PR bot feedback matrix

Read-only report of review bot feedback on merged PRs. Each workflow run publishes a Markdown job summary and downloadable Markdown, HTML and JSON files. It creates no commits or pull requests.

| Dimension | Content |
|-----------|---------|
| **Rows** | Merged pull requests (newest first) |
| **Columns** | Gemini, Codex, Sourcery, Copilot, CodeRabbit, Greptile |
| **Colors** | Green / yellow / grey / red (see below) |

## Viewing the matrix on GitHub

Open the latest successful [pr-bot-spreadsheet Actions run](https://github.com/yanniedog/AR-local/actions/workflows/pr-bot-spreadsheet.yml). Read its job summary or download `pr-bot-matrix-RUN_ID-ATTEMPT`; artifacts remain available for 30 days. HTML and JSON are included in the download.

The tracked `reports/pr-bot-matrix.{md,html,json}` files are retained historical snapshots, not the current automated report.

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

Each run generates into a fresh temporary directory, adds Markdown to the job summary, and uploads all three files. A manual single-PR run contains that PR only; it never incorporates the tracked historical report. `limit` accepts 1–100 and `pr_number` accepts a positive integer of at most nine digits. Inputs are validated as data before invoking the generator.

The workflow uses `contents: read` and `pull-requests: read`; checkout does not persist credentials. It does not push to protected main, create bot PRs or require a ruleset bypass. Existing local generator and legacy commit commands remain unchanged, but the workflow never invokes the commit command.

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
| `scripts/lib/pr-bot-matrix-writer.mjs` | Markdown + HTML + JSON artifact writer |
| `scripts/lib/pr-bot-matrix-markdown.mjs` | GitHub markdown table + PR body builder |
| `scripts/pr-bot-matrix-commit.mjs` | Stage/commit/push matrix files to `main` |
| `scripts/lib/pr-bot-matrix-commit.mjs` | Matrix commit paths + bypass hint |
| `scripts/lib/pr-bot-roster.mjs` | Bot column definitions |
| `scripts/lib/pr-bot-spreadsheet-fetch.mjs` | GitHub GraphQL fetch |
| `scripts/lib/pr-bot-cell-status.mjs` | Green/yellow/grey/red logic |
| `scripts/lib/bot-noise.mjs` | Quota/limit patterns (shared) |
| `scripts/lib/gh-pr-review-threads.mjs` | Thread address detection (shared) |
| `reports/pr-bot-matrix.md` | Historical markdown snapshot |
| `reports/pr-bot-matrix.html` | Historical colored snapshot |
| `reports/pr-bot-matrix.json` | Historical machine-readable snapshot |
