# PR bot feedback spreadsheet

Automated Google Sheet matrix tracking how each review bot responded to merged PRs.

| Dimension | Content |
|-----------|---------|
| **Rows** | Merged pull requests (newest first) |
| **Columns** | Gemini, Codex, Sourcery, Copilot, CodeRabbit, Greptile |
| **Colors** | Green / yellow / grey / red (see below) |

## Cell colors

| Color | Meaning |
|-------|---------|
| **Green** | Bot gave substantive feedback (comment, review, or thumbs reaction) **and** all actionable threads were addressed before merge. Declined / won't-fix / deferred replies count as addressed (same rules as `pr-bot-feedback-check --audit-merged`). |
| **Yellow** | Bot gave substantive feedback but at least one actionable thread was still open at merge (unresolved, no disposition reply). |
| **Grey** | No bot activity on the PR (no comments, reviews, or thumbs from that bot login). |
| **Red** | Bot posted but only quota/limit notices — no substantive feedback before merge. Uses `scripts/lib/bot-noise.mjs` `isQuotaBotMessage` patterns (rate limit, out of credits, trial expired, unable to review, etc.). |

### Limit detection heuristics

Red cells reuse the same quota patterns as `wait_for_bots.mjs` and `gh-pr-review-threads.mjs`:

- `rate limit`, `api limit`, `quota exceeded`, `out of credits/tokens`
- `subscription required/expired`, `trial expired`, `free-tier limit`
- `unable to review`, `couldn't review`, `too many requests`, `429`
- `service temporarily unavailable`, `please try again later`

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

## Setup

### 1. Google Cloud service account

1. [Google Cloud Console](https://console.cloud.google.com/) → IAM → **Service accounts** → Create.
2. Enable **Google Sheets API** for the project.
3. Create a JSON key; store the full JSON as GitHub secret `PR_BOT_SHEET_SERVICE_ACCOUNT_JSON`.

### 2. Google Sheet

1. Create a spreadsheet; add a tab named **`PR Bot Matrix`** (or set `PR_BOT_SHEET_TITLE`).
2. Copy the spreadsheet ID from the URL (`https://docs.google.com/spreadsheets/d/<ID>/edit`).
3. **Share** the sheet with the service account email (`…@….iam.gserviceaccount.com`) as **Editor**.
4. Store the ID as GitHub secret `PR_BOT_SPREADSHEET_ID`.

### 3. GitHub secrets

| Secret | Required | Purpose |
|--------|----------|---------|
| `PR_BOT_SPREADSHEET_ID` | Yes (for live sync) | Target sheet ID |
| `PR_BOT_SHEET_SERVICE_ACCOUNT_JSON` | Yes (for live sync) | Service account key JSON |
| `BOT_GATE_TOKEN` | Optional | PAT with `repo` read if `GITHUB_TOKEN` is insufficient |

### 4. Workflow

Workflow: `.github/workflows/pr-bot-spreadsheet.yml`

Triggers:

- **Daily** 06:00 UTC (`cron`)
- **On PR merge** (`pull_request` closed + merged)
- **Manual** `workflow_dispatch` (optional `--limit`, single `--pr`)

## Local commands

```sh
# Classify recent merged PRs without writing to Sheets
npm run pr:bot-spreadsheet:sync -- --dry-run --limit 10

# JSON report
npm run pr:bot-spreadsheet:sync -- --dry-run --limit 5 --json

# Single PR
npm run pr:bot-spreadsheet:sync -- --pr 253 --dry-run --json

# Live sync (needs env vars)
PR_BOT_SPREADSHEET_ID=… PR_BOT_SHEET_SERVICE_ACCOUNT_JSON="$(cat key.json)" \
  npm run pr:bot-spreadsheet:sync -- --limit 30
```

## Implementation files

| File | Role |
|------|------|
| `scripts/pr-bot-spreadsheet-sync.mjs` | CLI entry |
| `scripts/lib/pr-bot-roster.mjs` | Bot column definitions |
| `scripts/lib/pr-bot-spreadsheet-fetch.mjs` | GitHub GraphQL fetch |
| `scripts/lib/pr-bot-cell-status.mjs` | Green/yellow/grey/red logic |
| `scripts/lib/google-sheets-client.mjs` | Sheets API write + colors |
| `scripts/lib/bot-noise.mjs` | Quota/limit patterns (shared) |
| `scripts/lib/gh-pr-review-threads.mjs` | Thread address detection (shared) |

## Alternatives

If Google credentials are unavailable:

- **`--dry-run --json`** prints the matrix locally.
- Excel via `cdr_xlsx.py` could be added as a follow-up export path; native color coding and CI updates favor Google Sheets for this repo.
