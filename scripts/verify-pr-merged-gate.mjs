#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { mergedDispatch, publishMergedGate } from './lib/pr-merged-gate.mjs';
import { mergedFeedbackViolations, readMergedFeedback } from './lib/pr-merged-feedback.mjs';
import { publishRequiredGate, retirePriorEventGate } from './lib/pr-required-gate.mjs';

const repository = 'owner/repo', head = 'a'.repeat(40), merge = 'b'.repeat(40), reporter = 'c'.repeat(40);
const pr = { number: 42, state: 'closed', merged: true, merged_at: '2026-11-02T01:00:00Z',
  merge_commit_sha: merge, changed_files: 0,
  head: { sha: head, ref: 'feature', repo: { full_name: repository } },
  base: { sha: merge, ref: 'main', repo: { full_name: repository } } };
const options = { repository, expectedHeadSha: head, expectedMergeSha: merge, reporterSha: reporter, runId: 10, runAttempt: 2 };
const event = { repository: { full_name: repository }, inputs: { pr_number: '42',
  merged_revalidation: 'true', expected_head: head, expected_merge: merge } };
assert.deepEqual(mergedDispatch(event, 'workflow_dispatch', repository, 42),
  { expectedHeadSha: head, expectedMergeSha: merge });
assert.equal(mergedDispatch(event, 'pull_request_target', repository, 42), null);
assert.equal(mergedDispatch({ inputs: { pr_number: '42' } }, 'workflow_dispatch', repository, 42), null);
for (const inputs of [{ expected_head: 'bad' }, { expected_merge: head.slice(1) }, { pr_number: '43' },
  { retired_head: head }, { merged_revalidation: 'false' }, { merged_revalidation: 'yes' }]) {
  assert.throws(() => mergedDispatch({ ...event, inputs: { ...event.inputs, ...inputs } }, 'workflow_dispatch', repository, 42));
}
assert.throws(() => mergedDispatch({ ...event, repository: { full_name: 'other/repo' } }, 'workflow_dispatch', repository, 42));

function fixture(overrides = {}) {
  const writes = [], calls = [];
  let prReads = 0;
  const api = (endpoint) => {
    calls.push(endpoint);
    if (overrides.api) { const value = overrides.api(endpoint, calls); if (value !== undefined) return value; }
    if (endpoint === `repos/${repository}`) return { full_name: repository, default_branch: 'main' };
    if (endpoint === `repos/${repository}/pulls/42`) {
      prReads += 1;
      return structuredClone(prReads > 1 && overrides.finalPr ? overrides.finalPr : overrides.pr || pr);
    }
    if (endpoint.endsWith('/branches/main')) return { name: 'main', commit: { sha: merge } };
    if (endpoint.includes('/compare/')) return { status: 'identical', base_commit: { sha: merge }, merge_base_commit: { sha: merge } };
    if (endpoint.includes('/files?')) return [];
    if (endpoint.includes('/check-runs?')) return { total_count: overrides.history?.length || 0, check_runs: overrides.history || [] };
    throw new Error(`Unexpected request ${endpoint}`);
  };
  const write = (endpoint, body, method = 'POST') => { writes.push({ endpoint, body, method }); return { id: 101 }; };
  const threadReader = overrides.threadReader || (() => overrides.threads || []);
  return { api, write, threadReader, writes, calls };
}
function publish(overrides = {}) {
  const f = fixture(overrides);
  const result = publishMergedGate(42, { ...options, ...f, ...(overrides.productReader ? { productReader: overrides.productReader } : {}) });
  return { ...f, result };
}
const green = publish();
assert.equal(green.result.conclusion, 'success');
assert.equal(green.writes.length, 2);
assert.equal(green.writes[0].body.status, 'in_progress');
assert.equal(green.writes[0].body.head_sha, head);
assert.equal(green.writes[0].body.external_id, `ar-local-merged-required:42:${head}:${merge}`);
assert.equal(green.writes[1].endpoint, `repos/${repository}/check-runs/101`);
assert.equal(green.result.reporterSha, reporter);
assert.equal(green.result.runAttempt, 2);
assert.match(green.result.summary, /producer_checks/);
for (const invalid of [{ state: 'open' }, { merged: false }, { merge_commit_sha: head },
  { head: { ...pr.head, sha: merge } }, { base: { ...pr.base, ref: 'other' } },
  { base: { ...pr.base, repo: { full_name: 'other/repo' } } }]) {
  const f = fixture({ pr: { ...pr, ...invalid } });
  assert.throws(() => publishMergedGate(42, { ...options, ...f }));
  assert.equal(f.writes.length, 0, 'invalid target creates no check');
}
for (const response of [{ status: 'behind', base_commit: { sha: merge }, merge_base_commit: { sha: merge } },
  { status: 'ahead', base_commit: { sha: merge }, merge_base_commit: { sha: head } }, {}]) {
  assert.throws(() => publish({ api: (endpoint) => endpoint.includes('/compare/') ? response : undefined }));
}
assert.throws(() => publish({ api: (endpoint) => { if (endpoint.includes('/compare/')) throw new Error('unavailable'); } }));
assert.equal(publish({ finalPr: { ...pr, merged_at: '2026-11-02T02:00:00Z' } }).result.conclusion, 'failure');
assert.equal(publish({ finalPr: { ...pr, head: { ...pr.head, ref: 'changed' } } }).result.conclusion, 'failure');
assert.equal(publish({ api: (endpoint, calls) => endpoint.endsWith('/branches/main') &&
  calls.filter((value) => value.endsWith('/branches/main')).length > 1 ? { name: 'main', commit: { sha: head } } : undefined }).result.conclusion, 'failure');
for (const product of [{ ok: false, error: 'API unavailable' }, { ok: true, failed: true, detail: 'failed' },
  { ok: true, pending: true, detail: 'newer attempt running' }]) {
  const result = publish({ productReader: (number, supplied) => {
    assert.equal(number, 42); assert.equal(supplied.expectedHeadSha, head); assert.equal(supplied.expectedMergeSha, merge);
    return product;
  } }).result;
  assert.notEqual(result.conclusion, 'success');
}
const comment = { id: 'C1', author: { login: 'reviewer', __typename: 'User' }, body: 'Handle this failure.', createdAt: pr.merged_at };
assert.equal(publish({ threads: [{ isResolved: false, comments: { nodes: [comment] } }] }).result.conclusion, 'failure');

const quotaComment = { ...comment, id: 'quota', author: { login: 'github-actions[bot]', __typename: 'Bot' }, body: 'API quota exceeded' };
const unresolved = (nodes) => ({ id: 'unknown-author-thread', isResolved: false, comments: { nodes } });
for (const nodes of [[], ...[null, undefined, {}, { login: '' }, { login: ' ' }].map((author) => [{ ...comment, author }]),
  [{ ...comment, author: null }, quotaComment], [quotaComment, { ...comment, author: null }]]) {
  assert.equal(publish({ threads: [unresolved(nodes)] }).result.conclusion, 'failure',
    'unknown/empty unresolved feedback cannot be filtered or reclassified using a later visible author');
}
assert.equal(publish({ threads: [{ ...unresolved([{ ...comment, author: null }]), isResolved: true }] }).result.conclusion,
  'success', 'resolved deleted-author history remains valid');
assert.equal(publish({ threads: [unresolved([quotaComment])] }).result.conclusion, 'success',
  'known-author bot-noise policy is unchanged');

// The complete second feedback snapshot must be the last evidence read before PATCH.
const resolved = { id: 'T-stable', isResolved: true, comments: { nodes: [comment] } };
const observed = [];
const stableFixture = fixture();
const stable = publishMergedGate(42, { ...options, ...stableFixture,
  api: (endpoint) => { observed.push('api'); return stableFixture.api(endpoint); },
  threadReader: () => { observed.push('feedback'); return structuredClone([resolved]); },
  write: (...args) => { observed.push('write'); return stableFixture.write(...args); } });
assert.equal(stable.conclusion, 'success');
assert.equal(observed.filter((value) => value === 'feedback').length, 2);
assert.deepEqual(observed.slice(-2), ['feedback', 'write']);
for (const final of [[resolved, unresolved([comment])], [{ ...resolved, isResolved: false }], [],
  [{ ...resolved, comments: { nodes: [{ ...comment, body: 'Edited review' }] } }],
  [{ ...resolved, isResolved: undefined }], null]) {
  let reads = 0;
  const changed = publish({ threadReader: () => ++reads === 1 ? structuredClone([resolved]) : final });
  assert.equal(changed.result.conclusion, 'failure', 'added/reopened/deleted/edited/malformed feedback cannot reuse stale success');
  assert.equal(changed.writes.at(-1).body.conclusion, 'failure');
}
let feedbackReads = 0;
assert.equal(publish({ threadReader: () => {
  if (++feedbackReads === 1) return [resolved];
  throw new Error('Second complete feedback read unavailable');
} }).result.conclusion, 'failure');

// Automatic closure/prior-head cleanup cannot cancel explicit merged ownership.
const oldCancelled = { id: 99, name: 'bot-feedback-gate', head_sha: head, status: 'completed', conclusion: 'cancelled',
  app: { id: 15368, slug: 'github-actions' }, external_id: `ar-local-required:42:${head}` };
const explicitPending = { ...oldCancelled, id: 101, status: 'in_progress', conclusion: null,
  external_id: green.writes[0].body.external_id };
const cleanup = fixture({ history: [oldCancelled, explicitPending] });
assert.equal(publishRequiredGate(42, { repository, ...cleanup }).skipped, true);
retirePriorEventGate({ ...event, inputs: { pr_number: '42', retired_head: head } }, 'workflow_dispatch', { repository, ...cleanup });
assert.equal(cleanup.writes.length, 0, 'closed events preserve old terminal and explicit pending checks');
const retained = publish({ history: [oldCancelled] });
assert.equal(retained.result.conclusion, 'success');
assert.equal(retained.writes.some((row) => row.endpoint.endsWith('/99')), false);

// Complete thread/comment pagination is bound to the merged identity on every page.
const identity = { headSha: head, mergeSha: merge, mergedAt: pr.merged_at, baseRef: 'main' };
const connection = (nodes, totalCount = nodes.length, hasNextPage = false, endCursor = null) =>
  ({ nodes, totalCount, pageInfo: { hasNextPage, endCursor } });
const feedbackPage = (threads) => ({ repository: { nameWithOwner: repository, pullRequest: {
  number: 42, state: 'MERGED', merged: true, mergedAt: pr.merged_at, headRefOid: head,
  baseRefName: 'main', mergeCommit: { oid: merge }, reviewThreads: threads } } });
const thread = (id) => ({ id, isResolved: true, comments: connection([comment]) });
assert.equal(readMergedFeedback(repository, 42, identity, { query: () => feedbackPage(connection([thread('T1')])) }).length, 1);
const deletedAuthor = { ...thread('T-deleted'), isResolved: false, comments: connection([{ ...comment, author: null }]) };
const deletedSnapshot = readMergedFeedback(repository, 42, identity, { query: () => feedbackPage(connection([deletedAuthor])) });
assert.equal(mergedFeedbackViolations(deletedSnapshot).length, 1, 'complete GraphQL null-author snapshot blocks publication');
const manyThreads = Array.from({ length: 101 }, (_, i) => thread(`T${i}`));
assert.equal(readMergedFeedback(repository, 42, identity, { query: (_, vars) => feedbackPage(vars.after ?
  connection(manyThreads.slice(100), 101) : connection(manyThreads.slice(0, 100), 101, true, 'next')) }).length, 101);
const manyComments = Array.from({ length: 101 }, (_, i) => ({ ...comment, id: `C${i}` }));
const commentPages = readMergedFeedback(repository, 42, identity, { query: (_, vars) => vars.id ?
  { node: { id: 'T1', comments: connection(manyComments.slice(100), 101) } } :
  feedbackPage(connection([{ ...thread('T1'), comments: connection(manyComments.slice(0, 100), 101, true, 'comments-next') }])) });
assert.equal(commentPages[0].comments.nodes.length, 101);
for (const bad of [{ nodes: [] }, connection([], 1), connection([thread('T1'), thread('T1')]),
  connection([thread('T1')], 2, true, null), connection([{ ...thread('T1'), isResolved: undefined }]),
  connection([{ ...thread('T1'), comments: connection([], 1) }])]) {
  assert.throws(() => readMergedFeedback(repository, 42, identity, { query: () => feedbackPage(bad) }));
}
assert.throws(() => readMergedFeedback(repository, 42, identity, { query: () => {
  const result = feedbackPage(connection([])); result.repository.pullRequest.headRefOid = merge; return result;
} }));
for (const closed of [{ state: 'CLOSED', merged: false }, { state: 'CLOSED', merged: true }, { state: 'OPEN', merged: false }]) {
  assert.throws(() => readMergedFeedback(repository, 42, identity, { query: () => {
    const result = feedbackPage(connection([])); Object.assign(result.repository.pullRequest, closed); return result;
  } }), 'GraphQL MERGED is distinct from REST closed');
}

const yaml = fs.readFileSync(new URL('../.github/workflows/pr-bot-feedback-check.yml', import.meta.url), 'utf8');
assert.match(yaml, /merged_revalidation:[\s\S]*?type: boolean/);
assert.match(yaml, /format\('required-merged-pr-gate-\{0\}', matrix.pr\) \|\| format\('required-pr-gate-\{0\}', matrix.pr\)/,
  'old automatic jobs cannot replace pending merged recovery; each writer mode remains serialized per PR');
assert.match(yaml, /github.event_name == 'workflow_dispatch' && github.sha \|\| github.event.repository.default_branch/);
assert.doesNotMatch(yaml, /administration:|contents: write|pull-requests: write|download-artifact|pull_request.head.sha/);
const source = fs.readFileSync(new URL('lib/pr-merged-gate.mjs', import.meta.url), 'utf8');
assert.doesNotMatch(source, /mergedAudit:\s*true|retirePendingEvaluations|\/protection/);
console.log('verify-pr-merged-gate: pass (explicit dispatch, identity/ancestry, unchanged CI policy, feedback completeness, races and ownership)');
