import assert from 'node:assert/strict';
import { applyStatusCheckPolicy, buildStatusCheckPatch } from './lib/branch-protection-policy.mjs';

const actionsApp = { id: 15368, slug: 'github-actions' };
const existing = {
  strict: true,
  contexts: ['bot-presence-gate', 'bot-feedback-gate', 'security-review', 'legacy-status'],
  checks: [
    { context: 'bot-presence-gate', app_id: 15368 },
    { context: 'bot-feedback-gate', app_id: 15368 },
    { context: 'security-review', app_id: 9001 },
    { context: 'legacy-status', app_id: null },
  ],
};
const original = structuredClone(existing);
const expected = {
  strict: true,
  checks: [
    { context: 'bot-feedback-gate', app_id: 15368 },
    { context: 'security-review', app_id: 9001 },
    { context: 'legacy-status', app_id: -1 },
  ],
};
assert.deepEqual(buildStatusCheckPatch(existing, actionsApp.id), expected);
assert.deepEqual(existing, original, 'planning must not mutate the input');
assert.deepEqual(Object.keys(expected).sort(), ['checks', 'strict']);
assert.equal(buildStatusCheckPatch({ ...existing, strict: false }, actionsApp.id).strict, true);
assert.deepEqual(buildStatusCheckPatch({ strict: true, contexts: [], checks: [] }, actionsApp.id), {
  strict: true, checks: [{ context: 'bot-feedback-gate', app_id: 15368 }],
});
for (const invalid of [null, {}, { ...existing, checks: undefined }, { ...existing, contexts: ['unknown'] }]) {
  assert.throws(() => buildStatusCheckPatch(invalid, actionsApp.id));
}
assert.throws(() => buildStatusCheckPatch(existing, 0), /identify/);
assert.throws(() => buildStatusCheckPatch({ ...existing, checks: [
  { context: 'bot-feedback-gate', app_id: 9001 },
], contexts: ['bot-feedback-gate'] }, actionsApp.id), /different app/);

function harness({ initial = existing, readback, defaultBranch = 'trunk', failRead = false } = {}) {
  const calls = [];
  let current = structuredClone(initial);
  const read = (args) => {
    calls.push({ kind: 'read', args });
    if (args[0] === 'repo') return { nameWithOwner: 'owner/repo', defaultBranchRef: { name: defaultBranch } };
    if (args[1] === 'apps/github-actions') return actionsApp;
    if (failRead) throw new Error('HTTP 403');
    return current;
  };
  const write = (args, payload) => {
    calls.push({ kind: 'write', args, payload });
    current = readback ?? { ...payload, contexts: payload.checks.map((check) => check.context) };
  };
  return { calls, read, write };
}
const h = harness();
const applied = applyStatusCheckPolicy({}, h);
assert.equal(applied.branch, 'trunk');
assert.equal(applied.changed, true);
assert.deepEqual(h.calls.filter((call) => call.kind === 'write'), [{
  kind: 'write',
  args: ['api', '--method', 'PATCH', 'repos/owner/repo/branches/trunk/protection/required_status_checks', '--input', '-'],
  payload: expected,
}], 'never PUT all protection or change reviews, restrictions, admin enforcement, or conversation settings');
const dry = harness();
applyStatusCheckPolicy({ dryRun: true, branch: 'release/stable' }, dry);
assert.equal(dry.calls.some((call) => call.kind === 'write'), false);
assert.ok(dry.calls.some((call) => call.args[1]?.includes('branches/release%2Fstable/')));
const unchanged = harness({ initial: { ...expected, contexts: expected.checks.map((check) => check.context) } });
assert.equal(applyStatusCheckPolicy({}, unchanged).changed, false);
assert.equal(unchanged.calls.some((call) => call.kind === 'write'), false);
const denied = harness({ failRead: true });
assert.throws(() => applyStatusCheckPolicy({}, denied), /403/);
assert.equal(denied.calls.some((call) => call.kind === 'write'), false);
assert.throws(() => applyStatusCheckPolicy({}, harness({ readback: existing })), /readback/);
console.log('Branch-protection policy regression tests passed');
