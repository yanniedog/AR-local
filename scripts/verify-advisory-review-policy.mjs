import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { writeBotWaitStateFile, readBotWaitStateFile, botWaitStatePath } from './lib/bot-wait-state.mjs';
import { parseRequiredKeys, resolveRequiredKeys } from './lib/bot-wait-config.mjs';
import { requiredCiWaitResult, applyReviewerPolicy } from './lib/bot-wait-ci.mjs';
import { BOT_GATE_CHECK_NAMES } from './lib/pr-gates-lib.mjs';
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
