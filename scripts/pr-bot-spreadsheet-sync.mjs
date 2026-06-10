#!/usr/bin/env node
/**
 * Sync merged PR bot feedback matrix to Google Sheets.
 *
 * Usage:
 *   node scripts/pr-bot-spreadsheet-sync.mjs [--limit N] [--pr N] [--dry-run] [--json]
 *
 * Env:
 *   PR_BOT_SPREADSHEET_ID — target Google Sheet ID
 *   PR_BOT_SHEET_SERVICE_ACCOUNT_JSON — GCP service account key (JSON string)
 *   GH_TOKEN / GITHUB_TOKEN — GitHub API auth (gh CLI)
 */
import {
  classifyAllBotCells,
  CELL_STATUS,
} from './lib/pr-bot-cell-status.mjs';
import {
  getSheetsAccessToken,
  writeSpreadsheetMatrix,
} from './lib/google-sheets-client.mjs';
import {
  fetchMergedPrs,
  fetchPrBotMatrixRow,
  hasGh,
  repoSlug,
} from './lib/pr-bot-spreadsheet-fetch.mjs';
import { SPREADSHEET_BOT_KEYS, SPREADSHEET_HEADER } from './lib/pr-bot-roster.mjs';

function parseArgs(argv) {
  const out = {
    limit: 30,
    pr: null,
    dryRun: false,
    json: false,
    help: false,
    sheetTitle: process.env.PR_BOT_SHEET_TITLE || 'PR Bot Matrix',
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
    else if (a === '--sheet-title' && argv[i + 1]) out.sheetTitle = argv[++i];
  }
  return out;
}

/**
 * @param {object} row
 * @returns {{ values: string[], statuses: string[] }}
 */
function rowToSheetCells(row) {
  const values = [
    String(row.meta.number),
    row.meta.title || '',
    row.meta.mergedAt || '',
    row.meta.url || '',
  ];
  const statuses = [];
  for (const key of SPREADSHEET_BOT_KEYS) {
    const cell = row.cells[key];
    values.push(cell.label);
    statuses.push(cell.status);
  }
  return { values, statuses };
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
  --limit N       Merged PRs to scan (default 30)
  --pr N          Single PR only
  --dry-run       Fetch/classify only; skip Google Sheets write
  --json          Print matrix JSON to stdout
  --sheet-title   Sheet tab name (default "PR Bot Matrix")

Secrets (for non-dry-run):
  PR_BOT_SPREADSHEET_ID
  PR_BOT_SHEET_SERVICE_ACCOUNT_JSON`);
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

  const sheetValues = [SPREADSHEET_HEADER];
  const statusMatrix = [];
  for (const row of matrixRows) {
    const { values, statuses } = rowToSheetCells(row);
    sheetValues.push(values);
    statusMatrix.push(statuses);
  }

  const report = {
    repo: `${owner}/${name}`,
    prCount: matrixRows.length,
    rows: matrixRows.map((r) => ({
      number: r.meta.number,
      title: r.meta.title,
      mergedAt: r.meta.mergedAt,
      url: r.meta.url,
      cells: Object.fromEntries(
        SPREADSHEET_BOT_KEYS.map((k) => [k, { status: r.cells[k].status, reason: r.cells[k].reason }]),
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

  if (args.dryRun) {
    console.error('pr-bot-spreadsheet-sync: dry-run — skipped Google Sheets write');
    process.exit(0);
  }

  const spreadsheetId = (process.env.PR_BOT_SPREADSHEET_ID || '').trim();
  const saJson = (process.env.PR_BOT_SHEET_SERVICE_ACCOUNT_JSON || '').trim();
  if (!spreadsheetId || !saJson) {
    console.error(
      'pr-bot-spreadsheet-sync: set PR_BOT_SPREADSHEET_ID and PR_BOT_SHEET_SERVICE_ACCOUNT_JSON (or use --dry-run)',
    );
    process.exit(1);
  }

  const accessToken = await getSheetsAccessToken(saJson);
  const botColumnOffset = SPREADSHEET_HEADER.length - SPREADSHEET_BOT_KEYS.length;
  await writeSpreadsheetMatrix({
    spreadsheetId,
    accessToken,
    values: sheetValues,
    statusMatrix,
    botColumnOffset,
    sheetTitle: args.sheetTitle,
  });

  console.error(`pr-bot-spreadsheet-sync: wrote ${matrixRows.length} row(s) to spreadsheet ${spreadsheetId}`);
}

main().catch((err) => {
  console.error(`pr-bot-spreadsheet-sync: ${err.message}`);
  process.exit(1);
});
