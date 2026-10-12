import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { writeBotWaitStateFile, readBotWaitStateFile, botWaitStatePath } from './lib/bot-wait-state.mjs';
import { parseRequiredKeys, resolveRequiredKeys } from './lib/bot-wait-config.mjs';
import { requiredCiWaitResult, applyReviewerPolicy, reviewWaitIgnoredChecks } from './lib/bot-wait-ci.mjs';
import { BOT_GATE_CHECK_NAMES, gateGithubBotChecks, fetchRequiredCi } from './lib/pr-gates-lib.mjs';
import { readMergeCi } from './lib/pr-ci-readiness.mjs';
import { checkRequiredBotsOnPr } from './lib/bot-wait-presence.mjs';
assert.deepEqual(parseRequiredKeys(''), []);
for (const mode of ['off', 'none', 'disabled', 'OFF']) assert.deepEqual(parseRequiredKeys(mode), []);
assert.deepEqual(resolveRequiredKeys([], 'gemini,codex'), []);
assert.deepEqual(resolveRequiredKeys(null, 'gemini,codex'), ['gemini', 'codex']);
assert.deepEqual(resolveRequiredKeys(['sourcery'], 'off'), ['sourcery']);
assert.deepEqual(BOT_GATE_CHECK_NAMES, ['bot-feedback-gate']);
// Saved presence keys from old sessions must not resurrect a vendor requirement.
const stateRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'advisory-policy-'));
const savedStateDir = process.env.AR_BOT_WAIT_STATE_DIR;
const savedArPolicy = process.env.AR_BOT_WAIT_REQUIRED;
const savedPolicy = process.env.BOT_WAIT_REQUIRED;
try {
  process.env.AR_BOT_WAIT_STATE_DIR = path.join(stateRoot, 'state');
  delete process.env.AR_BOT_WAIT_REQUIRED;
  delete process.env.BOT_WAIT_REQUIRED;
  writeBotWaitStateFile(123, { requiredKeys: ['gemini', 'codex'], anchor: '2026-10-11T00:00:00Z' }, stateRoot);
  const persisted = readBotWaitStateFile(123, stateRoot);
  assert.deepEqual(persisted.requiredKeys, ['gemini', 'codex']);
  assert.deepEqual(applyReviewerPolicy(persisted, resolveRequiredKeys()), []);
  assert.deepEqual(persisted.requiredKeys, []);
  assert.equal(persisted.readyAt, null);
  assert.deepEqual(applyReviewerPolicy(persisted, ['sourcery']), ['sourcery']);
  assert.deepEqual(persisted.requiredKeys, ['sourcery']);
  const accepted = fs.readFileSync(botWaitStatePath(123, stateRoot), 'utf8');
  const originalRename = fs.renameSync;
  try {
    fs.renameSync = () => { throw new Error('replacement interrupted'); };
    assert.throws(() => writeBotWaitStateFile(123, { anchor: 'new' }, stateRoot), /replacement interrupted/);
  } finally {
    fs.renameSync = originalRename;
  }
  assert.equal(fs.readFileSync(botWaitStatePath(123, stateRoot), 'utf8'), accepted);
  assert.deepEqual(fs.readdirSync(path.dirname(botWaitStatePath(123, stateRoot))), ['123.json']);
  if (process.platform !== 'win32') {
    const originalFsync = fs.fsyncSync;
    let directorySynced = false;
    try {
      fs.fsyncSync = (descriptor) => {
        directorySynced ||= fs.fstatSync(descriptor).isDirectory();
        return originalFsync(descriptor);
      };
      writeBotWaitStateFile(123, persisted, stateRoot);
    } finally { fs.fsyncSync = originalFsync; }
    assert.equal(directorySynced, true, 'accepted rename persists its directory');
  }
  assert.equal(gateGithubBotChecks(123, {
    fetchChecks: (_pr, names) => {
      assert.deepEqual(names, ['bot-feedback-gate']);
      return { found: { 'bot-feedback-gate': { bucket: 'pass', state: 'SUCCESS' } } };
    },
  }).pass, true, 'ordinary invocation uses the default resolver');
  // Return before attempting GitHub access even with stale saved keys.
  assert.equal(checkRequiredBotsOnPr('invalid', 'invalid', 123, { repoRoot: stateRoot }).ok, true);
  assert.equal(checkRequiredBotsOnPr('invalid', 'invalid', 123, { requiredKeys: [], repoRoot: stateRoot }).ok, true);
} finally {
  for (const [key, value] of [['AR_BOT_WAIT_STATE_DIR', savedStateDir], ['AR_BOT_WAIT_REQUIRED', savedArPolicy], ['BOT_WAIT_REQUIRED', savedPolicy]]) {
    if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
  fs.rmSync(stateRoot, { recursive: true, force: true });
}
assert.equal(requiredCiWaitResult({ ok: true, pending: false, failed: false }).status, 'ready');
assert.equal(requiredCiWaitResult({ ok: true, pending: true, failed: false }).status, 'waiting');
assert.equal(requiredCiWaitResult({ ok: true, pending: true, failed: true, failedNames: ['product-ci'] }).status, 'error');
assert.equal(requiredCiWaitResult({ ok: false, error: 'auth failed' }).status, 'error');
console.log('Advisory review policy regression tests passed');

assert.ok(reviewWaitIgnoredChecks().has('bot-feedback-gate'));
assert.ok(reviewWaitIgnoredChecks('UNIT-CHECK').has('unit-check'));

const reported = [
  { name: 'bot-feedback-gate', bucket: 'fail', state: 'FAILURE' },
  { name: 'product-ci', bucket: 'pass', state: 'SUCCESS' },
];
const head = 'a'.repeat(40), base = 'b'.repeat(40);
const ciOptions = {
  run: () => ({ status: 1, stdout: JSON.stringify(reported) }),
  readProduct: () => ({ ok: true, repository: 'owner/repo', headSha: head, baseSha: base, baseRef: 'main',
    pending: false, failed: false, pendingNames: [], failedNames: [], checks: [] }),
  read: () => ({ number: 123, state: 'OPEN', headRefOid: head, baseRefOid: base, baseRefName: 'main' }),
  api: () => ({ check_runs: [{ id: 1, name: 'bot-feedback-gate', head_sha: head,
    app: { id: 15368, slug: 'github-actions' }, status: 'completed', conclusion: 'failure' }], total_count: 1 }),
};
assert.equal(fetchRequiredCi, readMergeCi, 'retain exact-head product CI from the merge policy');
assert.equal(fetchRequiredCi(123, ciOptions).failed, true);
assert.equal(fetchRequiredCi(123, { ...ciOptions, ignoredNames: ['BOT-FEEDBACK-GATE'] }).failed, false);
assert.equal(requiredCiWaitResult(fetchRequiredCi(123, { ...ciOptions, ignoredNames: [...reviewWaitIgnoredChecks()] })).status, 'ready');
assert.match(fetchRequiredCi(123, { ...ciOptions, run: () => ({ status: 0, stdout: '[null]' }) }).error, /observation has no name/);
assert.equal(gateGithubBotChecks(123, {
  requiredKeys: ['sourcery'],
  fetchChecks: (_pr, names) => {
    assert.deepEqual(names, ['bot-presence-gate', 'bot-feedback-gate']);
    return { found: { 'bot-feedback-gate': { bucket: 'pass', state: 'SUCCESS' } } };
  },
}).pass, false);
