#!/usr/bin/env node
/**
 * Update a PR branch when behind origin/main (WORKFLOW.md step 7 pre-merge).
 */
import {
  enableSquashAutoMerge,
  progressPullRequest,
  updatePrBranch,
} from './lib/pr-branch-sync.mjs';
import { hasGh } from './lib/gh-pr-review-threads.mjs';

function parseArgs(argv) {
  const out = { pr: null, dryRun: false, enableAuto: false, progress: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run') out.dryRun = true;
    else if (a === '--enable-auto') out.enableAuto = true;
    else if (a === '--progress') out.progress = true;
    else if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a.startsWith('--pr=')) out.pr = Number(a.slice(5));
  }
  if (out.pr != null && (!Number.isInteger(out.pr) || out.pr <= 0)) {
    out.prError = 'invalid --pr (positive integer required)';
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: npm run pr:update-branch -- --pr <n> [--enable-auto] [--progress] [--dry-run]`);
    process.exit(0);
  }
  if (!hasGh()) {
    console.error('pr-update-branch: install gh CLI and authenticate (gh auth login)');
    process.exit(1);
  }
  if (args.prError) {
    console.error(`pr-update-branch: ${args.prError}`);
    process.exit(1);
  }
  if (!args.pr) {
    console.error('pr-update-branch: --pr <n> required');
    process.exit(1);
  }

  try {
    if (args.progress || args.enableAuto) {
      const result = progressPullRequest(args.pr, { dryRun: args.dryRun, syncBranch: true, enableAuto: true });
      if (result.sync) console.log(`pr-update-branch: sync ${result.sync.action} — ${result.sync.detail}`);
      if (result.autoMerge) console.log(`pr-update-branch: auto-merge ${result.autoMerge.action} — ${result.autoMerge.detail}`);
      if (result.blocked) {
        if (result.sync?.hint) console.error(`pr-update-branch: ${result.sync.hint}`);
        process.exit(result.sync?.exitCode === 2 ? 2 : 1);
      }
      process.exit(result.ok ? 0 : 1);
    }

    const sync = updatePrBranch(args.pr, { dryRun: args.dryRun });
    console.log(`pr-update-branch: ${sync.action} — ${sync.detail}`);
    if (sync.hint) console.error(`pr-update-branch: ${sync.hint}`);
    if (!sync.ok) process.exit(sync.exitCode === 2 ? 2 : 1);

    if (args.enableAuto) {
      const auto = enableSquashAutoMerge(args.pr, { dryRun: args.dryRun });
      console.log(`pr-update-branch: auto-merge ${auto.action} — ${auto.detail}`);
      if (!auto.ok) process.exit(auto.exitCode || 1);
    }
    process.exit(0);
  } catch (e) {
    console.error(`pr-update-branch: ${e.message}`);
    process.exit(1);
  }
}

main();
