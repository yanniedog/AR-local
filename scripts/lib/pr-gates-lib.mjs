/**
 * Shared helpers for npm run pr:gates:check (merge-blocking PR gate audit).
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readBotWaitStateFile } from './bot-wait-state.mjs';
import { hasGh, ghJson, repoSlug } from './gh-pr-review-threads.mjs';
import { isReportsOnlyPr } from './pr-reports-only.mjs';
import { fetchPrMergeMeta, gateAutoMergeEnabled, gateBranchFreshMeta } from './pr-branch-sync.mjs';
import { gateExemptReason } from './pr-gate-exempt.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(__dirname, '../..');

export const BOT_GATE_CHECK_NAMES = ['bot-presence-gate', 'bot-feedback-gate'];

const FEEDBACK_PLAN_RE = /##\s*feedback\s+plan\b/i;

const DEFAULT_TIMEOUT_MIN = 35;
const DEFAULT_POLL_SEC = 45;
const MAX_TIMEOUT_MIN = 180;
const MAX_POLL_SEC = 600;

/** Positive finite number or fallback (avoids NaN watch loops). */
export function normalizePositiveNumber(value, fallback, max = Infinity) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.min(n, max);
}

export function parseGateArgs(argv) {
  const out = {
    pr: null,
    watch: false,
    json: false,
    quiet: false,
    skipFeedbackPlan: false,
    timeoutMin: normalizePositiveNumber(
      process.env.PR_GATES_WATCH_MAX_MIN,
      DEFAULT_TIMEOUT_MIN,
      MAX_TIMEOUT_MIN,
    ),
    help: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--watch' || a === '-w') out.watch = true;
    else if (a === '--json') out.json = true;
    else if (a === '--quiet' || a === '-q') out.quiet = true;
    else if (a === '--skip-feedback-plan') out.skipFeedbackPlan = true;
    else if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a.startsWith('--pr=')) out.pr = Number(a.slice(5));
    else if (a === '--timeout-min' && argv[i + 1]) {
      out.timeoutMin = normalizePositiveNumber(argv[++i], DEFAULT_TIMEOUT_MIN, MAX_TIMEOUT_MIN);
    } else if (a.startsWith('--timeout-min=')) {
      out.timeoutMin = normalizePositiveNumber(
        a.slice('--timeout-min='.length),
        DEFAULT_TIMEOUT_MIN,
        MAX_TIMEOUT_MIN,
      );
    }
  }
  if (out.pr != null) {
    const pr = Number(out.pr);
    if (!Number.isInteger(pr) || pr <= 0) {
      out.pr = null;
      out.prError = 'invalid --pr (must be a positive integer)';
    } else {
      out.pr = pr;
    }
  }
  return out;
}

export function prForBranch(branch) {
  if (!branch || branch === 'main') return null;
  try {
    const rows = ghJson(['pr', 'list', '--state', 'open', '--head', branch, '--json', 'number,headRefName,baseRefName,state']);
    return Array.isArray(rows) && rows.length > 0 ? rows[0] : null;
  } catch {
    return null;
  }
}

export function resolvePrNumber(prArg) {
  if (prArg && Number.isFinite(prArg) && prArg > 0) {
    const view = ghJson(['pr', 'view', String(prArg), '--json', 'number,state,title,headRefName,baseRefName']);
    if (view.state !== 'OPEN') {
      return { error: `PR #${prArg} is not open (state=${view.state})` };
    }
    return { pr: view };
  }
  const branch = spawnSync('git', ['rev-parse', '--abbrev-ref', 'HEAD'], { encoding: 'utf8' }).stdout?.trim();
  const row = prForBranch(branch);
  if (!row) {
    return { error: branch === 'main' ? 'on main — pass --pr <n>' : `no open PR for branch ${branch}` };
  }
  const view = ghJson(['pr', 'view', String(row.number), '--json', 'number,state,title,headRefName,baseRefName']);
  return { pr: view, branch };
}

export function fetchRequiredCi(prNumber) {
  const r = spawnSync(
    'gh',
    ['pr', 'checks', String(prNumber), '--required', '--json', 'name,bucket,state'],
    { encoding: 'utf8' },
  );
  if (r.status === 8) {
    return { ok: true, pending: true, failed: false, failedNames: [], checks: [] };
  }
  if (r.status !== 0) {
    const msg = (r.stderr || '').trim() || `gh pr checks exit ${r.status}`;
    if (/no checks reported/i.test(msg) || /no required checks reported/i.test(msg)) {
      return { ok: true, pending: false, failed: false, failedNames: [], checks: [] };
    }
    return { ok: false, error: msg };
  }
  const checks = JSON.parse(r.stdout || '[]');
  let pending = false;
  let failed = false;
  const failedNames = [];
  for (const c of checks) {
    if (c.bucket === 'pending') pending = true;
    if (
      c.bucket === 'fail' ||
      c.bucket === 'cancel' ||
      c.state === 'FAILURE' ||
      c.state === 'ERROR' ||
      c.state === 'CANCELLED'
    ) {
      failed = true;
      failedNames.push(c.name);
    }
  }
  return { ok: true, pending, failed, failedNames, checks };
}

export function fetchNamedChecks(prNumber, names) {
  const r = spawnSync(
    'gh',
    ['pr', 'checks', String(prNumber), '--json', 'name,bucket,state,completedAt'],
    { encoding: 'utf8' },
  );
  if (r.status !== 0) {
    const msg = (r.stderr || '').trim() || `gh pr checks exit ${r.status}`;
    if (/no checks reported/i.test(msg)) return { found: {}, skipped: true };
    return { found: {}, error: msg };
  }
  const all = JSON.parse(r.stdout || '[]');
  const want = new Set(names.map((n) => n.toLowerCase()));
  const found = {};
  for (const c of all) {
    const lower = (c.name || '').toLowerCase();
    const tail = lower.includes('/') ? lower.slice(lower.lastIndexOf('/') + 1) : lower;
    for (const key of want) {
      if (lower === key || tail === key) found[key] = c;
    }
  }
  return { found };
}

function checkBucketPass(c) {
  if (!c) return null;
  if (c.bucket === 'pass' || c.state === 'SUCCESS') return true;
  if (c.bucket === 'pending' || c.state === 'PENDING' || c.state === 'IN_PROGRESS') return false;
  return false;
}

export function gateCiRequired(prNumber) {
  const ci = fetchRequiredCi(prNumber);
  if (!ci.ok) {
    return { id: 'ci-required', pass: false, detail: ci.error, action: 'Fix gh auth or repo access; run gh pr checks <n>' };
  }
  if (ci.failed) {
    return {
      id: 'ci-required',
      pass: false,
      detail: `Failed: ${ci.failedNames.join(', ')}`,
      action: 'Fix failing required checks; gh pr checks <n> --watch',
    };
  }
  if (ci.pending) {
    return {
      id: 'ci-required',
      pass: false,
      detail: 'Required checks still pending',
      action: 'Wait for CI; gh pr checks <n> --watch',
    };
  }
  return { id: 'ci-required', pass: true, detail: 'All required checks passed' };
}

export function gateGithubBotChecks(prNumber) {
  const { found, error, skipped } = fetchNamedChecks(prNumber, BOT_GATE_CHECK_NAMES);
  if (error) {
    return {
      id: 'github-bot-gates',
      pass: false,
      detail: error,
      action: 'Ensure GitHub Actions workflows pr-bot-presence-gate and pr-bot-feedback-check ran',
    };
  }
  if (skipped || !BOT_GATE_CHECK_NAMES.some((name) => found[name])) {
    return {
      id: 'github-bot-gates',
      pass: true,
      detail: 'No GitHub bot gate checks reported; relying on local wait/thread gates',
      skipped: true,
    };
  }
  const parts = [];
  let pass = true;
  let botPresencePass = false;
  let botPresenceCompletedAt = null;
  for (const name of BOT_GATE_CHECK_NAMES) {
    const c = found[name];
    if (!c) {
      parts.push(`${name}: not reported yet`);
      pass = false;
      continue;
    }
    const ok = checkBucketPass(c);
    if (ok === true) {
      parts.push(`${name}: pass`);
      if (name === 'bot-presence-gate') {
        botPresencePass = true;
        botPresenceCompletedAt = c.completedAt || null;
      }
    }
    else if (ok === false) {
      parts.push(`${name}: ${c.bucket || c.state}`);
      pass = false;
    } else {
      parts.push(`${name}: ${c.bucket || c.state} (failed)`);
      pass = false;
    }
  }
  return {
    id: 'github-bot-gates',
    pass,
    detail: parts.join('; '),
    botPresencePass,
    botPresenceCompletedAt,
    action: pass
      ? undefined
      : 'Wait for bot-presence-gate and bot-feedback-gate on GitHub (branch protection)',
  };
}

export function runNodeScript(relPath, extraArgs = [], { env: envOverrides, maxBuffer, timeout } = {}) {
  const script = path.join(REPO_ROOT, relPath);
  const r = spawnSync(process.execPath, [script, ...extraArgs], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    env: { ...process.env, ...(envOverrides || {}) },
    maxBuffer: maxBuffer || 1024 * 1024,
    timeout: timeout || 120_000,
  });
  return {
    exitCode: r.status ?? 1,
    stdout: (r.stdout || '').trim(),
    stderr: (r.stderr || '').trim(),
  };
}

export function gateWaitForBots(prNumber, githubBotGate) {
  const exempt = gateExemptReason(prNumber);
  if (exempt) {
    return {
      id: 'wait-for-bots',
      pass: true,
      detail: `Skipped (${exempt} — human bot review not required)`,
      skipped: true,
    };
  }
  if (githubBotGate?.botPresencePass) {
    const state = readBotWaitStateFile(prNumber, REPO_ROOT);
    const anchorMs = new Date(state?.anchor || '').getTime();
    const gateMs = new Date(githubBotGate.botPresenceCompletedAt || '').getTime();
    if (!Number.isFinite(anchorMs) || (Number.isFinite(gateMs) && anchorMs <= gateMs)) {
      return {
        id: 'wait-for-bots',
        pass: true,
        detail: 'Bot wait satisfied by green GitHub bot-presence-gate',
        exitCode: 0,
      };
    }
  }
  const { exitCode, stderr, stdout } = runNodeScript('wait_for_bots.mjs', ['--pr', String(prNumber)]);
  if (exitCode === 0) {
    return { id: 'wait-for-bots', pass: true, detail: 'Bot wait satisfied (exit 0)', exitCode };
  }
  const msg = stderr || stdout || `exit ${exitCode}`;
  return {
    id: 'wait-for-bots',
    pass: false,
    detail: msg.split('\n').slice(-3).join(' '),
    exitCode,
    action:
      exitCode === 2
        ? `npm run wait-for-bots -- --watch --pr ${prNumber}`
        : `npm run wait-for-bots -- --pr ${prNumber} (exit 1 = missing bots or error — do not merge)`,
  };
}

export function gateBotFeedback(prNumber) {
  const exempt = gateExemptReason(prNumber);
  if (exempt) {
    return {
      id: 'pr-bot-feedback-check',
      pass: true,
      detail: `Skipped (${exempt} — human bot review not required)`,
      skipped: true,
    };
  }
  const { exitCode, stderr, stdout } = runNodeScript('scripts/pr-bot-feedback-check.mjs', [
    '--pr',
    String(prNumber),
    '--quiet',
    '--skip-bot-presence',
  ]);
  if (exitCode === 0) {
    return { id: 'pr-bot-feedback-check', pass: true, detail: 'Thread closure gate passed', exitCode };
  }
  return {
    id: 'pr-bot-feedback-check',
    pass: false,
    detail: (stderr || stdout || `exit ${exitCode}`).split('\n').slice(0, 4).join(' '),
    exitCode,
    action: `Close substantive threads in-thread; npm run pr:bot-feedback-check -- --pr ${prNumber}`,
  };
}

export function hasFeedbackPlanComment(prNumber) {
  const { owner, name } = repoSlug();
  // Paginated gh api emits one JSON blob per page unless --slurp wraps them (see gh api manual).
  const r = spawnSync(
    'gh',
    ['api', `repos/${owner}/${name}/issues/${prNumber}/comments`, '--paginate', '--slurp'],
    { encoding: 'utf8' },
  );
  if (r.status !== 0) {
    throw new Error((r.stderr || r.stdout || 'gh api issue comments failed').trim());
  }
  const comments = JSON.parse(r.stdout || '[]');
  const list = (Array.isArray(comments) ? comments : []).flatMap((page) =>
    Array.isArray(page) ? page : [],
  );
  return list.some((c) => FEEDBACK_PLAN_RE.test(c.body || ''));
}

export function gateFeedbackPlan(prNumber, { skip, waitPass, feedbackPass }) {
  if (skip) {
    return { id: 'feedback-plan', pass: true, detail: 'Skipped (--skip-feedback-plan)', skipped: true };
  }
  if (feedbackPass) {
    return { id: 'feedback-plan', pass: true, detail: 'Thread gate passed — synthesis complete' };
  }
  if (!waitPass) {
    return {
      id: 'feedback-plan',
      pass: true,
      detail: 'Deferred until wait-for-bots exit 0 (WORKFLOW.md step 5b)',
      waived: true,
    };
  }
  if (hasFeedbackPlanComment(prNumber)) {
    return { id: 'feedback-plan', pass: true, detail: '## Feedback plan found on PR' };
  }
  return {
    id: 'feedback-plan',
    pass: false,
    detail: 'Bot wait ready but no ## Feedback plan comment and threads still open',
    action: `Post one ## Feedback plan on PR #${prNumber} before in-thread replies (WORKFLOW.md step 5b)`,
  };
}

export function gateShipCloseoutSubgates(waitGate, feedbackGate) {
  const pass = waitGate.pass && feedbackGate.pass;
  return {
    id: 'ship-closeout-subgates',
    pass,
    detail: pass
      ? 'Same checks ship:closeout:strict runs on topic branches (merge blockers clear)'
      : 'ship:closeout:strict would exit 2 until wait-for-bots and pr:bot-feedback-check pass',
    action: pass ? undefined : 'npm run ship:closeout:strict (after fixes above)',
    note: 'ship:closeout:strict exit 0 on an open PR branch only after merge/close; use pr:gates:check for merge readiness',
  };
}

export function evaluateGates(prNumber, options = {}) {
  if (!hasGh()) {
    return {
      prNumber,
      pass: false,
      gates: [
        {
          id: 'gh-auth',
          pass: false,
          detail: 'gh CLI missing or not on PATH',
          action: 'Install GitHub CLI and run gh auth login',
        },
      ],
    };
  }

  let branchFresh = { id: 'branch-fresh', pass: true, skipped: true };
  let autoMergeGate = { id: 'auto-merge', pass: true, skipped: true };
  try {
    const meta = fetchPrMergeMeta(prNumber);
    branchFresh = gateBranchFreshMeta(meta);
    autoMergeGate = gateAutoMergeEnabled(meta);
  } catch (e) {
    branchFresh = { id: 'branch-fresh', pass: false, detail: e.message };
  }

  const ci = gateCiRequired(prNumber);
  const ghBot = gateGithubBotChecks(prNumber);
  const wait = gateWaitForBots(prNumber, ghBot);
  const feedback = gateBotFeedback(prNumber);
  const plan = gateFeedbackPlan(prNumber, {
    skip: options.skipFeedbackPlan,
    waitPass: wait.pass,
    feedbackPass: feedback.pass,
  });
  const closeout = gateShipCloseoutSubgates(wait, feedback);

  const gates = [
    { id: 'gh-auth', pass: true, detail: 'gh available' },
    branchFresh,
    autoMergeGate,
    ci,
    ghBot,
    wait,
    feedback,
    plan,
    closeout,
  ];

  return {
    prNumber,
    pass: gates.every((g) => g.pass),
    gates,
  };
}

export { hasGh, repoSlug };
