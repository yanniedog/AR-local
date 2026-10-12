#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { PRODUCT_CI_WORKFLOWS, getApplicableProductCi, pathMatches } from './lib/pr-product-ci-policy.mjs';
import { readProductCi, evaluateProductCi, latestProductRun, readApiPages } from './lib/pr-product-ci.mjs';
import { readRequiredCi, readMergeCi, readUniversalCheck } from './lib/pr-ci-readiness.mjs';
import { mergePullRequest } from './lib/pr-merge.mjs';
import { progressPullRequest } from './lib/pr-branch-sync.mjs';

const head = 'a'.repeat(40), base = 'b'.repeat(40);
const repository = 'owner/repo';
const workflow = PRODUCT_CI_WORKFLOWS.find((item) => item.name === 'app-ci');
const meta = { number: 42, state: 'open', headSha: head, baseSha: base, baseRef: 'main',
  headRef: 'feature', headRepository: repository, repository, changedFiles: 1 };
const pr = { number: 42, state: 'open', changed_files: 1, head: { sha: head, ref: 'feature', repo: { full_name: repository } },
  base: { sha: base, ref: 'main', repo: { full_name: repository } } };
const run = { id: 10, run_attempt: 1, workflow_id: 20, path: workflow.path,
  run_started_at: '2026-10-12T01:00:00Z',
  event: 'pull_request', head_sha: head, head_branch: 'feature', repository: { full_name: repository },
  head_repository: { full_name: repository }, pull_requests: [], status: 'completed', conclusion: 'success' };
const jobs = workflow.jobs.map((name, index) => ({ id: index + 1, name, run_id: run.id, head_sha: head,
  status: 'completed', conclusion: 'success' }));
const evaluate = (observed = {}, selected = workflow) => evaluateProductCi({ meta, workflows: [selected],
  observations: { [selected.path]: { run, jobs, ...observed } } });
assert.equal(evaluate().failed, false);
assert.equal(evaluate().pending, false);
assert.equal(evaluate({ run: undefined }).pending, true, 'missing workflow blocks');
for (const status of ['queued', 'in_progress', 'waiting', 'requested', 'pending']) {
  assert.equal(evaluate({ run: { ...run, status } }).pending, true, `${status} blocks`);
}
for (const conclusion of ['failure', 'cancelled', 'skipped', 'neutral', 'timed_out', 'action_required', null]) {
  assert.equal(evaluate({ run: { ...run, conclusion } }).failed, true, `${conclusion} blocks`);
}
assert.equal(evaluate({ jobs: jobs.slice(1) }).failed, true, 'missing expected job blocks despite successful workflow');
assert.equal(evaluate({ jobs: [...jobs, jobs[0]] }).failed, true, 'ambiguous duplicate jobs block');
assert.equal(evaluate({ jobs: jobs.map((job) => ({ ...job, head_sha: base })) }).failed, true, 'jobs from another head block');
assert.equal(evaluate({ jobs: jobs.map((job) => ({ ...job, run_id: 9 })) }).failed, true, 'jobs from another run block');
assert.equal(evaluate({ jobs: [{ ...jobs[0], conclusion: 'skipped' }, ...jobs.slice(1)] }).failed, true);

const identified = { ...workflow, id: 20 };
for (const wrong of [{ workflow_id: 21 }, { path: 'other.yml' }, { event: 'push' }, { head_sha: base },
  { repository: { full_name: 'attacker/repo' } }, { head_repository: { full_name: 'attacker/repo' } },
  { head_branch: 'other' }, { pull_requests: [{ number: 43 }] }]) {
  assert.equal(latestProductRun([{ ...run, ...wrong }], meta, identified), undefined, 'untrusted workflow source rejected');
}
assert.equal(latestProductRun([run, { ...run, id: 11, status: 'queued' }], meta, identified).id, 11);
assert.equal(latestProductRun([run, { ...run, run_attempt: 2, status: 'queued' }], meta, identified).run_attempt, 2);
assert.equal(latestProductRun([{ ...run, id: 11 }, { ...run, run_attempt: 2, status: 'queued' }], meta, identified).id, 10,
  'a rerun of an older run cannot hide behind a newer successful run');
assert.equal(latestProductRun([{ ...run, id: 11 }, { ...run, run_attempt: 2, conclusion: 'failure',
  run_started_at: '2026-10-12T02:00:00Z' }], meta, identified).conclusion, 'failure');

assert.deepEqual(getApplicableProductCi(['README.md']), []);
assert.throws(() => getApplicableProductCi([{}]), /Invalid changed-file/);
assert.throws(() => getApplicableProductCi([null]), /Invalid changed-file/);
assert.deepEqual(getApplicableProductCi(['app_payload.py']).map((item) => item.name), ['app-ci']);
assert.deepEqual(getApplicableProductCi(['app_payload_secure_upload.py']).map((item) => item.name), ['app-ci', 'app-data-service-ci']);
assert.equal(getApplicableProductCi([{ filename: 'docs/moved.md', previous_filename: 'cdr_daily.py' }])[0].name, 'app-ci');
assert.equal(getApplicableProductCi(['scripts/lib/pr-required-gate.mjs'])[0].name, 'pr-closeout-ci');
for (const file of ['deploy/pi/ar-local-ingest-watchdog.service', 'dashboard/app.js', 'scripts/check.py', 'cdr_domain/models.py', 'cdr_pipeline/stage.py']) {
  assert.ok(getApplicableProductCi([file]).some((item) => item.name === 'app-ci'), `${file} requires full product suite`);
}
assert.equal(pathMatches('nested/cdr_daily.py', 'cdr_*.py'), false);
assert.throws(() => pathMatches('a', '!**'), /Unsupported/);
assert.throws(() => pathMatches('a.py', 'a\\.py'), /Unsupported/);
assert.equal(pathMatches('fileXpy', 'file.py'), false, 'literal dots are escaped');

// Every PR workflow needs an intentional classification. Adding a new product
// workflow must update the required policy instead of silently making it advisory.
const advisoryWorkflowPaths = new Set([
  '.github/workflows/gemini-review.yml',
  '.github/workflows/pr-bot-presence-gate.yml',
  '.github/workflows/pr-bot-spreadsheet.yml',
]);
function hasPullRequestTrigger(source) {
  const cleaned = `${source.replace(/\r/g, '').replace(/^\s*#.*$/gm, '')}\n`;
  const on = cleaned.match(/^(?:on|'on'|"on"):[ \t]*([^\n]*)(?:\n((?:[ \t][^\n]*\n|\n)*))?/m);
  if (!on) return false;
  const inline = on[1].split('#')[0];
  if (/(?:^|[\[\{,\s'"])pull_request(?:$|[\]\}:,\s'"])/.test(inline)) return true;
  const block = on[2] || '';
  const indentation = block.match(/^( +)\S/m)?.[1] || '  ';
  return new RegExp(`^${indentation}(?:pull_request|'pull_request'|"pull_request")\\s*:`, 'm').test(block);
}
function unclassifiedPrWorkflows(entries) {
  const productPaths = new Set(PRODUCT_CI_WORKFLOWS.map((item) => item.path));
  return entries.filter((item) => hasPullRequestTrigger(item.source) &&
    !productPaths.has(item.path) && !advisoryWorkflowPaths.has(item.path)).map((item) => item.path);
}
const workflowDirectory = new URL('../.github/workflows/', import.meta.url);
const workflowInventory = fs.readdirSync(workflowDirectory).filter((name) => /\.ya?ml$/.test(name))
  .map((name) => ({ path: `.github/workflows/${name}`, source: fs.readFileSync(new URL(name, workflowDirectory), 'utf8') }));
assert.deepEqual(unclassifiedPrWorkflows(workflowInventory), [], 'Every pull_request workflow must be registered as product CI or explicitly advisory/reporting');
const futureWorkflow = '.github/workflows/firebase-ci.yaml';
for (const trigger of ['on:\n  pull_request:\n    paths: [firebase/**]\n', 'on: [push, pull_request]\n', "'on': pull_request\n"]) {
  assert.deepEqual(unclassifiedPrWorkflows([{ path: futureWorkflow, source: `${trigger}jobs:\n  test:\n    runs-on: ubuntu-latest\n` }]), [futureWorkflow]);
}
assert.equal(hasPullRequestTrigger('on:\n  workflow_dispatch:\n    inputs:\n      pull_request:\n        type: string\njobs:\n'), false);
assert.equal(hasPullRequestTrigger('on:\n  pull_request_target:\n  pull_request_review:\njobs:\n'), false);
assert.ok(getApplicableProductCi([futureWorkflow]).some((item) => item.name === 'pr-closeout-ci'));

// Guard policy drift with the real workflow triggers, not test-only copies.
for (const expected of PRODUCT_CI_WORKFLOWS) {
  const source = fs.readFileSync(new URL(`../${expected.path}`, import.meta.url), 'utf8');
  for (const event of ['pull_request', 'push']) {
    const section = source.split(new RegExp(`^  ${event}:`, 'm'))[1]?.split(/^\S|^  [a-z_]+:/m)[0];
    assert.ok(section, `${expected.name} has ${event} trigger`);
    const paths = section.split('paths:')[1];
    assert.ok(paths, `${expected.name} has paths policy`);
    const actual = [...paths.matchAll(/'([^']+)'/g)].map((match) => match[1]);
    assert.deepEqual(actual.sort(), [...expected.paths].sort(), `${expected.name} ${event} path policy drift`);
  }
}

function fixture(overrides = {}) {
  const calls = [];
  let prReads = 0;
  const api = (endpoint) => {
    calls.push(endpoint);
    if (overrides.api) {
      const value = overrides.api(endpoint, calls);
      if (value !== undefined) return value;
    }
    if (endpoint === `repos/${repository}`) return { default_branch: 'main' };
    if (endpoint === `repos/${repository}/pulls/42`) {
      prReads += 1;
      return structuredClone(prReads > 1 && overrides.finalPr ? overrides.finalPr : overrides.pr || pr);
    }
    if (endpoint.includes('/pulls/42/files?')) return [{ filename: 'cdr_daily.py' }];
    if (endpoint.endsWith('/actions/workflows/app-ci.yml')) return { id: 20, path: workflow.path, name: workflow.name };
    if (endpoint.includes('/actions/workflows/20/runs?')) return { workflow_runs: overrides.runs || [run], total_count: overrides.runs?.length ?? 1 };
    if (endpoint.includes('/actions/runs/10/jobs?')) return { jobs, total_count: jobs.length };
    if (endpoint.endsWith('/actions/runs/10')) return overrides.refreshedRun || run;
    throw new Error(`Unexpected request: ${endpoint}`);
  };
  return { api, calls };
}
const read = (overrides = {}) => readProductCi(42, { repository, ...fixture(overrides) });
assert.equal(read().ok, true);
assert.equal(read().failed, false);
assert.equal(read({ runs: [] }).pending, true);
assert.equal(read({ runs: [{ ...run, status: 'in_progress', conclusion: null }], refreshedRun: { ...run, status: 'in_progress', conclusion: null } }).pending, true);
assert.equal(read({ refreshedRun: { ...run, run_attempt: 2, status: 'queued', conclusion: null } }).pending, true);
assert.equal(read({ pr: { ...pr, changed_files: 2 } }).ok, false, 'truncated files fail closed');
assert.equal(read({ pr: { ...pr, state: 'closed' } }).ok, false);
assert.equal(read({ pr: { ...pr, base: { ...pr.base, ref: 'feature-base' } } }).ok, false);
assert.equal(read({ finalPr: { ...pr, head: { ...pr.head, sha: base } } }).pending, true, 'head changes during read block');
assert.equal(read({ finalPr: { ...pr, base: { ...pr.base, sha: head } } }).pending, true, 'base changes during read block');
assert.equal(read({ api: () => { throw new Error('API unavailable'); } }).ok, false);
assert.equal(readProductCi(42, { repository, ...fixture(), expectedHeadSha: base }).ok, false);

const many = Array.from({ length: 300 }, (_, index) => ({ filename: `docs/${index}.md` }));
many.push({ filename: 'cdr_daily.py' });
const paged = fixture({ pr: { ...pr, changed_files: many.length }, finalPr: { ...pr, changed_files: many.length },
  api: (endpoint) => endpoint.includes('/files?') ? many.slice((Number(new URLSearchParams(endpoint.split('?')[1]).get('page')) - 1) * 100,
    Number(new URLSearchParams(endpoint.split('?')[1]).get('page')) * 100) : undefined });
assert.equal(readProductCi(42, { repository, api: paged.api }).checks.length, 1, 'path past GitHub 300-file trigger limit still requires CI');
assert.equal(paged.calls.filter((endpoint) => endpoint.includes('/files?')).length, 4);
const hundred = Array.from({ length: 100 }, () => ({}));
assert.equal(readApiPages((endpoint) => endpoint.endsWith('page=1') ? { jobs: hundred, total_count: 101 } : { jobs: [{}], total_count: 101 }, 'jobs', 'jobs').length, 101);
assert.throws(() => readApiPages(() => ({ jobs: [], total_count: 1 }), 'jobs', 'jobs'), /Incomplete/);
assert.throws(() => readApiPages(() => hundred, 'files', null, { maxPages: 2 }), /Pagination limit/);

const requiredOutput = (checks) => ({ status: 0, stdout: JSON.stringify(checks) });
const bot = { id: 100, name: 'bot-feedback-gate', head_sha: head, app: { id: 15368, slug: 'github-actions' },
  status: 'completed', conclusion: 'success', external_id: `ar-local-required:42:${head}`,
  details_url: `https://github.com/${repository}/actions/runs/100` };
const botOptions = { repository, headSha: head, api: () => ({ check_runs: [bot], total_count: 1 }) };
assert.equal(readRequiredCi(42, { ...botOptions, api: () => ({ check_runs: [], total_count: 0 }), run: () => requiredOutput([]) }).pending, true, 'missing universal check never passes');
assert.equal(readRequiredCi(42, { ...botOptions, run: () => requiredOutput([{ name: 'bot-feedback-gate', bucket: 'pass' }]) }).pending, false);
assert.equal(readRequiredCi(42, { ...botOptions, api: () => ({ check_runs: [{ ...bot, conclusion: 'skipped' }] }), run: () => requiredOutput([]) }).failed, true);
const duplicateCustom = [100, 101].map((id) => ({ name: 'bot-feedback-gate', bucket: 'pass', workflow: '', link: `https://github.com/${repository}/actions/runs/${id}` }));
assert.equal(readRequiredCi(42, { ...botOptions, api: () => ({ check_runs: [bot, { ...bot, id: 101, status: 'in_progress' }] }),
  run: () => requiredOutput(duplicateCustom) }).pending, true, 'custom check duplicates retain trusted API producer identity');
assert.equal(readUniversalCheck(42, { ...botOptions, api: () => ({ check_runs: [{ ...bot, app: { id: 999, slug: 'attacker' } }] }) }).bucket, 'pending');
assert.equal(readUniversalCheck(42, { ...botOptions, api: () => ({ check_runs: [{ ...bot, external_id: `ar-local-required:43:${head}` }] }) }).bucket, 'pending');
const ciGreen = { ok: true, ...meta, pending: false, failed: false, pendingNames: [], failedNames: [], checks: [] };
const currentView = { number: 42, state: 'OPEN', headRefOid: head, baseRefOid: base, baseRefName: 'main' };
const mergedRead = { readProduct: () => ciGreen, read: () => currentView,
  api: botOptions.api, run: () => requiredOutput([{ name: 'bot-feedback-gate', bucket: 'pass' }]) };
assert.equal(readMergeCi(42, mergedRead).pending, false);
assert.equal(readMergeCi(42, { ...mergedRead, read: () => ({ ...currentView, headRefOid: base }) }).pending, true);
assert.equal(readMergeCi(42, { ...mergedRead, readProduct: () => ({ ...ciGreen, pending: true, pendingNames: ['payload'] }) }).pending, true);

for (const blocked of [{ ...ciGreen, pending: true }, { ...ciGreen, failed: true }, { ok: false, error: 'denied' }]) {
  let mutations = 0;
  const outcome = mergePullRequest(42, { readCi: () => blocked, run: () => { mutations += 1; return { status: 0 }; } });
  assert.equal(outcome.ok, false);
  assert.equal(mutations, 0, 'pending/failed/error CI cannot invoke merge');
}
let mergeArgs;
assert.equal(mergePullRequest(42, { readCi: () => ciGreen, run: (_, args) => { mergeArgs = args; return { status: 0 }; } }).ok, true);
assert.equal(mergeArgs[mergeArgs.indexOf('--match-head-commit') + 1], head, 'merge is pinned to checked commit');
assert.equal(mergePullRequest(42, { readCi: () => ciGreen, extraArgs: ['--admin'], run: () => { throw new Error('must not run'); } }).ok, false);
assert.equal(mergePullRequest(42, { readCi: () => ciGreen, dryRun: true, run: () => { throw new Error('must not run'); } }).ok, true);
let armed = false;
const updated = progressPullRequest(42, { fetchMeta: () => ({ number: 42, mergeStateStatus: 'BEHIND' }),
  updateBranch: () => ({ ok: true, action: 'updated', detail: 'updated', exitCode: 0 }),
  enableMerge: () => { armed = true; return { ok: true }; } });
assert.equal(updated.ok, false);
assert.equal(updated.sync.exitCode, 2);
assert.equal(armed, false, 'branch refresh requires a later fresh CI evaluation');
console.log('verify-pr-product-ci: pass (missing/pending/failed CI, identities, pagination, reruns, races, scopes and merge pinning)');
