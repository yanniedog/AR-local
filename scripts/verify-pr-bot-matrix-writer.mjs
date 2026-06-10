#!/usr/bin/env node
import { CELL_STATUS } from './lib/pr-bot-cell-status.mjs';
import { buildMatrixMarkdown, buildMatrixPrBody, formatCellMarkdown, MATRIX_MD_FILE } from './lib/pr-bot-matrix-markdown.mjs';
const r = { repo:'o/r', prCount:1, generatedAt:'2026-01-01', rows:[{number:1,title:'t',mergedAt:'2026-01-01',url:'http://x',cells:{gemini:{status:CELL_STATUS.GREEN}}}] };
if (formatCellMarkdown({status:CELL_STATUS.GREEN}) !== '**PASS**') process.exit(1);
if (!buildMatrixMarkdown(r).includes('**PASS**')) process.exit(1);
if (!buildMatrixPrBody(r).includes(MATRIX_MD_FILE)) process.exit(1);
console.log('PASS verify-pr-bot-matrix-writer');
