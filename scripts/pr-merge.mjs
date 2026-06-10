#!/usr/bin/env node
/**
 * Merge a PR using the repo default: squash auto-merge + delete branch.
 *
 * Run only after pr:gates:check exit 0 (WORKFLOW.md steps 5–7).
 *
 * Usage:
 *   npm run pr:merge -- --pr <n>
 *   npm run pr:merge -- --pr <n> --dry-run
 */
import { mergePullRequest, mergeCommandLine, PR_MERGE_FLAGS } from './lib/pr-merge.mjs';
import { hasGh } from './lib/gh-pr-review-threads.mjs';

function parseArgs(argv) {
  const out = { pr: null, dryRun: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run') out.dryRun = true;
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
    console.log(`Usage: npm run pr:merge -- --pr <n> [--dry-run]

Default merge: ${mergeCommandLine('<n>')}

Flags: ${PR_MERGE_FLAGS.join(' ')}
Requires gates green (npm run pr:gates:check -- --pr <n>).`);
    process.exit(0);
  }
  if (!hasGh()) {
    console.error('pr-merge: install gh CLI and authenticate (gh auth login)');
    process.exit(1);
  }
  if (args.prError) {
    console.error(`pr-merge: ${args.prError}`);
    process.exit(1);
  }
  if (!args.pr) {
    console.error('pr-merge: --pr <n> required');
    process.exit(1);
  }

  const result = mergePullRequest(args.pr, { dryRun: args.dryRun });
  if (args.dryRun) {
    console.log(result.stdout);
    process.exit(0);
  }
  if (result.ok) {
    if (result.stdout) console.log(result.stdout);
    console.log(`pr-merge: enabled squash auto-merge for PR #${args.pr}`);
    process.exit(0);
  }
  console.error(`pr-merge: gh failed (exit ${result.exitCode})`);
  if (result.stderr) console.error(result.stderr);
  process.exit(result.exitCode || 1);
}

main();
