#!/usr/bin/env node
/**
 * Self-test for canonical PR merge flags. Run: node scripts/verify-pr-merge.mjs
 */
import { PR_MERGE_FLAGS, mergeCommandLine } from './lib/pr-merge.mjs';

let failed = 0;

function assert(cond, msg) {
  if (!cond) {
    console.error(`FAIL: ${msg}`);
    failed += 1;
  }
}

assert(PR_MERGE_FLAGS.includes('--auto'), '--auto in PR_MERGE_FLAGS');
assert(PR_MERGE_FLAGS.includes('--squash'), '--squash in PR_MERGE_FLAGS');
assert(PR_MERGE_FLAGS.includes('--delete-branch'), '--delete-branch in PR_MERGE_FLAGS');
assert(
  mergeCommandLine(42) === 'gh pr merge 42 --auto --squash --delete-branch',
  'mergeCommandLine canonical form',
);

if (failed) {
  console.error(`verify-pr-merge: ${failed} failure(s)`);
  process.exit(1);
}
console.log('verify-pr-merge: pass');
