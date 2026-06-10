/**
 * GitHub-native markdown rendering for the PR bot feedback matrix.
 */
import { CELL_LABELS, CELL_STATUS } from './pr-bot-cell-status.mjs';
import { BOT_KEY_LABELS, SPREADSHEET_BOT_KEYS } from './pr-bot-roster.mjs';

export const MATRIX_MD_FILE = 'pr-bot-matrix.md';
const MATRIX_HTML_FILE = 'pr-bot-matrix.html';
const MATRIX_JSON_FILE = 'pr-bot-matrix.json';

/** Scannable PASS/FAIL labels for GitHub markdown (distinct from HTML cell labels). */
export const MARKDOWN_CELL_LABELS = {
  [CELL_STATUS.GREEN]: 'PASS',
  [CELL_STATUS.YELLOW]: 'FAIL',
  [CELL_STATUS.GREY]: '—',
  [CELL_STATUS.RED]: 'LIMIT',
};

const STATUS_LEGEND = [
  [CELL_STATUS.GREEN, 'Substantive feedback addressed before merge'],
  [CELL_STATUS.YELLOW, 'Substantive feedback with open threads at merge'],
  [CELL_STATUS.GREY, 'No bot activity'],
  [CELL_STATUS.RED, 'Quota/limit notice only'],
];

function escapeMarkdownCell(text) {
  return String(text ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ').replace(/\r/g, '');
}

function truncateText(text, maxLen = 55) {
  const s = String(text ?? '');
  return s.length <= maxLen ? s : `${s.slice(0, maxLen - 1)}…`;
}

export function formatCellMarkdown(cell) {
  const status = cell?.status ?? CELL_STATUS.GREY;
  const label = MARKDOWN_CELL_LABELS[status] ?? MARKDOWN_CELL_LABELS[CELL_STATUS.GREY];
  if (status === CELL_STATUS.GREY) return label;
  return `**${label}**`;
}

function formatMergedDate(iso) {
  const s = String(iso ?? '');
  return s.length >= 10 ? s.slice(0, 10) : s;
}

function legendStatusCell(status) {
  if (status === CELL_STATUS.GREY) return MARKDOWN_CELL_LABELS[CELL_STATUS.GREY];
  return `**${MARKDOWN_CELL_LABELS[status] || CELL_LABELS[status]}**`;
}

export function buildMatrixMarkdown(report, opts = {}) {
  const generatedAt = report.generatedAt || new Date().toISOString();
  const maxRows = opts.maxRows ?? null;
  const titleMaxLen = opts.titleMaxLen ?? 55;
  const allRows = report.rows || [];
  const rows = maxRows == null ? allRows : allRows.slice(0, maxRows);
  const truncated = maxRows != null && allRows.length > maxRows;
  const botHeaders = SPREADSHEET_BOT_KEYS.map((k) => BOT_KEY_LABELS[k] || k);
  const header = ['PR', 'Title', 'Merged', ...botHeaders].join(' | ');
  const separator = ['---', '---', '---', ...botHeaders.map(() => '---')].join(' | ');

  const bodyRows = rows.map((row) => {
    const botCells = SPREADSHEET_BOT_KEYS.map((key) => formatCellMarkdown(
      row.cells?.[key] || { status: CELL_STATUS.GREY, label: CELL_LABELS[CELL_STATUS.GREY] },
    ));
    return `[#${row.number}](${row.url}) | ${escapeMarkdownCell(truncateText(row.title, titleMaxLen))} | ${formatMergedDate(row.mergedAt)} | ${botCells.join(' | ')}`;
  });

  const legendRows = STATUS_LEGEND.map(([status, text]) => `| ${legendStatusCell(status)} | ${text} |`);
  const lines = [
    '# PR bot feedback matrix', '', `**Repo:** ${report.repo || ''} · **${report.prCount ?? 0}** merged PR(s) · generated ${generatedAt}`,
    '', '## Legend', '', '| Status | Meaning |', '| --- | --- |', ...legendRows,
    '', '## Matrix', '', `| ${header} |`, `| ${separator} |`,
  ];
  if (bodyRows.length) {
    bodyRows.forEach((line) => lines.push(`| ${line} |`));
  } else {
    const emptyCells = Array(2 + botHeaders.length).fill('').join(' | ');
    lines.push(`| _No merged PRs yet_ | ${emptyCells} |`);
  }
  if (truncated) lines.push('', `_Showing ${maxRows} of ${report.prCount ?? allRows.length} rows._`);
  lines.push('', '## Machine-readable data', '', `JSON: [\`${MATRIX_JSON_FILE}\`](${MATRIX_JSON_FILE}). HTML: [\`${MATRIX_HTML_FILE}\`](${MATRIX_HTML_FILE}).`, '');
  return `${lines.join('\n')}\n`;
}

export function buildMatrixPrBody(report, opts = {}) {
  const maxRows = opts.maxRows ?? 15;
  const generatedAt = report.generatedAt || new Date().toISOString();
  return [
    'Automated sync from `pr-bot-spreadsheet` workflow.', '',
    `Generated **${generatedAt}** · **${report.prCount ?? 0}** merged PR(s).`, '',
    `Primary view: [\`reports/${MATRIX_MD_FILE}\`](reports/${MATRIX_MD_FILE}).`, '',
    buildMatrixMarkdown(report, { maxRows, titleMaxLen: 45 }),
  ].join('\n');
}
