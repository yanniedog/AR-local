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
  ['reports/pr-bot-matrix.md', true],
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
  ['exact matrix trio', [...MATRIX_COMMIT_REL_PATHS], true],
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

// The automated matrix report must never attempt a repository mutation.
const { readFileSync } = await import('node:fs');
const { spawnSync } = await import('node:child_process');
const workflow = readFileSync(new URL('../.github/workflows/pr-bot-spreadsheet.yml', import.meta.url), 'utf8');
for (const forbidden of ['contents: write', 'pull-requests: write', 'pr:bot-matrix:commit', 'git push', 'gh pr create']) {
  if (workflow.includes(forbidden)) throw new Error(`Matrix workflow contains ${forbidden}`);
}
for (const required of ['contents: read', 'pull-requests: read', 'persist-credentials: false', 'actions/upload-artifact@v4', 'if-no-files-found: error', 'retention-days: 30', 'GITHUB_STEP_SUMMARY', 'mkdtempSync', 'types: [closed]', 'pull_request.merged == true']) {
  if (!workflow.includes(required)) throw new Error(`Matrix workflow missing ${required}`);
}
const inline = workflow.match(/node --input-type=module <<'NODE'\r?\n([\s\S]*?)\r?\n          NODE/)[1].replace(/^          /gm, '');
if (inline.includes('${{')) throw new Error('Dispatch expressions must remain environment data');
for (const [limit, pr] of [['0',''], ['101',''], ['1; echo injected',''], ['2','1; echo injected'], ['2','-1'], ['2','1000000000']]) {
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', inline], {
    encoding: 'utf8', env: { ...process.env, MATRIX_LIMIT: limit, MATRIX_PR: pr, RUNNER_TEMP: '' },
  });
  if (result.status === 0 || !/must be/.test(result.stderr)) throw new Error('Malformed dispatch input did not fail before generation');
}
console.log('PASS artifact-only matrix workflow: read-only output, merged trigger and invalid dispatch controls');
