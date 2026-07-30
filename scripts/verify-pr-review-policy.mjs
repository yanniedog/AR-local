#!/usr/bin/env node
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import {
  DEFAULT_REQUIRED_KEYS,
  parseRequiredKeys,
  resolveRequiredKeys,
} from './lib/bot-wait-config.mjs';
import {
  BOT_GATE_CHECK_NAMES,
  gateGithubBotChecksResult,
  selectNewestCheck,
} from './lib/pr-gates-lib.mjs';
import { parseRequiredChecksResult } from './lib/required-check-settlement.mjs';

assert.deepEqual(DEFAULT_REQUIRED_KEYS, []);
assert.deepEqual(parseRequiredKeys('off'), []);
assert.deepEqual(parseRequiredKeys('none'), []);
assert.deepEqual(parseRequiredKeys('disabled'), []);
assert.deepEqual(parseRequiredKeys('gemini,codex'), ['gemini', 'codex']);
assert.deepEqual(
  resolveRequiredKeys([], 'gemini'),
  [],
  'an explicit advisory policy must override stale environment requirements',
);
assert.deepEqual(BOT_GATE_CHECK_NAMES, ['bot-feedback-gate']);

const packageJson = JSON.parse(readFileSync('package.json', 'utf8'));
assert.equal(
  packageJson.scripts?.['pr:arm-and-park'],
  'node scripts/pr-arm-and-park.mjs',
);
assert.match(packageJson.scripts?.['pr:automation:verify'] || '', /verify-pr-arm-and-park/);

const missingFeedbackGate = gateGithubBotChecksResult({ found: {}, skipped: true });
assert.equal(
  missingFeedbackGate.pass,
  false,
  'an unreported required feedback check must wait rather than pass',
);
assert.equal(missingFeedbackGate.pending, true);

const olderPass = {
  name: 'bot-feedback-gate',
  bucket: 'pass',
  state: 'SUCCESS',
  startedAt: '2026-07-30T01:00:00Z',
};
const newerPending = {
  name: 'bot-feedback-gate',
  bucket: 'pending',
  state: 'IN_PROGRESS',
  startedAt: '2026-07-30T02:00:00Z',
};
assert.equal(
  selectNewestCheck(olderPass, newerPending),
  newerPending,
  'a stale pass must not hide a newer pending gate run',
);

const ignoredPendingOnly = parseRequiredChecksResult({
  status: 8,
  stderr: '',
  stdout: JSON.stringify([
    { name: 'bot-feedback-gate', bucket: 'pending', state: 'IN_PROGRESS' },
  ]),
});
assert.equal(
  ignoredPendingOnly.pending,
  false,
  'exit 8 must be parsed before ignored required checks are classified',
);
const productPending = parseRequiredChecksResult({
  status: 8,
  stderr: '',
  stdout: JSON.stringify([
    { name: 'bot-feedback-gate', bucket: 'pending', state: 'IN_PROGRESS' },
    { name: 'app-ci', bucket: 'pending', state: 'QUEUED' },
  ]),
});
assert.equal(productPending.pending, true);

const branchProtection = readFileSync('scripts/apply-branch-protection.mjs', 'utf8');
const requiredBlock =
  branchProtection.match(/const REQUIRED_CHECKS = \[[\s\S]*?\];/)?.[0] || '';
assert.match(requiredBlock, /bot-feedback-gate/);
assert.doesNotMatch(
  requiredBlock,
  /bot-presence-gate|local-llm-review|qwen/,
);
for (const retired of [
  'bot-presence-gate',
  'local-llm-review',
  'qwen-code-review',
]) {
  assert.match(branchProtection, new RegExp(retired));
}

const ruleset = JSON.parse(
  readFileSync('.github/rulesets/main-bot-gates.json', 'utf8'),
);
const contexts =
  ruleset.rules
    ?.find((rule) => rule.type === 'required_status_checks')
    ?.parameters?.required_status_checks?.map((check) => check.context) || [];
assert.deepEqual(contexts, ['bot-feedback-gate']);

const presenceWorkflow = readFileSync(
  '.github/workflows/pr-bot-presence-gate.yml',
  'utf8',
);
assert.match(presenceWorkflow, /AR_BOT_WAIT_REQUIRED:\s*off/);

const feedbackWorkflow = readFileSync(
  '.github/workflows/pr-bot-feedback-check.yml',
  'utf8',
);
assert.match(feedbackWorkflow, /npm run pr:automation:verify/);
assert.match(
  feedbackWorkflow,
  /group:\s*bot-feedback-gate-\$\{\{\s*github\.event\.pull_request\.number\s*\|\|\s*inputs\.pr_number\s*\|\|\s*github\.run_id\s*\}\}/,
);
assert.match(feedbackWorkflow, /cancel-in-progress:\s*false/);
assert.doesNotMatch(feedbackWorkflow, /queue:\s*max/);
assert.doesNotMatch(feedbackWorkflow, /pull_request\.head\.sha|github\.sha/);
assert.match(feedbackWorkflow, /elif \[ "\$code" -eq 3 \]/);
assert.match(feedbackWorkflow, /Feedback gate execution failed permanently/);

const feedbackCheck = readFileSync('scripts/pr-bot-feedback-check.mjs', 'utf8');
assert.match(
  feedbackCheck,
  /process\.exit\(result\.violations\.length \? 3 : 0\)/,
  'open feedback must have a distinct retryable exit from hard execution failures',
);

const appCi = readFileSync('.github/workflows/app-ci.yml', 'utf8');
assert.match(
  appCi,
  /pull_request:\s*\r?\n\s+paths:/,
  'AR-local product CI remains path-filtered and is not invented as a universal required check',
);

console.log('PASS verify-pr-review-policy: reviewers advisory; feedback gate required');
