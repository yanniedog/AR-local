import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  combineRequiredGate, discoverGatePrs, publishRequiredGate, validPrNumber,
} from './lib/pr-required-gate.mjs';

const repository = 'owner/repo';
const headSha = 'a'.repeat(40), baseSha = 'b'.repeat(40);
const pr = { number: 42, state: 'open', changed_files: 1, title: 'fix: gates',
  user: { login: 'owner', type: 'User' },
  head: { sha: headSha, ref: 'topic', repo: { full_name: 'contributor/fork' } },
  base: { sha: baseSha, ref: 'main', repo: { full_name: repository } } };
const green = { ok: true, pending: false, failed: false, detail: 'All expected jobs succeeded' };
assert.equal(validPrNumber('42'), 42);
for (const value of [0, -1, 1.5, '01', '1; echo unsafe', Number.MAX_SAFE_INTEGER + 1, undefined]) {
  assert.throws(() => validPrNumber(value), /Invalid/);
}
assert.deepEqual(discoverGatePrs({ inputs: { pr_number: '42' } }, 'workflow_dispatch', repository), [42]);
assert.deepEqual(discoverGatePrs({ pull_request: pr }, 'pull_request_target', repository), [42]);
assert.deepEqual(discoverGatePrs({ issue: { number: 42, pull_request: {} } }, 'issue_comment', repository), [42]);
assert.deepEqual(discoverGatePrs({ issue: { number: 42 } }, 'issue_comment', repository), []);
assert.throws(() => discoverGatePrs({}, 'untrusted', repository), /Unsupported/);
assert.throws(() => discoverGatePrs({}, 'workflow_dispatch', '../invalid/repo'), /repository/);
const run = { event: 'pull_request', repository: { full_name: repository },
  head_repository: { full_name: 'contributor/fork' }, head_branch: 'topic', pull_requests: [] };
const apiCalls = [];
const discoveryApi = (endpoint) => {
  apiCalls.push(endpoint);
  return [pr, { ...pr, number: 43, head: { ...pr.head, ref: 'other' } },
    { ...pr, number: 44, head: { ...pr.head, repo: { full_name: 'other/fork' } } }];
};
for (const event of ['pull_request', 'pull_request_review', 'pull_request_review_comment']) {
  assert.deepEqual(discoverGatePrs({ workflow_run: { ...run, event } }, 'workflow_run', repository, discoveryApi), [42]);
}
assert.ok(apiCalls.every((endpoint) => endpoint.includes('/pulls?state=open&per_page=100&page=1')));
assert.deepEqual(discoverGatePrs({ workflow_run: { ...run, event: 'push' } }, 'workflow_run', repository), []);
assert.throws(() => discoverGatePrs({ workflow_run: { ...run, repository: { full_name: 'other/repo' } } },
  'workflow_run', repository), /repository/);

assert.equal(combineRequiredGate(green, []).conclusion, 'success');
assert.equal(combineRequiredGate({ ...green, pending: true }, []).status, 'in_progress');
assert.equal(combineRequiredGate({ ...green, failed: true }, []).conclusion, 'failure');
assert.equal(combineRequiredGate({ ok: false, error: 'API denied' }, []).conclusion, 'failure');
assert.equal(combineRequiredGate(green, [{}]).conclusion, 'failure');

function publishFixture({ initial = pr, final = initial, product = green, productError, threadError,
  apiErrorAfterCreate = false, threads = [], rerunDuringThreadRead = false, existingChecks = [],
  cleanupError } = {}) {
  const events = [];
  let reads = 0;
  let currentProduct = product;
  const api = (endpoint) => {
    events.push({ type: 'api', endpoint });
    if (endpoint.includes('/check-runs?')) {
      if (cleanupError) throw new Error(cleanupError);
      return { check_runs: existingChecks, total_count: existingChecks.length };
    }
    reads += 1;
    if (apiErrorAfterCreate && reads > 1) throw new Error('PR refresh unavailable');
    return reads > 1 ? structuredClone(final) : structuredClone(initial);
  };
  const write = (endpoint, body, method = 'POST') => {
    events.push({ type: 'write', endpoint, body: structuredClone(body), method });
    return { id: 99 };
  };
  const productReader = (number, options) => {
    events.push({ type: 'product', number, expectedHeadSha: options.expectedHeadSha });
    if (productError) throw new Error(productError);
    return currentProduct;
  };
  const threadReader = (owner, name, number) => {
    events.push({ type: 'threads', owner, name, number });
    if (threadError) throw new Error(threadError);
    if (rerunDuringThreadRead) currentProduct = { ...green, pending: true, detail: 'Product rerun started' };
    return { threads };
  };
  const result = publishRequiredGate(42, { repository, api, write, productReader, threadReader,
    now: () => '2026-10-12T00:00:00.000Z', detailsUrl: 'https://github.com/owner/repo/actions/runs/7' });
  return { result, events, writes: events.filter((event) => event.type === 'write') };
}
const successful = publishFixture();
assert.equal(successful.result.conclusion, 'success');
assert.deepEqual(successful.events.map((event) => event.type), ['api', 'write', 'api', 'threads', 'product', 'api', 'write']);
assert.equal(successful.writes[0].method, 'POST');
assert.equal(successful.writes[0].body.name, 'bot-feedback-gate');
assert.equal(successful.writes[0].body.head_sha, headSha, 'required check attaches to current PR head');
assert.equal(successful.writes[0].body.status, 'in_progress', 'pending is published before any evidence reads');
assert.equal(successful.writes[0].body.conclusion, undefined);
assert.equal(successful.writes[1].method, 'PATCH');
assert.equal(successful.writes[1].endpoint, 'repos/owner/repo/check-runs/99');
assert.equal(successful.writes[1].body.conclusion, 'success');
assert.equal(successful.events.find((event) => event.type === 'product').expectedHeadSha, headSha);
assert.equal(publishFixture({ initial: { ...pr, state: 'closed' } }).writes.length, 0);
for (const options of [{ productError: 'API failed' }, { threadError: 'Threads denied' }, { apiErrorAfterCreate: true },
  { product: { ...green, failed: true } }, { cleanupError: 'Check list denied' }]) {
  const result = publishFixture(options);
  assert.equal(result.writes[0].body.status, 'in_progress');
  assert.equal(result.writes.at(-1).body.conclusion, 'failure', 'unavailable or failed evidence cannot produce green');
}
const pending = publishFixture({ product: { ...green, pending: true } });
assert.equal(pending.writes.at(-1).body.status, 'in_progress');
assert.equal(pending.writes.at(-1).body.conclusion, undefined);
const restartedDuringThreads = publishFixture({ rerunDuringThreadRead: true });
assert.equal(restartedDuringThreads.writes.at(-1).body.status, 'in_progress');
assert.equal(restartedDuringThreads.writes.at(-1).body.conclusion, undefined,
  'product rerun started while review pages are read must not be hidden by an earlier green snapshot');
for (const final of [{ ...pr, head: { ...pr.head, sha: baseSha } },
  { ...pr, base: { ...pr.base, sha: headSha } }, { ...pr, state: 'closed' }]) {
  const raced = publishFixture({ final });
  assert.equal(raced.writes.at(-1).body.status, 'in_progress', 'head/base/state race must prevent success');
  assert.equal(raced.writes.at(-1).body.conclusion, undefined);
}
const unresolved = [{ isResolved: false, comments: { nodes: [{
  author: { login: 'reviewer', __typename: 'User' }, body: 'This branch can delete the retained evidence.',
  createdAt: '2026-10-12T00:00:00Z',
}] } }];
assert.equal(publishFixture({ threads: unresolved }).result.conclusion, 'failure');
for (const initial of [{ ...pr, title: 'chore: product change' },
  { ...pr, user: { login: 'dependabot[bot]', type: 'Bot' } }]) {
  assert.equal(publishFixture({ initial, threads: unresolved }).result.conclusion, 'failure',
    'existing substantive feedback is never exempted by title or author');
}
assert.equal(publishFixture({ threads: [{ ...unresolved[0], isResolved: true }] }).result.conclusion, 'success');

const owned = { id: 90, name: 'bot-feedback-gate', head_sha: headSha, status: 'in_progress',
  external_id: 'ar-local-required:42:' + headSha, app: { id: 15368, slug: 'github-actions' } };
const history = [owned, { ...owned, id: 91, status: 'queued' },
  { ...owned, id: 92, status: 'completed', conclusion: 'success' },
  { ...owned, id: 93, external_id: 'ar-local-required:43:' + headSha },
  { ...owned, id: 94, app: { id: 999, slug: 'other' } },
  { ...owned, id: 95, external_id: 'workflow-job' },
  { ...owned, id: 96, head_sha: baseSha },
  { ...owned, id: 99 }, { ...owned, id: 100 }];
const retired = publishFixture({ existingChecks: history });
assert.equal(retired.writes[0].method, 'POST', 'new pending check must exist before cancelling old evaluations');
assert.equal(retired.writes[0].body.status, 'in_progress');
assert.deepEqual(retired.writes.filter((event) => event.body.conclusion === 'cancelled').map((event) => event.endpoint),
  ['repos/owner/repo/check-runs/90', 'repos/owner/repo/check-runs/91'],
  'only older pending checks with exact PR/head/producer identity are retired');
assert.equal(retired.writes.at(-1).body.conclusion, 'success');
const closed = publishFixture({ initial: { ...pr, state: 'closed' }, existingChecks: history });
assert.equal(closed.writes.some((event) => event.method === 'POST'), false, 'closed PR never receives a new gate');
assert.ok(closed.writes.every((event) => event.body.conclusion === 'cancelled'));
assert.deepEqual(closed.writes.map((event) => event.endpoint), [90, 91, 99, 100].map((id) => 'repos/owner/repo/check-runs/' + id));
assert.equal(publishFixture({ existingChecks: [{ ...owned, id: -1 }] }).writes.at(-1).body.conclusion, 'failure');

const workflow = fs.readFileSync(new URL('../.github/workflows/pr-bot-feedback-check.yml', import.meta.url), 'utf8');
assert.match(workflow, /\n  pull_request_target:/);
assert.doesNotMatch(workflow, /\n  pull_request:|\n  pull_request_review(?:_comment)?:/);
assert.match(workflow, /types: \[requested, in_progress, completed\]/, 'reruns refresh the gate');
assert.match(workflow, /group: required-pr-gate-\$\{\{ matrix\.pr \}\}/);
assert.match(workflow, /cancel-in-progress: false/);
assert.doesNotMatch(workflow, /\n  bot-feedback-gate:/, 'Actions job cannot compete with the published required check');
assert.doesNotMatch(workflow, /BOT_GATE_TOKEN|secrets\./, 'no privileged PAT in PR-controlled execution');
assert.equal((workflow.match(/persist-credentials: false/g) || []).length, 2);
const refs = [...workflow.matchAll(/^\s+ref: (.+)$/gm)].map((match) => match[1]);
assert.equal(refs.length, 2);
for (const ref of refs) {
  assert.match(ref, /github\.event\.repository\.default_branch/);
  assert.doesNotMatch(ref, /pull_request\.(?:head|base)|workflow_run\.head/);
  if (ref.includes('github.sha')) {
    assert.match(ref, /github\.event_name == 'workflow_dispatch' && github\.sha \|\| github\.event\.repository\.default_branch/,
      'only an explicitly dispatched reviewed revision may supply reporter code');
  }
}
assert.doesNotMatch(workflow.split('\njobs:')[0], /checks: write/);
assert.match(workflow, /\n  evaluate-gates:[\s\S]*checks: write/);
assert.doesNotMatch(workflow, /download-artifact|refs\/pull\//);
const bridge = fs.readFileSync(new URL('../.github/workflows/pr-review-events.yml', import.meta.url), 'utf8');
assert.match(bridge, /pull_request_review:/);
assert.match(bridge, /pull_request_review_comment:/);
assert.doesNotMatch(bridge, /uses:\s*actions\/checkout|checks: write|GH_TOKEN|secrets\./);
console.log('Required-gate reporter regression tests passed');
