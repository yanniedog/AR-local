#!/usr/bin/env node
/**
 * Guarded legacy wrapper. Prefer pr:arm-and-park, which also classifies
 * actionable work versus GitHub-owned waiting without polling.
 */
import {
  fetchPrMergeMeta,
  progressPullRequest,
  enableSquashAutoMerge,
} from './lib/pr-branch-sync.mjs';
import { checkDefaultBase } from './lib/pr-base-guard.mjs';
import { hasGh } from './lib/gh-pr-review-threads.mjs';

function parseArgs(argv) {
  const out = { pr: null, dryRun: false, enableOnly: false, noSync: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run') out.dryRun = true;
    else if (a === '--enable-only') out.enableOnly = true;
    else if (a === '--no-sync') out.noSync = true;
    else if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a.startsWith('--pr=')) out.pr = Number(a.slice(5));
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: npm run pr:merge -- --pr <n> [--enable-only] [--no-sync] [--dry-run]

Guarded legacy wrapper. Prefer:
  npm run pr:arm-and-park -- --pr <n>`);
    process.exit(0);
  }
  if (!hasGh() || !args.pr) { console.error('pr-merge: gh + --pr required'); process.exit(1); }

  let meta;
  try {
    meta = fetchPrMergeMeta(args.pr);
  } catch (error) {
    console.error(`pr-merge: ${error.message}`);
    process.exit(1);
  }
  const baseGuard = checkDefaultBase(meta.baseRefName);
  if (!baseGuard.covered) {
    console.error(`pr-merge: base-unprotected: ${baseGuard.detail}`);
    process.exit(3);
  }

  if (args.enableOnly) {
    const auto = enableSquashAutoMerge(args.pr, { dryRun: args.dryRun });
    console.log(`auto-merge ${auto.action}: ${auto.detail}`);
    process.exit(auto.ok ? 0 : auto.exitCode || 1);
  }
  const r = progressPullRequest(args.pr, {
    dryRun: args.dryRun,
    syncBranch: !args.noSync,
    enableAuto: true,
    markReady: true,
  });
  if (r.ready) console.log(`ready ${r.ready.action}: ${r.ready.detail}`);
  if (r.sync && !args.noSync) console.log(`sync ${r.sync.action}: ${r.sync.detail}`);
  if (r.autoMerge) console.log(`auto-merge ${r.autoMerge.action}: ${r.autoMerge.detail}`);
  if (r.blocked) process.exit(r.sync?.exitCode === 2 ? 2 : 1);
  process.exit(r.ok ? 0 : 1);
}
main();
