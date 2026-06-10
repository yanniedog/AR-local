#!/usr/bin/env node
/**
 * Sync merged PR bot feedback matrix to in-repo HTML + JSON artifacts.
 *
 * Usage:
 *   node scripts/pr-bot-spreadsheet-sync.mjs [--limit N] [--pr N] [--dry-run] [--json]
 *
 * Env:
 *   GH_TOKEN / GITHUB_TOKEN — GitHub API auth (gh CLI)
 */
import {
  classifyAllBotCells,
} from './lib/pr-bot-cell-status.mjs';
import {
  DEFAULT_MATRIX_DIR,
  MATRIX_HTML_FILE,
  MATRIX_JSON_FILE,
  resolveMatrixPaths,
  writeMatrixArtifacts,
} from './lib/pr-bot-matrix-writer.mjs';
import {
  fetchMergedPrs,
  fetchPrBotMatrixRow,
  hasGh,
  repoSlug,
} from './lib/pr-bot-spreadsheet-fetch.mjs';
import { SPREADSHEET_BOT_KEYS } from './lib/pr-bot-roster.mjs';

function parseArgs(argv) {
  const out = {
    limit: 30,
    pr: null,
    dryRun: false,
    json: false,
    help: false,
    outputDir: process.env.PR_BOT_MATRIX_DIR || DEFAULT_MATRIX_DIR,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run') out.dryRun = true;
    else if (a === '--json') out.json = true;
    else if (a === '--limit' && argv[i + 1]) out.limit = Number(argv[++i]);
    else if (a.startsWith('--limit=')) out.limit = Number(a.slice('--limit='.length));
    else if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a.startsWith('--pr=')) out.pr = Number(a.slice('--pr='.length));
    else if (a === '--output-dir' && argv[i + 1]) out.outputDir = argv[++i];
    else if (a.startsWith('--output-dir=')) out.outputDir = a.slice('--output-dir='.length);
  }
  return out;
}

async function buildMatrix(owner, name, prNumbers) {
  /** @type {object[]} */
  const rows = [];
  for (const num of prNumbers) {
    const payload = await fetchPrBotMatrixRow(owner, name, num);
    if (!payload.meta.merged) continue;
    const cells = classifyAllBotCells(payload);
    rows.push({ meta: payload.meta, cells });
  }
  rows.sort((a, b) => new Date(b.meta.mergedAt) - new Date(a.meta.mergedAt));
  return rows;
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: node scripts/pr-bot-spreadsheet-sync.mjs [options]

Options:
  --limit N         Merged PRs to scan (default 30)
  --pr N            Single PR only
  --dry-run         Fetch/classify only; print output paths, do not write files
  --json            Print matrix JSON to stdout
  --output-dir DIR  Output directory (default "${DEFAULT_MATRIX_DIR}")

Artifacts:
  ${DEFAULT_MATRIX_DIR}/${MATRIX_HTML_FILE}  — colored HTML table
  ${DEFAULT_MATRIX_DIR}/${MATRIX_JSON_FILE}  — machine-readable matrix`);
    process.exit(0);
  }

  if (!hasGh()) {
    console.error('pr-bot-spreadsheet-sync: install gh CLI and authenticate (gh auth login)');
    process.exit(1);
  }

  const { owner, name } = repoSlug();
  let prNumbers;
  if (args.pr) {
    prNumbers = [args.pr];
  } else {
    const merged = fetchMergedPrs(owner, name, args.limit);
    prNumbers = merged.map((r) => r.number);
  }

  if (!prNumbers.length) {
    console.error('pr-bot-spreadsheet-sync: no merged PRs found');
    process.exit(1);
  }

  console.error(`pr-bot-spreadsheet-sync: scanning ${prNumbers.length} merged PR(s) in ${owner}/${name}…`);
  const matrixRows = await buildMatrix(owner, name, prNumbers);

  const report = {
    repo: `${owner}/${name}`,
    prCount: matrixRows.length,
    rows: matrixRows.map((r) => ({
      number: r.meta.number,
      title: r.meta.title,
      mergedAt: r.meta.mergedAt,
      url: r.meta.url,
      cells: Object.fromEntries(
        SPREADSHEET_BOT_KEYS.map((k) => [k, { status: r.cells[k].status, label: r.cells[k].label, reason: r.cells[k].reason }]),
      ),
    })),
  };

  if (args.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    for (const row of report.rows.slice(0, 5)) {
      const summary = SPREADSHEET_BOT_KEYS.map((k) => `${k}=${row.cells[k].status}`).join(' ');
      console.log(`  #${row.number}: ${summary}`);
    }
    if (report.rows.length > 5) {
      console.error(`  … and ${report.rows.length - 5} more`);
    }
  }

  const { htmlPath, jsonPath } = resolveMatrixPaths({ report, outputDir: args.outputDir });

  if (args.dryRun) {
    console.error('pr-bot-spreadsheet-sync: dry-run — would write:');
    console.error(`  ${htmlPath}`);
    console.error(`  ${jsonPath}`);
    process.exit(0);
  }

  const written = writeMatrixArtifacts({ report, outputDir: args.outputDir });
  console.error(`pr-bot-spreadsheet-sync: wrote ${matrixRows.length} row(s) to:`);
  console.error(`  ${written.htmlPath}`);
  console.error(`  ${written.jsonPath}`);
}

main().catch((err) => {
  console.error(`pr-bot-spreadsheet-sync: ${err.message}`);
  process.exit(1);
});
