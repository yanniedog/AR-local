#!/usr/bin/env node
/**
 * Dynamic pre-merge bot wait gate (AR-local WORKFLOW.md step 5).
 * Polls GitHub until CI checks settle and bot review activity is quiet,
 * or until a safety cap. Exit 0 = ready, 2 = still waiting, 1 = error/timeout.
 */
import { execSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { setTimeout as sleepMs } from 'node:timers/promises';

const DEFAULT_BOT_LOGINS = [
  'gemini-code-assist[bot]',
  'chatgpt-codex-connector[bot]',
  'sourcery-ai[bot]',
  'copilot-pull-request-reviewer[bot]',
  'coderabbitai[bot]',
];

const POLL_INTERVAL_SEC = Number(process.env.BOT_WAIT_POLL_SEC || 45);
const QUIET_WINDOW_SEC = Number(process.env.BOT_WAIT_QUIET_SEC || 90);
const MIN_WAIT_SEC = Number(process.env.BOT_WAIT_MIN_SEC || 60);
const MAX_WAIT_MIN = Number(process.env.BOT_WAIT_MAX_MIN || 28);

const BOT_LOGINS = (process.env.BOT_WAIT_LOGINS || '')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);
const EXPECTED_BOTS = BOT_LOGINS.length > 0 ? BOT_LOGINS : DEFAULT_BOT_LOGINS;

const COMMENTS_QUERY =
  'query($owner:String!,$name:String!,$num:Int!){repository(owner:$owner,name:$name){pullRequest(number:$num){comments(last:100){nodes{author{login}createdAt}}reviews(last:30){nodes{author{login}submittedAt}}reviewThreads(last:100){nodes{comments(last:10){nodes{author{login}createdAt}}}}}}}';

function sh(cmd) {
  try {
    return execSync(cmd, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    return '';
  }
}

function gh(args, { json = false } = {}) {
  const r = spawnSync('gh', args, { encoding: 'utf8' });
  if (r.error) return { ok: false, error: r.error.message };
  if (r.status !== 0) {
    return { ok: false, error: (r.stderr || '').trim() || `gh exit ${r.status}` };
  }
  const stdout = (r.stdout || '').trim();
  if (json && stdout) {
    try {
      return { ok: true, data: JSON.parse(stdout) };
    } catch (e) {
      return { ok: false, error: `Invalid JSON from gh: ${e.message}` };
    }
  }
  return { ok: true, data: stdout };
}

function hasGh() {
  return spawnSync('gh', ['--version'], { stdio: 'ignore' }).status === 0;
}

function repoRoot() {
  return sh('git rev-parse --show-toplevel') || process.cwd();
}

function currentBranch() {
  return sh('git rev-parse --abbrev-ref HEAD');
}

function isTopicBranch(b) {
  return /^(agent|feat|fix)\//.test(b);
}

function parseArgs(argv) {
  const out = { pr: null, watch: false, botTag: false, since: null, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--watch' || a === '-w') out.watch = true;
    else if (a === '--bot-tag') out.botTag = true;
    else if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a.startsWith('--pr=')) out.pr = Number(a.slice(5));
    else if ((a === '--since' || a === '--anchor') && argv[i + 1]) out.since = argv[++i];
    else if (a.startsWith('--since=') || a.startsWith('--anchor=')) out.since = a.split('=').slice(1).join('=');
  }
  return out;
}

function statePath(prNumber) {
  return path.join(repoRoot(), '.git', 'ar-bot-wait', `${prNumber}.json`);
}

function readState(prNumber) {
  const p = statePath(prNumber);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

function writeState(prNumber, state) {
  const p = statePath(prNumber);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
}

function resolveRepo() {
  const r = gh(['repo', 'view', '--json', 'nameWithOwner'], { json: true });
  if (!r.ok || !r.data?.nameWithOwner) return null;
  const [owner, name] = r.data.nameWithOwner.split('/');
  return { owner, name };
}

function resolvePr(prArg, branch) {
  if (prArg) {
    const r = gh(['pr', 'view', String(prArg), '--json', 'number,createdAt,headRefName'], { json: true });
    if (!r.ok) return { error: r.error };
    return { pr: r.data };
  }
  if (!branch) return { pr: null };
  const r = gh(['pr', 'list', '--state', 'open', '--head', branch, '--json', 'number,createdAt,headRefName'], {
    json: true,
  });
  if (!r.ok) return { error: r.error };
  const arr = Array.isArray(r.data) ? r.data : [];
  return { pr: arr.length > 0 ? arr[0] : null };
}

function isBotLogin(login) {
  if (!login) return false;
  const lower = login.toLowerCase();
  return EXPECTED_BOTS.some((b) => lower === b.toLowerCase());
}

function fetchBotActivity(owner, name, prNumber) {
  const r = gh(
    ['api', 'graphql', '-f', `query=${COMMENTS_QUERY}`, '-F', `owner=${owner}`, '-F', `name=${name}`, '-F', `num=${prNumber}`],
    { json: true },
  );
  if (!r.ok) return { error: r.error, events: [] };

  const pr = r.data?.data?.repository?.pullRequest;
  if (!pr) return { error: 'GraphQL: pull request not found', events: [] };

  const events = [];
  for (const c of pr.comments?.nodes || []) {
    if (c.author?.login && c.createdAt) events.push({ login: c.author.login, at: c.createdAt });
  }
  for (const rev of pr.reviews?.nodes || []) {
    if (rev.author?.login && rev.submittedAt) events.push({ login: rev.author.login, at: rev.submittedAt });
  }
  for (const t of pr.reviewThreads?.nodes || []) {
    for (const c of t.comments?.nodes || []) {
      if (c.author?.login && c.createdAt) events.push({ login: c.author.login, at: c.createdAt });
    }
  }
  events.sort((a, b) => new Date(a.at) - new Date(b.at));
  return { events };
}

function fetchChecks(prNumber) {
  const r = spawnSync('gh', ['pr', 'checks', String(prNumber), '--json', 'name,bucket,state'], {
    encoding: 'utf8',
  });
  // gh pr checks exits 8 when checks are still pending (see gh manual).
  if (r.status === 8) return { pending: true };
  if (r.status !== 0) {
    const msg = (r.stderr || '').trim() || `gh pr checks exit ${r.status}`;
    return { pending: true, error: msg };
  }
  const stdout = (r.stdout || '').trim();
  if (!stdout) return { pending: true };
  try {
    const checks = JSON.parse(stdout);
    return {
      pending: Array.isArray(checks) && checks.some((c) => c.bucket === 'pending'),
    };
  } catch (e) {
    return { pending: true, error: `Invalid JSON from gh pr checks: ${e.message}` };
  }
}

function formatDuration(ms) {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function evaluate({ prNumber, anchorIso, state, repo: repoIn }) {
  const anchor = new Date(anchorIso);
  if (!Number.isFinite(anchor.getTime())) {
    return { status: 'error', message: `Invalid anchor time: ${anchorIso}` };
  }

  const repo = repoIn || resolveRepo();
  if (!repo) return { status: 'error', message: 'Could not resolve repository (gh repo view).' };

  const elapsedMs = Date.now() - anchor.getTime();
  const maxMs = MAX_WAIT_MIN * 60 * 1000;
  if (elapsedMs > maxMs) {
    return {
      status: 'timeout',
      message:
        `Bot wait safety cap (${MAX_WAIT_MIN} min) exceeded since anchor ${anchor.toISOString()}. ` +
        'Re-sweep manually or tag bots again.',
    };
  }

  if (state?.readyAt) {
    const readyAt = new Date(state.readyAt);
    if (Number.isFinite(readyAt.getTime()) && readyAt >= anchor) {
      return { status: 'ready', message: `Bot wait already satisfied at ${state.readyAt} (cached). Clear to sweep.` };
    }
  }

  const activity = fetchBotActivity(repo.owner, repo.name, prNumber);
  if (activity.error) return { status: 'error', message: activity.error };

  const checks = fetchChecks(prNumber);
  if (checks.error && !checks.pending) {
    return { status: 'error', message: checks.error };
  }

  const anchorMs = anchor.getTime();
  const botEventsSinceAnchor = activity.events.filter(
    (e) => isBotLogin(e.login) && new Date(e.at).getTime() >= anchorMs,
  );
  const lastBotAt =
    botEventsSinceAnchor.length > 0
      ? new Date(botEventsSinceAnchor[botEventsSinceAnchor.length - 1].at)
      : null;

  const botsSinceAnchor = new Set(botEventsSinceAnchor.map((e) => e.login));
  const allBotsPosted = EXPECTED_BOTS.every((b) =>
    [...botsSinceAnchor].some((seen) => seen.toLowerCase() === b.toLowerCase()),
  );
  const anyBotPosted = botsSinceAnchor.size > 0;
  const quiet = lastBotAt !== null && Date.now() - lastBotAt.getTime() >= QUIET_WINDOW_SEC * 1000;
  const checksReady = !checks.pending;
  const minElapsed = elapsedMs >= MIN_WAIT_SEC * 1000;
  const botsPreexisting =
    state?.readyAt && state?.lastBotAt && lastBotAt && state.lastBotAt === lastBotAt.toISOString();

  if (checksReady && (minElapsed || botsPreexisting) && anyBotPosted && (quiet || allBotsPosted)) {
    const reason = allBotsPosted
      ? `all ${EXPECTED_BOTS.length} configured bots posted`
      : `checks settled and no bot activity for ${QUIET_WINDOW_SEC}s`;
    return {
      status: 'ready',
      message: `Bot wait satisfied (${reason}). Clear to sweep threads.`,
      lastBotAt: lastBotAt?.toISOString() || null,
      botsSeen: [...botsSinceAnchor],
    };
  }

  const waitParts = [];
  if (!checksReady) waitParts.push('CI checks still pending');
  if (!anyBotPosted) waitParts.push('no bot comments yet since anchor');
  else if (!quiet && !allBotsPosted) {
    waitParts.push(
      `bot activity ${formatDuration(Date.now() - lastBotAt.getTime())} ago (need ${QUIET_WINDOW_SEC}s quiet or all bots)`,
    );
  }
  if (!minElapsed && !botsPreexisting) {
    waitParts.push(`${Math.ceil((MIN_WAIT_SEC * 1000 - elapsedMs) / 1000)}s until minimum wait`);
  }

  return {
    status: 'waiting',
    message: `PR #${prNumber}: ${waitParts.join('; ')}.`,
    elapsedMs,
    remainingCapMs: maxMs - elapsedMs,
    lastBotAt: lastBotAt?.toISOString() || null,
    botsSeen: [...botsSinceAnchor],
  };
}

function printHelp() {
  console.log(`Usage: npm run wait-for-bots -- [options]

Poll GitHub until bot review activity is stable (or safety cap).

Options:
  --pr <n>       Pull request number (default: open PR for current branch)
  --watch, -w    Poll every ${POLL_INTERVAL_SEC}s until ready or cap (default: single check)
  --bot-tag      Reset wait anchor to now (after @mentioning bots in PR)
  --since <iso>  Anchor wait window to this timestamp (ISO 8601)
  --help, -h     Show this help

Exit codes: 0 ready | 2 still waiting | 1 error/timeout

Env: BOT_WAIT_POLL_SEC, BOT_WAIT_QUIET_SEC, BOT_WAIT_MIN_SEC, BOT_WAIT_MAX_MIN,
     BOT_WAIT_LOGINS (comma-separated)

Expected bots: ${EXPECTED_BOTS.join(', ')}
`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    process.exit(0);
  }

  const branch = currentBranch();
  const prArg = args.pr;

  if (!prArg && (!branch || !isTopicBranch(branch))) {
    process.exit(0);
  }

  if (!hasGh()) {
    console.log('(Install gh CLI for dynamic bot wait on topic branches.)');
    process.exit(0);
  }

  const resolved = resolvePr(prArg, branch);
  if (resolved.error) {
    console.error(`>>> BOT WAIT ERROR: ${resolved.error}`);
    process.exit(1);
  }
  if (!resolved.pr?.number) {
    process.exit(0);
  }

  const prNumber = resolved.pr.number;
  const repo = resolveRepo();
  if (!repo) {
    console.error('>>> BOT WAIT ERROR: Could not resolve repository (gh repo view).');
    process.exit(1);
  }
  let state = readState(prNumber) || {};
  const anchorFromPr = resolved.pr.createdAt;

  if (args.botTag) {
    const anchorIso = new Date().toISOString();
    state = { anchor: anchorIso, readyAt: null };
    writeState(prNumber, state);
    console.log(`>>> BOT WAIT: anchor reset (bot-tag) at ${anchorIso} for PR #${prNumber}`);
    console.log('>>> Re-run wait-for-bots until exit 0 before synthesis.');
  } else if (args.since) {
    state.anchor = args.since;
    state.readyAt = null;
    writeState(prNumber, state);
  } else if (!state.anchor || new Date(state.anchor) < new Date(anchorFromPr)) {
    state.anchor = anchorFromPr;
    writeState(prNumber, state);
  }

  const finish = (result) => {
    const st = readState(prNumber) || state;
    if (result.status === 'ready') {
      console.log(`>>> ${result.message}`);
      if (result.botsSeen?.length) console.log(`>>> Bots seen since anchor: ${result.botsSeen.join(', ')}`);
      st.readyAt = new Date().toISOString();
      st.lastBotAt = result.lastBotAt || st.lastBotAt;
      writeState(prNumber, st);
      process.exit(0);
    }
    if (result.status === 'timeout' || result.status === 'error') {
      console.error(`>>> BOT WAIT ${result.status.toUpperCase()}: ${result.message}`);
      process.exit(1);
    }
    console.log(`>>> BOT WAIT: ${result.message}`);
    if (result.remainingCapMs != null) {
      console.log(
        `>>> Elapsed ${formatDuration(result.elapsedMs)}; cap remaining ~${formatDuration(result.remainingCapMs)}`,
      );
    }
    console.log(`>>> PR #${prNumber} ÔÇö retry: npm run wait-for-bots -- --pr ${prNumber}`);
    process.exit(2);
  };

  const runOnce = () => {
    const st = readState(prNumber) || state;
    return evaluate({ prNumber, anchorIso: st.anchor || anchorFromPr, state: st, repo });
  };

  if (!args.watch) {
    finish(runOnce());
    return;
  }

  console.log(
    `>>> Watching PR #${prNumber} (poll ${POLL_INTERVAL_SEC}s, quiet ${QUIET_WINDOW_SEC}s, cap ${MAX_WAIT_MIN} min)`,
  );
  for (;;) {
    const result = runOnce();
    if (result.status === 'ready' || result.status === 'timeout' || result.status === 'error') {
      finish(result);
      return;
    }
    console.log(`>>> ${result.message}`);
    await sleepMs(POLL_INTERVAL_SEC * 1000);
  }
}

main().catch((err) => {
  console.error(`>>> BOT WAIT ERROR: ${err.message}`);
  process.exit(1);
});
