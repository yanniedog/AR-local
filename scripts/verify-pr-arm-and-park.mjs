#!/usr/bin/env node
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  armAndParkOnce,
  classifyGateFailure,
  classifyPostProgressState,
  classifyWorkMode,
  progressionFailureDetail,
  requireNewlyReadyChecks,
} from './lib/pr-arm-and-park-lib.mjs';
import { shouldMarkReady } from './lib/pr-branch-sync.mjs';
import { checkDefaultBase, evaluateDefaultBase } from './lib/pr-base-guard.mjs';
import {
  fetchRequiredCi,
  gateCiRequiredResult,
  gateGithubBotChecksResult,
  gateShipCloseoutSubgates,
} from './lib/pr-gates-lib.mjs';

assert.equal(evaluateDefaultBase('main', 'main').covered, true);
assert.equal(evaluateDefaultBase('feature/base', 'main').covered, false);
assert.equal(evaluateDefaultBase('main', null).covered, false);
assert.equal(
  checkDefaultBase('main', () => ({ defaultBranchRef: { name: 'main' } })).covered,
  true,
);
assert.equal(
  checkDefaultBase('main', () => { throw new Error('offline'); }).covered,
  false,
);

assert.equal(
  classifyGateFailure({
    id: 'ci-required',
    pass: false,
    pending: true,
    detail: 'Required checks have not reported on the current head yet',
  }),
  'waiting',
);
assert.equal(
  classifyGateFailure({
    id: 'ci-required',
    pass: false,
    detail: 'A failed check happened to include the word pending',
  }),
  'actionable',
);
assert.equal(
  classifyGateFailure({
    id: 'github-bot-gates',
    pass: false,
    detail: 'bot-feedback-gate: pending',
  }),
  'actionable',
);
assert.equal(
  classifyGateFailure({ id: 'pr-bot-feedback-check', pass: false }),
  'actionable',
);
assert.equal(
  classifyGateFailure({ id: 'merge-subgates', pass: false, exitCode: 2 }),
  'waiting',
);
assert.equal(
  classifyGateFailure({ id: 'merge-subgates', pass: false, exitCode: 1 }),
  'actionable',
);
assert.equal(
  gateShipCloseoutSubgates(
    { pass: false, exitCode: 2 },
    { pass: true, exitCode: 0 },
  ).exitCode,
  2,
);

const missingRequiredChecks = {
  ok: true,
  pending: true,
  failed: false,
  failedNames: [],
  pendingNames: ['bot-feedback-gate'],
  missingNames: ['bot-feedback-gate'],
  missing: true,
  checks: [],
};
assert.equal(missingRequiredChecks.pending, true);
assert.equal(missingRequiredChecks.missing, true);
assert.equal(
  classifyGateFailure(gateCiRequiredResult(missingRequiredChecks)),
  'waiting',
);
const missingFeedbackGate = gateGithubBotChecksResult(missingRequiredChecks);
assert.equal(missingFeedbackGate.pending, true);
assert.equal(classifyGateFailure(missingFeedbackGate), 'waiting');
const pendingFeedbackGate = gateGithubBotChecksResult({
  ok: true,
  failedNames: [],
  pendingNames: ['bot-feedback-gate'],
  missingNames: [],
});
assert.equal(pendingFeedbackGate.pending, true);
assert.equal(classifyGateFailure(pendingFeedbackGate), 'waiting');
const failedFeedbackGate = gateGithubBotChecksResult({
  ok: true,
  failedNames: ['bot-feedback-gate'],
  pendingNames: [],
  missingNames: [],
});
assert.equal(failedFeedbackGate.pending, false);
assert.equal(classifyGateFailure(failedFeedbackGate), 'actionable');

assert.equal(
  classifyWorkMode({
    gates: [
      { id: 'ci-required', pass: false, pending: true },
      { id: 'merge-subgates', pass: false, exitCode: 2 },
    ],
  }).mode,
  'waiting',
);
assert.equal(
  classifyWorkMode({
    gates: [
      { id: 'ci-required', pass: false, pending: true },
      { id: 'pr-bot-feedback-check', pass: false },
    ],
  }).mode,
  'actionable',
);
assert.equal(
  requireNewlyReadyChecks(
    { mode: 'ready', actionable: [], waiting: [], gates: [] },
    true,
  ).mode,
  'waiting',
);
assert.equal(
  requireNewlyReadyChecks(
    { mode: 'actionable', actionable: [{ id: 'threads' }], waiting: [], gates: [] },
    true,
  ).mode,
  'actionable',
);

assert.equal(classifyPostProgressState({ state: 'OPEN' }, 7), null);
assert.equal(shouldMarkReady({ state: 'OPEN', isDraft: true }), false);
assert.equal(shouldMarkReady({ state: 'OPEN', isDraft: true }, true), true);
assert.equal(shouldMarkReady({ state: 'OPEN', isDraft: false }, true), false);
assert.equal(shouldMarkReady({ state: 'MERGED', isDraft: true }, true), false);
assert.equal(
  progressionFailureDetail({
    ready: { detail: 'gh pr ready failed: auth denied' },
    sync: null,
  }),
  'gh pr ready failed: auth denied',
);
assert.match(
  fetchRequiredCi.toString(),
  /fetchRequiredCheckState/,
  'required checks must be evaluated against the exact current PR head',
);
assert.deepEqual(
  classifyPostProgressState({ state: 'MERGED' }, 7),
  {
    mode: 'ready',
    merged: true,
    classification: {
      mode: 'ready',
      actionable: [],
      waiting: [],
      gates: [{
        id: 'terminal-state',
        pass: true,
        detail: 'PR #7 merged while auto-merge was being armed',
      }],
    },
  },
);
assert.equal(classifyPostProgressState({ state: 'CLOSED' }, 7).mode, 'actionable');

const openMeta = {
  number: 7,
  state: 'OPEN',
  isDraft: true,
  baseRefName: 'main',
  headRefName: 'agent/test',
  mergeStateStatus: 'CLEAN',
  mergeable: 'MERGEABLE',
};
const baseGuard = { covered: true, detail: 'base covered' };
const readinessFailure = armAndParkOnce(
  7,
  { baseGuard },
  {
    fetchPrMergeMeta: () => openMeta,
    progressPullRequest: () => ({
      blocked: true,
      hardError: true,
      ok: false,
      ready: { ok: false, action: 'failed', detail: 'gh pr ready failed: auth denied' },
    }),
  },
);
assert.equal(readinessFailure.mode, 'error');
assert.equal(readinessFailure.error, 'gh pr ready failed: auth denied');
assert.equal(
  readinessFailure.progression.ready.detail,
  'gh pr ready failed: auth denied',
);

let thrownRaceFetches = 0;
const mergedAfterThrownProgression = armAndParkOnce(
  7,
  { baseGuard },
  {
    fetchPrMergeMeta: () => {
      thrownRaceFetches += 1;
      return thrownRaceFetches === 1 ? openMeta : { ...openMeta, state: 'MERGED' };
    },
    progressPullRequest: () => { throw new Error('gh pr merge raced'); },
  },
);
assert.equal(mergedAfterThrownProgression.mode, 'ready');
assert.equal(mergedAfterThrownProgression.merged, true);
assert.equal(mergedAfterThrownProgression.progression, null);

let blockedRaceFetches = 0;
const mergedAfterBlockedProgression = armAndParkOnce(
  7,
  { baseGuard },
  {
    fetchPrMergeMeta: () => {
      blockedRaceFetches += 1;
      return blockedRaceFetches === 1 ? openMeta : { ...openMeta, state: 'MERGED' };
    },
    progressPullRequest: () => ({
      blocked: true,
      ok: false,
      branchState: { detail: 'branch became blocked' },
    }),
  },
);
assert.equal(mergedAfterBlockedProgression.mode, 'ready');
assert.equal(mergedAfterBlockedProgression.merged, true);

let explicitProgressOptions;
armAndParkOnce(
  7,
  { baseGuard },
  {
    fetchPrMergeMeta: () => ({ ...openMeta, isDraft: false }),
    progressPullRequest: (_pr, options) => {
      explicitProgressOptions = options;
      return {
        blocked: false,
        ok: true,
        ready: { action: 'skipped' },
        autoMerge: { ok: true },
      };
    },
    evaluateGates: () => ({ gates: [] }),
  },
);
assert.equal(explicitProgressOptions.markReady, true);

const dryRunResult = armAndParkOnce(
  7,
  { baseGuard, dryRun: true },
  {
    fetchPrMergeMeta: () => ({ ...openMeta, isDraft: false, autoMergeRequest: null }),
    progressPullRequest: () => ({
      blocked: false,
      ok: true,
      ready: { action: 'skipped' },
      autoMerge: { ok: true, action: 'skipped' },
    }),
    evaluateGates: () => ({ gates: [] }),
  },
);
assert.equal(dryRunResult.autoMergeArmed, false);

const mergeWrapper = readFileSync('scripts/pr-merge.mjs', 'utf8');
assert.match(mergeWrapper, /checkDefaultBase/);
assert.match(mergeWrapper, /base-unprotected/);
assert.match(mergeWrapper, /markReady:\s*true/);
assert.match(
  readFileSync('scripts/lib/pr-branch-sync.mjs', 'utf8'),
  /enableAuto \? checkDefaultBase/,
);
for (const backgroundCaller of [
  'scripts/pr-watch-once.mjs',
  'scripts/pr-queue-drive.mjs',
  'scripts/pr-update-branch.mjs',
]) {
  assert.doesNotMatch(
    readFileSync(backgroundCaller, 'utf8'),
    /markReady:\s*true/,
    `${backgroundCaller} must not publish drafts`,
  );
}

console.log('pr arm-and-park verification passed');
