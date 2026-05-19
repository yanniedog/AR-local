#!/usr/bin/env node
import { execSync } from 'node:child_process';
import { resolveRequiredKeys } from './lib/bot-wait-config.mjs';
import { checkRequiredBotsOnPr } from './lib/bot-wait-presence.mjs';
import {
  classifyThreads,
  fetchPullRequestThreads,
  hasGh,
  repoSlug,
} from './lib/gh-pr-review-threads.mjs';

function sh(cmd) {
  try {
    return execSync(cmd, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  } catch (e) {
    return (e.stdout || e.stderr || '').trim();
  }
}

function parseArgs(argv) {
  const out = {
    pr: null,
    auditMerged: false,
    limit: 20,
    json: false,
    quiet: false,
    skipBotPresence: false,
    requireBots: null,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a === '--audit-merged') out.auditMerged = true;
    else if (a === '--limit' && argv[i + 1]) out.limit = Number(argv[++i]);
    else if (a === '--json') out.json = true;
    else if (a === '--quiet') out.quiet = true;
    else if (a === '--skip-bot-presence') out.skipBotPresence = true;
    else if (a === '--require-bots' && argv[i + 1]) {
      out.requireBots = argv[++i].split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
    } else if (a.startsWith('--require-bots=')) {
      out.requireBots = a
        .slice('--require-bots='.length)
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
    } else if (a === '--help' || a === '-h') out.help = true;
  }
  return out;
}

function prForBranch(branch) {
  const json = sh(`gh pr list --state open --head ${branch} --json number --jq ".[0].number"`);
  const n = Number(json);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function mergedPrs(limit) {
  const raw = sh(`gh pr list --state merged --limit ${limit} --json number,title,mergedAt`);
  return raw ? JSON.parse(raw) : [];
}

function checkOne(owner, name, prNumber, { mergedAudit = false } = {}) {
  const pr = fetchPullRequestThreads(owner, name, prNumber);
  return {
    number: pr.number,
    title: pr.title,
    state: pr.state,
    merged: pr.merged,
    mergedAt: pr.mergedAt,
    threadCount: pr.threads.length,
    violations: classifyThreads(pr.threads, { mergedAudit }),
  };
}

function printViolations(result) {
  if (!result.violations.length) return;
  console.error(`PR #${result.number} (${result.title}): ${result.violations.length} thread issue(s)`);
  for (const v of result.violations) {
    console.error(
      `  - thread ${v.threadIndex} [${v.kind}] @${v.starter}: ${v.excerpt}${v.excerpt.length >= 120 ? '…' : ''}`,
    );
  }
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(
      'Usage: node scripts/pr-bot-feedback-check.mjs [--pr N] [--audit-merged] [--limit N] [--json] [--skip-bot-presence] [--require-bots gemini,codex,sourcery]',
    );
    process.exit(0);
  }
  if (!hasGh()) {
    console.error('pr-bot-feedback-check: install gh CLI and authenticate (gh auth login)');
    process.exit(1);
  }

  const { owner, name } = repoSlug();

  if (args.auditMerged) {
    const prs = args.pr ? [{ number: args.pr }] : mergedPrs(args.limit);
    const report = prs.map((row) => checkOne(owner, name, row.number, { mergedAudit: true }));
    let anyViolations = false;
    for (const result of report) {
      if (result.violations.length) {
        anyViolations = true;
        if (!args.json) printViolations(result);
      }
    }
    if (args.json) console.log(JSON.stringify(report, null, 2));
    else {
      const clean = report.filter((r) => !r.violations.length).length;
      console.log(
        `Merged PR audit: ${report.length} checked, ${clean} clean, ${report.length - clean} with thread gaps`,
      );
    }
    process.exit(anyViolations ? 1 : 0);
  }

  let prNumber = args.pr;
  if (!prNumber) {
    const branch = sh('git rev-parse --abbrev-ref HEAD');
    if (!branch || branch === 'main') {
      if (!args.quiet) console.log('pr-bot-feedback-check: on main with no --pr; skip');
      process.exit(0);
    }
    prNumber = prForBranch(branch);
    if (!prNumber) {
      if (!args.quiet) console.log(`pr-bot-feedback-check: no open PR for branch ${branch}; skip`);
      process.exit(0);
    }
  }

  let botPresence = null;
  if (!args.skipBotPresence) {
    const requiredKeys = resolveRequiredKeys(args.requireBots);
    try {
      botPresence = checkRequiredBotsOnPr(owner, name, prNumber, { requiredKeys });
    } catch (e) {
      console.error(`pr-bot-feedback-check: bot presence check failed: ${e.message}`);
      process.exit(1);
    }
    if (!botPresence.ok) {
      console.error(
        `pr-bot-feedback-check: merge blocked — required bot(s) have not posted on PR #${prNumber}: ${botPresence.missing.join(', ')}`,
      );
      console.error(`  Expected: ${botPresence.detail}`);
      console.error(`  Seen since anchor: ${botPresence.botsSeen.join(', ') || '(none)'}`);
      console.error('  Run: npm run wait-for-bots -- --pr', prNumber, 'until exit 0 before merge.');
      process.exit(1);
    }
  }

  const result = checkOne(owner, name, prNumber);
  if (args.json) {
    console.log(JSON.stringify({ ...result, botPresence }, null, 2));
  } else if (result.violations.length) {
    printViolations(result);
    console.error(
      'pr-bot-feedback-check: merge blocked — resolve threads or reply in-thread (implemented / deferred / declined) per WORKFLOW.md step 6',
    );
  } else {
    console.log(
      `PR #${result.number}: bot feedback gate passed (${result.threadCount} review thread(s) checked)`,
    );
  }
  process.exit(result.violations.length ? 1 : 0);
}

main();
