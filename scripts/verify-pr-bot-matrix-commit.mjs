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
const { buildMatrixMarkdown } = await import('./lib/pr-bot-matrix-markdown.mjs');
const markdown = buildMatrixMarkdown({ generatedAt: '2026-01-01', prCount: 0, rows: [] });
const summaryLine = inline.split('\n').find(line => line.startsWith('const summary = '));
const summary = new Function('readFileSync', 'path', 'output', `${summaryLine}; return summary;`)(() => markdown, { join: () => '' }, '');
if (summary.includes('](pr-bot-matrix.') || !markdown.includes('](pr-bot-matrix.')) throw new Error('Job summary retains artifact-relative links or artifact footer was lost');
const operator = readFileSync(new URL('./github-bot-gates-operator.mjs', import.meta.url), 'utf8');
for (const unsafe of ['DELETE legacy branch protection', 'commits reports/* directly to main', 'mode Always (actor_id 15368)']) {
  if (operator.includes(unsafe)) throw new Error('Operator still requests matrix protection bypass');
}
console.log('PASS summary removes artifact-relative footer; operator preserves protection');

// Unsafe imported templates must refuse before local verifier commands or GitHub access.
const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import('node:fs');
const { tmpdir } = await import('node:os');
const { join, resolve } = await import('node:path');
const ruleset = JSON.parse(readFileSync(new URL('../.github/rulesets/main-bot-gates.json', import.meta.url), 'utf8'));
if (!Array.isArray(ruleset.bypass_actors) || ruleset.bypass_actors.length) throw new Error('Imported template permits protection bypass');
const fixture = mkdtempSync(join(tmpdir(), 'ar-ruleset-refusal-'));
try {
  mkdirSync(join(fixture, 'scripts'));
  mkdirSync(join(fixture, '.github', 'rulesets'), { recursive: true });
  writeFileSync(join(fixture, 'scripts', 'github-bot-gates-operator.mjs'), operator);
  for (const actors of [[{ actor_id: 15368, actor_type: 'Integration', bypass_mode: 'always' }], [{ actor_id: 5, actor_type: 'RepositoryRole', bypass_mode: 'pull_request' }], null]) {
    writeFileSync(join(fixture, '.github', 'rulesets', 'main-bot-gates.json'), JSON.stringify({ ...ruleset, bypass_actors: actors }));
    const result = spawnSync(process.execPath, [join(fixture, 'scripts', 'github-bot-gates-operator.mjs')], { encoding: 'utf8' });
    if (result.status !== 1 || !result.stderr.includes('must declare an empty bypass_actors list') || result.stdout.includes('Local policy self-tests')) {
      throw new Error('Unsafe ruleset did not refuse before operator verification');
    }
  }
} finally {
  const target = resolve(fixture);
  if (!target.startsWith(resolve(tmpdir()) + (process.platform === 'win32' ? '\\' : '/')) || !target.includes('ar-ruleset-refusal-')) throw new Error('Unexpected temporary fixture path');
  rmSync(target, { recursive: true, force: true });
}
console.log('PASS operator rejects Actions, role and malformed bypass lists');
