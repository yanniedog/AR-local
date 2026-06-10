/**
 * Write PR bot feedback matrix as committed repo artifacts (Markdown + HTML + JSON).
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { CELL_COLORS, CELL_LABELS, CELL_STATUS } from './pr-bot-cell-status.mjs';
import { BOT_KEY_LABELS, SPREADSHEET_BOT_KEYS } from './pr-bot-roster.mjs';
import { buildMatrixMarkdown, buildMatrixPrBody } from './pr-bot-matrix-markdown.mjs';

export const DEFAULT_MATRIX_DIR = 'reports';
export const MATRIX_MD_FILE = 'pr-bot-matrix.md';
export const MATRIX_HTML_FILE = 'pr-bot-matrix.html';
export const MATRIX_JSON_FILE = 'pr-bot-matrix.json';

export { buildMatrixMarkdown, buildMatrixPrBody, formatCellMarkdown } from './pr-bot-matrix-markdown.mjs';

export function rgbToHex({ red, green, blue }) {
  const toByte = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255);
  return `#${[toByte(red), toByte(green), toByte(blue)].map((n) => n.toString(16).padStart(2, '0')).join('')}`;
}

const STATUS_CSS = Object.fromEntries(Object.entries(CELL_COLORS).map(([s, rgb]) => [s, rgbToHex(rgb)]));

function escapeHtml(text) {
  return String(text ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function buildMatrixHtml(report) {
  const generatedAt = report.generatedAt || new Date().toISOString();
  const legend = [
    [CELL_STATUS.GREEN, 'Substantive feedback addressed before merge'],
    [CELL_STATUS.YELLOW, 'Substantive feedback with open threads at merge'],
    [CELL_STATUS.GREY, 'No bot activity'],
    [CELL_STATUS.RED, 'Quota/limit notice only'],
  ];
  const headerCells = ['PR #', 'Title', 'Merged At', ...SPREADSHEET_BOT_KEYS.map((k) => BOT_KEY_LABELS[k] || k)]
    .map((h) => `<th scope="col">${escapeHtml(h)}</th>`).join('');
  const bodyRows = (report.rows || []).map((row) => {
    const metaCells = [
      `<td class="meta"><a href="${escapeHtml(row.url)}">#${escapeHtml(row.number)}</a></td>`,
      `<td class="meta title">${escapeHtml(row.title)}</td>`,
      `<td class="meta">${escapeHtml(row.mergedAt || '')}</td>`,
    ];
    const botCells = SPREADSHEET_BOT_KEYS.map((key) => {
      const cell = row.cells?.[key] || { status: CELL_STATUS.GREY, label: CELL_LABELS[CELL_STATUS.GREY], reason: '' };
      const bg = STATUS_CSS[cell.status] || STATUS_CSS[CELL_STATUS.GREY];
      return `<td class="bot" style="background:${bg}" title="${escapeHtml(cell.reason || cell.status)}">${escapeHtml(cell.label)}</td>`;
    });
    return `<tr>${metaCells.join('')}${botCells.join('')}</tr>`;
  }).join('\n');
  const legendItems = legend.map(([status, text]) => {
    const bg = STATUS_CSS[status];
    return `<li><span class="swatch" style="background:${bg}">${escapeHtml(CELL_LABELS[status])}</span> ${escapeHtml(text)}</li>`;
  }).join('\n');
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PR bot feedback matrix — ${escapeHtml(report.repo || '')}</title>
<style>:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{margin:1rem 1.25rem 2rem;line-height:1.4}h1{font-size:1.25rem;margin:0 0 .25rem}.meta-line{color:#555;font-size:.9rem;margin-bottom:1rem}table{border-collapse:collapse;width:100%;font-size:.85rem}th,td{border:1px solid #ccc;padding:.35rem .5rem;vertical-align:top}th{background:#d9d9d9;text-align:left;position:sticky;top:0}td.meta{background:#fafafa}td.title{max-width:28rem}td.bot{text-align:center;font-weight:600;min-width:4.5rem}ul.legend{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:.75rem 1.25rem}.swatch{display:inline-block;min-width:2.5rem;text-align:center;padding:.1rem .35rem;border:1px solid #bbb;border-radius:2px;margin-right:.35rem;font-weight:600}</style></head>
<body><h1>PR bot feedback matrix</h1>
<p class="meta-line">Repo: <strong>${escapeHtml(report.repo || '')}</strong> · ${report.prCount ?? 0} merged PR(s) · generated ${escapeHtml(generatedAt)}</p>
<p class="meta-line">GitHub view: <a href="${MATRIX_MD_FILE}">${MATRIX_MD_FILE}</a> · JSON: <a href="${MATRIX_JSON_FILE}">${MATRIX_JSON_FILE}</a></p>
<ul class="legend">${legendItems}</ul><table><thead><tr>${headerCells}</tr></thead><tbody>${bodyRows}</tbody></table></body></html>`;
}

export function buildMatrixJson(report) {
  return `${JSON.stringify({
    repo: report.repo, prCount: report.prCount,
    generatedAt: report.generatedAt || new Date().toISOString(),
    bots: SPREADSHEET_BOT_KEYS.map((key) => ({ key, label: BOT_KEY_LABELS[key] || key })),
    statusLegend: { green: 'feedback addressed before merge', yellow: 'open threads at merge', grey: 'no bot activity', red: 'quota/limit only' },
    rows: report.rows || [],
  }, null, 2)}\n`;
}

export function resolveMatrixPaths({ report, outputDir = DEFAULT_MATRIX_DIR }) {
  const dir = path.resolve(process.cwd(), outputDir);
  const mdPath = path.join(dir, MATRIX_MD_FILE);
  const htmlPath = path.join(dir, MATRIX_HTML_FILE);
  const jsonPath = path.join(dir, MATRIX_JSON_FILE);
  const stamped = { ...report, generatedAt: report.generatedAt || new Date().toISOString() };
  return { mdPath, htmlPath, jsonPath, markdown: buildMatrixMarkdown(stamped), html: buildMatrixHtml(stamped), json: buildMatrixJson(stamped), prBody: buildMatrixPrBody(stamped) };
}

export function writeMatrixArtifacts({ report, outputDir = DEFAULT_MATRIX_DIR }) {
  const { mdPath, htmlPath, jsonPath, markdown, html, json } = resolveMatrixPaths({ report, outputDir });
  mkdirSync(path.dirname(mdPath), { recursive: true });
  writeFileSync(mdPath, markdown, 'utf8');
  writeFileSync(htmlPath, html, 'utf8');
  writeFileSync(jsonPath, json, 'utf8');
  return { mdPath, htmlPath, jsonPath };
}
