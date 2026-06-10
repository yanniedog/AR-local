#!/usr/bin/env node
import { progressPullRequest } from './lib/pr-branch-sync.mjs';
import { hasGh } from './lib/gh-pr-review-threads.mjs';

function parseArgs(argv) {
  const out = { pr: null, dryRun: false, enableOnly: false, noSync: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--dry-run') out.dryRun = true;
    else if (a === '--enable-only') out.enableOnly = true;
    else if (a === '--no-sync') out.noSync = true;
    else if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a.startsWith('--pr=')) out.pr = Number(a.slice(5));
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv);
  if (!hasGh() || !args.pr) { console.error('pr-merge: gh + --pr required'); process.exit(1); }
  const r = progressPullRequest(args.pr, { dryRun: args.dryRun, syncBranch: !args.noSync, enableAuto: true });
  if (r.sync && !args.noSync) console.log(`sync ${r.sync.action}: ${r.sync.detail}`);
  if (r.autoMerge) console.log(`auto-merge ${r.autoMerge.action}: ${r.autoMerge.detail}`);
  if (r.blocked) process.exit(r.sync?.exitCode === 2 ? 2 : 1);
  process.exit(r.ok ? 0 : 1);
}
main();
