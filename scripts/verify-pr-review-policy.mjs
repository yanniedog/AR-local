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
} from './lib/pr-gates-lib.mjs';
import {
  combineRequiredCheckState,
  DEFAULT_REQUIRED_CHECKS,
  evaluateRequiredCheckState,
  mergePolicyAndPrRequiredChecks,
} from './lib/required-ci-checks.mjs';

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
assert.deepEqual(DEFAULT_REQUIRED_CHECKS, ['bot-feedback-gate']);

const packageJson = JSON.parse(readFileSync('package.json', 'utf8'));
assert.equal(
  packageJson.scripts?.['pr:arm-and-park'],
  'node scripts/pr-arm-and-park.mjs',
);
assert.match(packageJson.scripts?.['pr:automation:verify'] || '', /verify-pr-arm-and-park/);

const missingFeedbackGate = gateGithubBotChecksResult({
  ok: true,
  failedNames: [],
  pendingNames: ['bot-feedback-gate'],
  missingNames: ['bot-feedback-gate'],
});
assert.equal(
  missingFeedbackGate.pass,
  false,
  'an unreported required feedback check must wait rather than pass',
);
assert.equal(missingFeedbackGate.pending, true);

assert.deepEqual(
  combineRequiredCheckState({
    protectionOk: true,
    protection: {
      required_status_checks: {
        checks: [{ context: 'bot-feedback-gate' }],
      },
    },
    rulesOk: true,
    rules: [{
      type: 'required_status_checks',
      parameters: {
        required_status_checks: [{ context: 'bot-feedback-gate' }],
      },
    }],
  }),
  {
    values: ['bot-feedback-gate'],
    requirements: [{ context: 'bot-feedback-gate', appId: null }],
    source: 'live branch protection + rules',
  },
);
assert.deepEqual(
  combineRequiredCheckState({
    protectionOk: false,
    rulesOk: false,
  }),
  {
    values: ['bot-feedback-gate'],
    requirements: [{ context: 'bot-feedback-gate', appId: null }],
    source: 'configured policy fallback; live policy APIs unavailable',
  },
);
assert.deepEqual(
  combineRequiredCheckState({
    protectionOk: false,
    rulesOk: true,
    rules: [],
    fallbackRequiredNames: ['bot-feedback-gate'],
  }),
  {
    values: ['bot-feedback-gate'],
    requirements: [{ context: 'bot-feedback-gate', appId: null }],
    source: 'partial live rules + configured policy fallback',
  },
);
assert.equal(
  evaluateRequiredCheckState({
    requiredChecks: [{ context: 'bot-feedback-gate', appId: 100 }],
    headCheckRuns: [{
      id: 20,
      name: 'bot-feedback-gate',
      app: { id: 200 },
      conclusion: 'success',
      completed_at: '2026-07-30T01:00:00Z',
    }],
  }).pending,
  true,
  'a same-name check from the wrong GitHub App must not satisfy an app-bound policy',
);
assert.equal(
  evaluateRequiredCheckState({
    requiredChecks: [{ context: 'bot-feedback-gate', appId: 100 }],
    headCheckRuns: [{
      id: 21,
      name: 'bot-feedback-gate',
      app: { id: 100 },
      conclusion: 'success',
      completed_at: '2026-07-30T01:00:00Z',
    }],
  }).pending,
  false,
);
assert.deepEqual(
  mergePolicyAndPrRequiredChecks(
    {
      values: ['bot-feedback-gate'],
      requirements: [{ context: 'bot-feedback-gate', appId: 100 }],
    },
    [
      { name: 'bot-feedback-gate', bucket: 'pass' },
      { name: 'path-filtered-product-ci', bucket: 'pass' },
    ],
  ),
  [
    { context: 'bot-feedback-gate', appId: 100 },
    { context: 'path-filtered-product-ci', appId: null },
  ],
  'required names reported by gh pr checks must remain in exact-head evaluation',
);
const missingRequired = evaluateRequiredCheckState({
  requiredNames: ['bot-feedback-gate'],
  prChecks: [],
  headCheckRuns: [],
});
assert.deepEqual(missingRequired.missingNames, ['bot-feedback-gate']);
assert.equal(missingRequired.pending, true);
const newerPending = evaluateRequiredCheckState({
  requiredNames: ['bot-feedback-gate'],
  prChecks: [{
    name: 'bot-feedback-gate',
    bucket: 'pass',
    state: 'SUCCESS',
    startedAt: '2026-07-30T01:00:00Z',
  }],
  headCheckRuns: [{
    id: 11,
    name: 'bot-feedback-gate',
    status: 'in_progress',
    started_at: '2026-07-30T02:00:00Z',
  }],
});
assert.equal(newerPending.pending, true, 'a stale pass must not hide a newer pending run');
const newerPass = evaluateRequiredCheckState({
  requiredNames: ['bot-feedback-gate'],
  headCheckRuns: [{
    id: 12,
    name: 'bot-feedback-gate',
    status: 'in_progress',
    started_at: '2026-07-30T01:00:00Z',
  }],
  commitStatuses: [{
    id: 13,
    context: 'bot-feedback-gate',
    state: 'success',
    updated_at: '2026-07-30T02:00:00Z',
  }],
});
assert.equal(newerPass.pending, false);
assert.equal(newerPass.failed, false);
assert.equal(
  evaluateRequiredCheckState({
    requiredNames: ['bot-feedback-gate'],
    ignoredNames: ['bot-feedback-gate'],
    headCheckRuns: [{
      name: 'bot-feedback-gate',
      status: 'in_progress',
    }],
  }).pending,
  false,
);

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
assert.match(
  branchProtection,
  /required_status_checks:\s*\{\s*strict:\s*true,\s*contexts:\s*mergedContexts\s*\}/,
);

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
  /uses:\s*actions\/checkout@v4\s*\r?\n\s+with:\s*\r?\n\s+ref:\s*\$\{\{\s*github\.event\.pull_request\.base\.sha\s*\|\|\s*github\.event\.repository\.default_branch\s*\}\}\s*\r?\n\s+persist-credentials:\s*false/,
  'the feedback gate must execute trusted policy code from the protected base without checkout credentials',
);
assert.doesNotMatch(feedbackWorkflow, /^concurrency:/m);
assert.doesNotMatch(feedbackWorkflow, /cancel-in-progress:/);
assert.match(feedbackWorkflow, /timeout-minutes:\s*5/);
assert.match(feedbackWorkflow, /types:\s*\[created, edited, deleted\]/);
assert.match(feedbackWorkflow, /if ! PR_STATE=\$\(gh api/);
assert.match(feedbackWorkflow, /GitHub API could not read PR state; retry this check/);
assert.match(feedbackWorkflow, /for attempt in 1 2 3 4/);
assert.match(feedbackWorkflow, /\[ "\$code" -ne 3 \]/);
assert.match(feedbackWorkflow, /sleep 5/);
assert.doesNotMatch(feedbackWorkflow, /queue:\s*max/);
assert.doesNotMatch(feedbackWorkflow, /pull_request\.head\.sha|github\.sha/);
assert.match(feedbackWorkflow, /elif \[ "\$code" -eq 3 \]/);
assert.match(feedbackWorkflow, /Feedback gate execution failed permanently/);
assert.doesNotMatch(feedbackWorkflow, /seq 1 40|sleep 60|40 minutes/);

const feedbackCheck = readFileSync('scripts/pr-bot-feedback-check.mjs', 'utf8');
assert.match(
  feedbackCheck,
  /process\.exit\(result\.violations\.length \? 3 : 0\)/,
  'open feedback must have a distinct retryable exit from hard execution failures',
);
assert.match(
  feedbackCheck,
  /GitHub API check could not complete:[\s\S]*process\.exit\(2\)/,
  'PR/API read failures must remain retryable rather than becoming permanent execution failures',
);

const waitForBots = readFileSync('wait_for_bots.mjs', 'utf8');
assert.match(waitForBots, /fetchRequiredCheckState/);
assert.match(waitForBots, /headRefOid,baseRefName/);
const botWaitState = readFileSync('scripts/lib/bot-wait-state.mjs', 'utf8');
assert.match(botWaitState, /rev-parse', '--git-path', 'ar-bot-wait'/);

const appCi = readFileSync('.github/workflows/app-ci.yml', 'utf8');
assert.match(
  appCi,
  /pull_request:\s*\r?\n\s+paths:/,
  'AR-local product CI remains path-filtered and is not invented as a universal required check',
);

console.log('PASS verify-pr-review-policy: reviewers advisory; feedback gate required');
