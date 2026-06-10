#!/usr/bin/env node
/**
 * Self-test for pr-bot-matrix-commit helpers. Run: node scripts/verify-pr-bot-matrix-commit.mjs
 */
import {
  isMatrixCommitOnly,
  isMatrixCommitPath,
  MATRIX_COMMIT_REL_PATHS,
  MATRIX_COMMIT_MESSAGE,
} from './lib/pr-bot-matrix-commit.mjs';

const failures = [];

for (const [path, want] of [
  ['reports/pr-bot-matrix.html', true],
  ['reports/pr-bot-matrix.json', true],
  ['reports/other.json', false],
  ['scripts/pr-bot-matrix-commit.mjs', false],
]) {
  if (isMatrixCommitPath(path) !== want) {
    failures.push(`isMatrixCommitPath(${path}) !== ${want}`);
  }
}

for (const [name, paths, want] of [
  ['exact matrix pair', [...MATRIX_COMMIT_REL_PATHS], true],
  ['duplicate matrix paths', [...MATRIX_COMMIT_REL_PATHS, ...MATRIX_COMMIT_REL_PATHS], false],
  ['duplicate html', ['reports/pr-bot-matrix.html', 'reports/pr-bot-matrix.html'], false],
  ['html only', ['reports/pr-bot-matrix.html'], false],
  ['matrix + workflow', [...MATRIX_COMMIT_REL_PATHS, '.github/workflows/pr-bot-spreadsheet.yml'], false],
  ['empty', [], false],
]) {
  if (isMatrixCommitOnly(paths) !== want) {
    failures.push(`${name}: isMatrixCommitOnly !== ${want}`);
  }
}

if (!MATRIX_COMMIT_MESSAGE.includes('matrix')) {
  failures.push('MATRIX_COMMIT_MESSAGE should mention matrix');
}

if (failures.length) {
  console.error('FAIL verify-pr-bot-matrix-commit:');
  for (const f of failures) console.error('  -', f);
  process.exit(1);
}

console.log(`PASS verify-pr-bot-matrix-commit: ${MATRIX_COMMIT_REL_PATHS.length} paths + commit message`);
