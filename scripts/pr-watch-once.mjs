#!/usr/bin/env node
/**
 * One PR-watch cycle: list open PRs (oldest first), audit merge gates per PR.
 * Agents loop `npm run pr:watch-once` or use --watch for idle polling.
 *
 * Exit 0 — no open PRs (idle), or all listed PRs pass pr:gates:check.
 * Exit 1 — gh/config error.
 * Exit 2 — one or more open PRs with failing gates (work remains).
 *
 * Usage:
 *   npm run pr:watch-once
 *   npm run pr:watch-once -- --pr 91
 *   npm run pr:watch-once -- --json
 *   npm run pr:watch-once -- --watch --idle-min 5
 */
import { setTimeout as sleepMs } from 'node:timers/promises';
import { evaluateGates } from './lib/pr-gates-lib.mjs';
import { hasGh, ghJson } from './lib/gh-pr-review-threads.mjs';

const DEFAULT_IDLE_MIN = 5;
const MAX_IDLE_MIN = 120;
const POLL_SEC = 60;
const OPEN_PR_PAGE_SIZE = 100;
const GH_TIMEOUT_MS = 120_000;
const GH_MAX_BUFFER = 4 * 1024 * 1024;

/** Human-readable status: stderr when --json so stdout stays pure JSON. */
function status(msg, { json, quiet }) {
  if (quiet) return;
  if (json) console.error(msg);
  else console.log(msg);
}

function parseArgs(argv) {
  const out = {
    pr: null,
    json: false,
    quiet: false,
    watch: false,
    idleMin: DEFAULT_IDLE_MIN,
    help: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--json') out.json = true;
    else if (a === '--quiet' || a === '-q') out.quiet = true;
    else if (a === '--watch' || a === '-w') out.watch = true;
    else if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a.startsWith('--pr=')) out.pr = Number(a.slice(5));
    else if (a === '--idle-min' && argv[i + 1]) {
      out.idleMin = Math.min(Math.max(1, Number(argv[++i]) || DEFAULT_IDLE_MIN), MAX_IDLE_MIN);
    } else if (a.startsWith('--idle-min=')) {
      out.idleMin = Math.min(Math.max(1, Number(a.slice(11)) || DEFAULT_IDLE_MIN), MAX_IDLE_MIN);
    }
  }
  if (out.pr != null && (!Number.isInteger(out.pr) || out.pr <= 0)) {
    out.prError = 'invalid --pr (positive integer required)';
  }
  return out;
}

function listOpenPrs() {
  const rows = [];
  for (let page = 1; page < 1000; page += 1) {
    const batch = ghJson([
      'pr',
      'list',
      '--state',
      'open',
      '--limit',
      String(OPEN_PR_PAGE_SIZE),
      '--page',
      String(page),
      '--json',
      'number,title,headRefName,createdAt,mergeable,mergeStateStatus',
    ]);
    if (!Array.isArray(batch) || !batch.length) break;
    rows.push(...batch);
    if (batch.length < OPEN_PR_PAGE_SIZE) break;
  }
  return rows.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));
}

function conflictHint(pr) {
  const ms = pr.mergeStateStatus;
  const m = pr.mergeable;
  if (ms === 'DIRTY' || m === 'CONFLICTING') {
    return 'merge conflict — rebase onto origin/main before gates can pass';
  }
  if (ms === 'BEHIND') return 'branch behind base — rebase origin/main';
  return null;
}

function auditPr(prNumber, { quiet, json }) {
  const result = evaluateGates(prNumber, { skipFeedbackPlan: false });
  const failed = result.gates.filter((g) => !g.pass);
  if (!quiet) {
    if (result.pass) {
      status(`  PR #${prNumber}: all merge gates passed`, { json, quiet: false });
    } else {
      console.error(`  PR #${prNumber}: ${failed.length} gate(s) failing`);
      for (const g of failed) {
        console.error(`    [${g.id}] ${g.detail}`);
        if (g.action) console.error(`      → ${g.action}`);
      }
    }
  }
  return result;
}

async function runCycle(args) {
  let prs;
  if (args.pr) {
    const view = ghJson([
      'pr',
      'view',
      String(args.pr),
      '--json',
      'number,title,headRefName,createdAt,state,mergeable,mergeStateStatus',
    ]);
    if (view.state !== 'OPEN') {
      return { idle: false, prs: [], results: [], error: `PR #${args.pr} is not open (state=${view.state})` };
    }
    prs = [view];
  } else {
    prs = listOpenPrs();
  }

  if (prs.length === 0) {
    return { idle: true, prs: [], results: [] };
  }

  const results = [];
  for (const pr of prs) {
    const hint = conflictHint(pr);
    if (hint && !args.quiet) {
      console.error(`  PR #${pr.number} (${pr.headRefName}): ${hint}`);
    }
    const gateResult = auditPr(pr.number, { quiet: args.quiet, json: args.json });
    results.push({
      number: pr.number,
      title: pr.title,
      headRefName: pr.headRefName,
      createdAt: pr.createdAt,
      mergeable: pr.mergeable,
      mergeStateStatus: pr.mergeStateStatus,
      conflictHint: hint,
      gatesPass: gateResult.pass,
      gates: gateResult.gates,
    });
  }

  const allPass = results.every((r) => r.gatesPass);
  return { idle: false, prs, results, allPass };
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: npm run pr:watch-once -- [--pr N] [--json] [--quiet] [--watch] [--idle-min M]

One cycle for pr-watch-agent:
  - Lists open PRs on the current repo (oldest createdAt first, paginated)
  - Runs pr:gates:check logic per PR via evaluateGates()

Exit codes:
  0  idle (no open PRs) OR every audited PR passes all gates
  1  gh missing or invalid --pr
  2  at least one open PR has failing gates

Watch mode (--watch): when idle, sleep --idle-min minutes and re-scan; Ctrl+C to stop.
Delegate remediation to pr-fix-agent; merge/deploy per .cursor/skills/pr-watch-agent/SKILL.md`);
    process.exit(0);
  }

  if (!hasGh()) {
    console.error('pr:watch-once: gh CLI not found — install and gh auth login');
    process.exit(1);
  }
  if (args.prError) {
    console.error(`pr:watch-once: ${args.prError}`);
    process.exit(1);
  }

  const emitJson = (payload) => {
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
  };

  const run = async () => {
    const cycle = await runCycle(args);
    if (cycle.error) {
      console.error(`pr:watch-once: ${cycle.error}`);
      return { exitCode: 1, cycle };
    }

    if (cycle.idle) {
      status('pr:watch-once: idle — no open PRs', args);
      if (args.json) emitJson({ idle: true, prs: [] });
      return { exitCode: 0, cycle };
    }

    status(`pr:watch-once: ${cycle.prs.length} open PR(s), oldest-first order`, args);
    for (const pr of cycle.prs) {
      status(`  #${pr.number} ${pr.headRefName} — ${pr.title}`, args);
    }

    if (args.json) {
      emitJson({
        idle: false,
        allPass: cycle.allPass,
        prs: cycle.results.map((r) => ({
          number: r.number,
          title: r.title,
          headRefName: r.headRefName,
          gatesPass: r.gatesPass,
          conflictHint: r.conflictHint,
          failingGates: r.gates.filter((g) => !g.pass).map((g) => g.id),
        })),
      });
    }

    if (cycle.allPass) {
      status('pr:watch-once: all audited PRs merge-ready (gates exit 0)', args);
      return { exitCode: 0, cycle };
    }

    const failing = cycle.results.filter((r) => !r.gatesPass).map((r) => r.number);
    console.error(`pr:watch-once: PR(s) not merge-ready: ${failing.join(', ')}`);
    console.error('>>> Delegate pr-fix-agent per failing gate; re-run pr:watch-once after fixes');
    return { exitCode: 2, cycle };
  };

  if (!args.watch) {
    const { exitCode } = await run();
    process.exit(exitCode);
  }

  for (;;) {
    const { exitCode, cycle } = await run();
    if (cycle.error) {
      console.error(`pr:watch-once: ${cycle.error}`);
      process.exit(1);
    }
    if (cycle.idle) {
      if (args.pr) {
        console.error(`pr:watch-once: PR #${args.pr} is not open — watch mode stopping`);
        process.exit(1);
      }
      status(`pr:watch-once: sleeping ${args.idleMin} min (idle poll) — Ctrl+C to stop`, args);
      await sleepMs(args.idleMin * 60 * 1000);
      continue;
    }
    if (exitCode === 0) {
      status('pr:watch-once: all gates green — agent may merge/deploy per skill', args);
      process.exit(0);
    }
    status(`pr:watch-once: work remaining (exit 2) — retry in ${POLL_SEC}s or fix and re-run`, args);
    await sleepMs(POLL_SEC * 1000);
  }
}

main().catch((e) => {
  console.error(`pr:watch-once: ${e.message}`);
  process.exit(1);
});
