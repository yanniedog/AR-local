#!/usr/bin/env node
import { CELL_STATUS } from './lib/pr-bot-cell-status.mjs';
import { buildMatrixMarkdown, buildMatrixPrBody, formatCellMarkdown, MATRIX_MD_FILE } from './lib/pr-bot-matrix-markdown.mjs';
import { buildMatrixHtml, resolveMatrixPaths, writeMatrixArtifacts } from './lib/pr-bot-matrix-writer.mjs';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const r = { repo: 'o/r', prCount: 1, generatedAt: '2026-01-01', rows: [{ number: 1, title: 't', mergedAt: '2026-01-01', url: 'http://x', cells: { gemini: { status: CELL_STATUS.GREEN, label: 'OK' }, codex: { status: CELL_STATUS.YELLOW, label: 'Open' } } }] };
const fail = [];
const ok = (c, m) => { if (!c) fail.push(m); };
ok(formatCellMarkdown({ status: CELL_STATUS.GREEN, label: 'OK' }) === '**PASS**', 'PASS');
ok(formatCellMarkdown({ status: CELL_STATUS.YELLOW, label: 'Open' }) === '**FAIL**', 'FAIL');
ok(buildMatrixMarkdown(r).includes('| PR | Title | Merged |'), 'header');
ok(buildMatrixPrBody(r).includes(MATRIX_MD_FILE), 'pr body');
ok(buildMatrixHtml(r).includes(MATRIX_MD_FILE), 'html link');
const tmp = mkdtempSync(path.join(tmpdir(), 'mx-'));
try { ok(readFileSync(writeMatrixArtifacts({ report: r, outputDir: tmp }).mdPath, 'utf8').includes('**PASS**'), 'write'); } finally { rmSync(tmp, { recursive: true, force: true }); }
ok(resolveMatrixPaths({ report: r }).markdown.includes('# PR bot feedback matrix'), 'resolve');
if (fail.length) { console.error('FAIL', fail); process.exit(1); }
console.log('PASS verify-pr-bot-matrix-writer');
