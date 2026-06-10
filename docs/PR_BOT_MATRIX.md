# PR bot feedback matrix

| Artifact | Path | GitHub view |
|----------|------|-------------|
| **Markdown (primary)** | [`reports/pr-bot-matrix.md`](../reports/pr-bot-matrix.md) | Scan-friendly table with **PASS** / **FAIL** / **LIMIT** / — |
| **HTML** | [`reports/pr-bot-matrix.html`](../reports/pr-bot-matrix.html) | Colored cells (Raw in browser) |
| **JSON** | [`reports/pr-bot-matrix.json`](../reports/pr-bot-matrix.json) | Machine-readable |

Renderer: [`scripts/lib/pr-bot-matrix-markdown.mjs`](../scripts/lib/pr-bot-matrix-markdown.mjs)

## Status labels (markdown)

| Label | Meaning |
|-------|---------|
| **PASS** | Substantive feedback addressed before merge |
| **FAIL** | Open threads at merge |
| **—** | No bot activity |
| **LIMIT** | Quota/limit notice only |

HTML uses colored OK/Open/Limit cells (same underlying logic in `scripts/lib/pr-bot-cell-status.mjs`).

## Workflow

Workflow: [`.github/workflows/pr-bot-spreadsheet.yml`](../.github/workflows/pr-bot-spreadsheet.yml)

After sync, the job commits matrix artifacts **directly to `main`** via `npm run pr:bot-matrix:commit` (no PR loop). `pi-deploy-on-main` ignores `reports/**` pushes.

### Direct commit to main (one-time GitHub setup)

Protected `main` requires `bot-presence-gate` and `bot-feedback-gate`. A workflow push does not run those checks first, so GitHub rejects the push unless **GitHub Actions** is on the ruleset bypass list.

See workflow logs for `MATRIX_PUSH_BYPASS_HINT` from `scripts/lib/pr-bot-matrix-commit.mjs` if push fails.

### Optional secret

| Secret | Required | Purpose |
|--------|----------|---------|
| `BOT_GATE_TOKEN` | No | PAT with `repo` read if `GITHUB_TOKEN` is insufficient for `gh` API |

## Local commands

```sh
npm run pr:bot-matrix:verify
npm run pr:bot-spreadsheet:sync -- --limit 30
npm run pr:bot-matrix:commit -- --dry-run
```

## Implementation files

| File | Role |
|------|------|
| `scripts/lib/pr-bot-matrix-markdown.mjs` | GitHub markdown table builder |
| `scripts/lib/pr-bot-matrix-writer.mjs` | Markdown + HTML + JSON writer |
| `scripts/pr-bot-spreadsheet-sync.mjs` | CLI entry |
| `scripts/pr-bot-matrix-commit.mjs` | Stage/commit/push matrix files to `main` |
| `scripts/lib/pr-bot-matrix-commit.mjs` | Matrix commit paths + bypass hint |
