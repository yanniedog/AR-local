import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { writeBotWaitStateFile, readBotWaitStateFile, botWaitStatePath } from './lib/bot-wait-state.mjs';
import { parseRequiredKeys, resolveRequiredKeys } from './lib/bot-wait-config.mjs';
import { requiredCiWaitResult, applyReviewerPolicy, reviewWaitIgnoredChecks } from './lib/bot-wait-ci.mjs';
import { BOT_GATE_CHECK_NAMES, gateGithubBotChecks, gateWaitForBots, fetchRequiredCi } from './lib/pr-gates-lib.mjs';
import { readMergeCi } from './lib/pr-ci-readiness.mjs';
import { checkRequiredBotsOnPr } from './lib/bot-wait-presence.mjs';
import { gateExemptReasonFromPrMeta } from './lib/pr-gate-exempt.mjs';
import { evaluate, reviewerExemption } from '../wait_for_bots.mjs';
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
  // Atomic persistence/crash handling lives in verify-pr-wait-state.mjs.
  writeBotWaitStateFile(123, persisted, stateRoot);
  assert.deepEqual(readBotWaitStateFile(123, stateRoot).requiredKeys, ['sourcery']);
  assert.deepEqual(fs.readdirSync(path.dirname(botWaitStatePath(123, stateRoot))).sort(), ['123.json', '123.json.writer-lock']);
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

const reviewNow = Date.now();
const reviewerWait = (ageSeconds, anchorAgeSeconds = 600) => evaluate({ prNumber: 123,
  anchorIso: new Date(reviewNow - anchorAgeSeconds * 1000).toISOString(), state: {}, repo: { owner: 'owner', name: 'repo' },
  requiredKeys: ['sourcery'],
  fetchActivity: () => ({ events: [{ login: 'sourcery-ai', at: new Date(reviewNow - ageSeconds * 1000).toISOString() }] }),
  readChecks: () => ({ ok: true, pending: false, failed: false }),
});
assert.equal(reviewerWait(0).status, 'waiting', 'one-shot opt-in retains the quiet window');
assert.equal(reviewerWait(120).status, 'ready', 'a later one-shot observation can satisfy quiet');
assert.equal(reviewerWait(0, 86400).status, 'waiting', 'an aged anchor cannot bypass recent reviewer activity');
assert.equal(reviewerWait(120, 86400).status, 'ready', 'an aged anchor is ready once reviewer activity is quiet');

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
    external_id: `ar-local-required:123:${head}`,
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
    assert.deepEqual(names, ['bot-feedback-gate']);
    return { found: { 'bot-feedback-gate': { bucket: 'pass', state: 'SUCCESS' } } };
  },
}).pass, true, 'opt-in must not require a diagnostic check attached to the default branch');

const botPr = { title: 'chore: automated report', author: { login: 'github-actions[bot]', type: 'Bot' } };
const botExemption = () => gateExemptReasonFromPrMeta(botPr);
assert.equal(reviewerExemption(123, [], botExemption), 'bot-authored');
assert.equal(reviewerExemption(123, ['sourcery'], botExemption), null, 'explicit opt-in overrides the bot PR exemption');
for (const [events, checks, expectedExit] of [
  [[], { pending: false, failed: false }, 2],
  [[{ login: 'sourcery-ai', at: new Date(reviewNow - 120_000).toISOString() }], { pending: false, failed: true }, 1],
  [[{ login: 'sourcery-ai', at: new Date(reviewNow - 120_000).toISOString() }], { pending: false, failed: false }, 0],
]) {
  let evaluations = 0;
  const result = gateWaitForBots(123, {
    botPresencePass: true, botPresenceCompletedAt: new Date(reviewNow).toISOString(),
    runScript: (script, args) => {
      assert.equal(script, 'wait_for_bots.mjs');
      assert.deepEqual(args, ['--pr', '123']);
      evaluations += 1;
      const current = evaluate({ prNumber: 123, anchorIso: new Date(reviewNow - 600_000).toISOString(),
        state: {}, repo: { owner: 'owner', name: 'repo' }, requiredKeys: ['sourcery'],
        fetchActivity: () => ({ events }), readChecks: () => ({ ok: true, ...checks }),
      });
      return { exitCode: current.status === 'ready' ? 0 : current.status === 'waiting' ? 2 : 1,
        stdout: current.message, stderr: '' };
    },
  });
  assert.equal(evaluations, 1, 'old green presence checks never bypass a fresh local evaluation');
  assert.equal(result.exitCode, expectedExit);
  assert.equal(result.pass, expectedExit === 0);
}

const presenceWorkflow = fs.readFileSync(new URL('../.github/workflows/pr-bot-presence-gate.yml', import.meta.url), 'utf8');
assert.match(presenceWorkflow, /if: github\.ref == format\('refs\/heads\/\{0\}', github\.event\.repository\.default_branch\)/);
assert.match(presenceWorkflow, /ref: \$\{\{ github\.event\.repository\.default_branch \}\}/);
assert.match(presenceWorkflow, /persist-credentials: false/);
assert.match(presenceWorkflow, /GH_TOKEN: \$\{\{ github\.token \}\}/);
assert.doesNotMatch(presenceWorkflow, /secrets\.|:\s*write\b|pull_request\s*:|pull_request_target\s*:/);
console.log('Local reviewer opt-in and trusted read-only diagnostic regressions passed');
