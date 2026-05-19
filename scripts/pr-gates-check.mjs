#!/usr/bin/env node
/**
 * Aggregate PR merge gates (WORKFLOW.md steps 4–7).
 * Exit 0 only when all gates pass; exit 1 with actionable checklist.
 *
 * Usage:
 *   npm run pr:gates:check -- --pr <n>
 *   npm run pr:gates:check              # open PR for current branch
 *   npm run pr:gates:check -- --watch   # poll until pass or timeout
 */
import { setTimeout as sleepMs } from 'node:timers/promises';
import {
  evaluateGates,
  normalizePositiveNumber,
  parseGateArgs,
  resolvePrNumber,
} from './lib/pr-gates-lib.mjs';

const POLL_SEC = normalizePositiveNumber(process.env.PR_GATES_POLL_SEC, 45, 600);

function printReport(result, { quiet = false } = {}) {
  const failed = result.gates.filter((g) => !g.pass);
  if (result.pass) {
    if (!quiet) {
      console.log(`pr:gates:check: PR #${result.prNumber} — all merge gates passed`);
      for (const g of result.gates) {
        if (g.skipped || g.waived) continue;
        console.log(`  [ok] ${g.id}: ${g.detail}`);
      }
    }
    return;
  }
  console.error(`pr:gates:check: PR #${result.prNumber} — ${failed.length} gate(s) failing`);
  console.error('');
  console.error('Checklist (fix in order where dependencies apply):');
  let n = 0;
  for (const g of failed) {
    n += 1;
    console.error(`  ${n}. [${g.id}] ${g.detail}`);
    if (g.action) console.error(`     → ${g.action}`);
  }
  console.error('');
  console.error('Delegate fixes: pr-fix-agent (threads/CI). Re-audit: pr-gates-agent / npm run pr:gates:check');
}

async function main() {
  const args = parseGateArgs(process.argv);
  if (args.prError) {
    console.error(`pr:gates:check: ${args.prError}`);
    process.exit(1);
  }
  if (args.help) {
    console.log(`Usage: npm run pr:gates:check -- [--pr N] [--watch] [--json] [--quiet] [--skip-feedback-plan] [--timeout-min M]

Gates enforced:
  ci-required              Required GitHub checks green (gh pr checks --required)
  github-bot-gates           bot-presence-gate + bot-feedback-gate when reported
  wait-for-bots            npm run wait-for-bots -- --pr N (exit 0)
  pr-bot-feedback-check    npm run pr:bot-feedback-check -- --pr N (exit 0)
  feedback-plan            ## Feedback plan when bot wait ready and threads open
  ship-closeout-subgates   wait + thread gates (ship:closeout:strict embeds these)

Note: ship:closeout:strict exit 0 on a topic branch with an open PR is expected only after merge/close.
Use this script for merge-readiness, not closeout idle detection.`);
    process.exit(0);
  }

  let prMeta;
  try {
    prMeta = resolvePrNumber(args.pr);
  } catch (e) {
    console.error(`pr:gates:check: ${e.message}`);
    process.exit(1);
  }
  if (prMeta.error) {
    console.error(`pr:gates:check: ${prMeta.error}`);
    process.exit(1);
  }

  const prNumber = prMeta.pr.number;
  const deadline = Date.now() + args.timeoutMin * 60 * 1000;

  const runOnce = () =>
    evaluateGates(prNumber, { skipFeedbackPlan: args.skipFeedbackPlan });

  if (!args.watch) {
    const result = runOnce();
    if (args.json) {
      console.log(JSON.stringify({ ...result, title: prMeta.pr.title, headRefName: prMeta.pr.headRefName }, null, 2));
    } else {
      printReport(result, { quiet: args.quiet });
    }
    process.exit(result.pass ? 0 : 1);
  }

  if (!args.quiet) {
    console.log(
      `pr:gates:check: watching PR #${prNumber} (poll ${POLL_SEC}s, timeout ${args.timeoutMin} min)`,
    );
  }

  for (;;) {
    const result = runOnce();
    if (result.pass) {
      if (args.json) console.log(JSON.stringify(result, null, 2));
      else printReport(result, { quiet: args.quiet });
      process.exit(0);
    }
    if (Date.now() >= deadline) {
      if (args.json) console.log(JSON.stringify({ ...result, timedOut: true }, null, 2));
      else {
        console.error(`pr:gates:check: timeout after ${args.timeoutMin} min`);
        printReport(result);
      }
      process.exit(1);
    }
    if (!args.quiet) {
      const pending = result.gates.filter((g) => !g.pass).map((g) => g.id);
      console.log(`pr:gates:check: waiting — pending: ${pending.join(', ')}`);
    }
    await sleepMs(POLL_SEC * 1000);
  }
}

main().catch((err) => {
  console.error(`pr:gates:check: ${err.message}`);
  process.exit(1);
});
