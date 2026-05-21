/**
 * Shared PR watch gate scan (oldest open PRs first).
 */
import { evaluateGates } from './pr-gates-lib.mjs';
import { hasGh, ghJson, repoSlug } from './gh-pr-review-threads.mjs';

const OPEN_PR_LIMIT = 100;

export function listOpenPrs() {
  const batch = ghJson([
    'pr',
    'list',
    '--state',
    'open',
    '--json',
    'number,title,headRefName,createdAt,mergeable,mergeStateStatus',
    '--limit',
    String(OPEN_PR_LIMIT),
  ]);
  const rows = (Array.isArray(batch) ? batch : []).map((pr) => ({
    number: pr.number,
    title: pr.title,
    headRefName: pr.headRefName || '',
    createdAt: pr.createdAt,
    mergeable: pr.mergeable,
    mergeStateStatus: pr.mergeStateStatus,
  }));
  return rows.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));
}

export function conflictHint(pr) {
  const ms = pr.mergeStateStatus;
  const m = pr.mergeable;
  if (ms === 'DIRTY' || m === 'CONFLICTING') {
    return 'merge conflict — rebase onto origin/main before gates can pass';
  }
  if (ms === 'BEHIND') return 'branch behind base — rebase origin/main';
  return null;
}

export function auditPr(prNumber) {
  const result = evaluateGates(prNumber, { skipFeedbackPlan: false });
  return result;
}

/**
 * @returns {{ idle: boolean, prs: object[], results: object[], allPass?: boolean, error?: string }}
 */
export async function runWatchCycle({ pr = null } = {}) {
  if (!hasGh()) {
    return { idle: false, prs: [], results: [], error: 'gh CLI missing — install and gh auth login' };
  }

  let prs;
  if (pr) {
    const view = ghJson([
      'pr',
      'view',
      String(pr),
      '--json',
      'number,title,headRefName,createdAt,state,mergeable,mergeStateStatus',
    ]);
    if (view.state !== 'OPEN') {
      return { idle: false, prs: [], results: [], error: `PR #${pr} is not open (state=${view.state})` };
    }
    prs = [view];
  } else {
    prs = listOpenPrs();
  }

  if (prs.length === 0) {
    return { idle: true, prs: [], results: [] };
  }

  const results = [];
  for (const row of prs) {
    const hint = conflictHint(row);
    const gateResult = auditPr(row.number);
    results.push({
      number: row.number,
      title: row.title,
      headRefName: row.headRefName,
      createdAt: row.createdAt,
      mergeable: row.mergeable,
      mergeStateStatus: row.mergeStateStatus,
      conflictHint: hint,
      gatesPass: gateResult.pass,
      gates: gateResult.gates,
      failingGates: gateResult.gates.filter((g) => !g.pass).map((g) => g.id),
      needsAgent: !gateResult.pass,
    });
  }

  const allPass = results.every((r) => r.gatesPass);
  return { idle: false, prs, results, allPass };
}

export function cycleToState(cycle, { prompt } = {}) {
  const openPrs = (cycle.results || []).map((r) => ({
    number: r.number,
    headRefName: r.headRefName,
    gatesPass: r.gatesPass,
    failingGates: r.failingGates,
    conflictHint: r.conflictHint,
    needsAgent: r.needsAgent,
  }));
  const remediateFirst = openPrs.filter((p) => p.needsAgent).map((p) => p.number);
  return {
    prompt: prompt || undefined,
    openPrs,
    remediateFirst,
    idle: cycle.idle,
    allPass: cycle.allPass,
  };
}
