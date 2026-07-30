import { evaluateGates } from './pr-gates-lib.mjs';
import { checkDefaultBase, BASE_GUARD_GATE_ID } from './pr-base-guard.mjs';
import {
  fetchPrMergeMeta,
  isAutoMergeEnabled,
  progressPullRequest,
} from './pr-branch-sync.mjs';

const ALWAYS_ACTIONABLE = new Set([
  'gh-auth',
  'branch-fresh',
  'auto-merge',
  'pr-bot-feedback-check',
  BASE_GUARD_GATE_ID,
]);

export function classifyGateFailure(gate) {
  if (!gate || gate.pass) return 'ok';
  if (ALWAYS_ACTIONABLE.has(gate.id)) return 'actionable';
  if (gate.id === 'ci-required') {
    return /pending/i.test(gate.detail || '') ? 'waiting' : 'actionable';
  }
  if (gate.id === 'github-bot-gates') {
    return /not reported yet|pending|in_progress|queued/i.test(gate.detail || '')
      ? 'waiting'
      : 'actionable';
  }
  if (gate.id === 'wait-for-bots') {
    return gate.exitCode === 2 ? 'waiting' : 'actionable';
  }
  if (gate.id === 'merge-subgates') {
    return gate.exitCode === 2 ? 'waiting' : 'actionable';
  }
  return 'actionable';
}

export function classifyWorkMode(gatesResult) {
  const failing = (gatesResult.gates || []).filter((gate) => !gate.pass);
  const actionable = failing.filter((gate) => classifyGateFailure(gate) === 'actionable');
  const waiting = failing.filter((gate) => classifyGateFailure(gate) === 'waiting');
  const mode = actionable.length ? 'actionable' : waiting.length ? 'waiting' : 'ready';
  return { mode, actionable, waiting, gates: gatesResult.gates || [] };
}

export function requireNewlyReadyChecks(classification, wasMarkedReady) {
  if (!wasMarkedReady) return classification;
  const gate = {
    id: 'ci-required',
    pass: false,
    detail: 'Required checks have not reported on the newly-ready head',
  };
  const waiting = [...(classification.waiting || [])];
  if (!waiting.some((item) => item.id === gate.id && /newly-ready/i.test(item.detail || ''))) {
    waiting.push(gate);
  }
  return {
    ...classification,
    mode: classification.actionable?.length ? 'actionable' : 'waiting',
    waiting,
  };
}

export function classifyPostProgressState(meta, prNumber) {
  if (!meta || meta.state === 'OPEN') return null;
  if (meta.state === 'MERGED') {
    return {
      mode: 'ready',
      merged: true,
      classification: {
        mode: 'ready',
        actionable: [],
        waiting: [],
        gates: [{
          id: 'terminal-state',
          pass: true,
          detail: `PR #${prNumber} merged while auto-merge was being armed`,
        }],
      },
    };
  }
  return {
    mode: 'actionable',
    merged: false,
    classification: {
      mode: 'actionable',
      actionable: [{
        id: 'branch-fresh',
        pass: false,
        detail: `PR #${prNumber} changed state unexpectedly (${meta.state})`,
      }],
      waiting: [],
    },
  };
}

/**
 * Verify the exact default base, mark a draft ready, sync when needed, arm
 * squash auto-merge, and classify the remaining state. Never polls.
 */
export function armAndParkOnce(prNumber, opts = {}) {
  let meta;
  try {
    meta = fetchPrMergeMeta(prNumber);
  } catch (error) {
    return { mode: 'error', error: error.message, autoMergeArmed: false };
  }

  const baseGuard = opts.baseGuard ?? checkDefaultBase(meta.baseRefName);
  if (!baseGuard.covered) {
    return {
      mode: 'actionable',
      autoMergeArmed: false,
      baseGuard,
      classification: {
        mode: 'actionable',
        actionable: [{ id: BASE_GUARD_GATE_ID, pass: false, detail: baseGuard.detail }],
        waiting: [],
      },
    };
  }

  const progression = progressPullRequest(prNumber, {
    dryRun: Boolean(opts.dryRun),
    syncBranch: !opts.skipSync,
    enableAuto: !opts.skipArm,
  });
  if (progression.blocked) {
    return {
      mode: 'actionable',
      progression,
      baseGuard,
      autoMergeArmed: false,
      classification: {
        mode: 'actionable',
        actionable: [{
          id: 'branch-fresh',
          pass: false,
          detail:
            progression.ready?.action === 'failed'
              ? progression.ready.detail
              : progression.sync?.detail || progression.branchState?.detail,
        }],
        waiting: [],
      },
    };
  }

  let postProgress = null;
  try {
    postProgress = fetchPrMergeMeta(prNumber, { requireOpen: false });
  } catch {
    // Gate evaluation below reports a hard API/auth failure if the PR is open.
  }
  const terminal = classifyPostProgressState(postProgress, prNumber);
  if (terminal?.merged) {
    return {
      ...terminal,
      progression,
      baseGuard,
      autoMergeArmed: progression.autoMerge?.ok === true,
    };
  }
  if (terminal) {
    return {
      ...terminal,
      progression,
      baseGuard,
      autoMergeArmed: false,
    };
  }

  const gates = evaluateGates(prNumber);
  const classification = requireNewlyReadyChecks(
    classifyWorkMode(gates),
    progression.ready?.action === 'ready',
  );
  let refreshed = postProgress || meta;
  try {
    refreshed = fetchPrMergeMeta(prNumber);
  } catch {
    // The progression result still proves whether the arm command succeeded.
  }
  return {
    mode: classification.mode,
    progression,
    gates,
    classification,
    baseGuard,
    autoMergeArmed:
      isAutoMergeEnabled(refreshed) || progression.autoMerge?.ok === true,
  };
}
