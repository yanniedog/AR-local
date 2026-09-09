#!/usr/bin/env node
/**
 * Self-test for canonical PR merge flags. Run: node scripts/verify-pr-merge.mjs
 */
import { PR_MERGE_FLAGS, mergeCommandLine } from './lib/pr-merge.mjs';
import { strict as check } from 'node:assert';
import { prepareExplicitCloseout } from './lib/pr-closeout-guard.mjs';

function fixture(overrides = {}) {
  const calls = [];
  return {
    calls,
    read: (args) => args[0] === 'repo' ? { defaultBranchRef: { name: 'release' } } :
      { number: 42, state: 'OPEN', baseRefName: 'release', isDraft: true, ...overrides },
    run: (...args) => { calls.push(args); return { status: 0 }; },
  };
}
for (const overrides of [{ baseRefName: 'main' }, { state: 'CLOSED' },
  { number: 43 }, { isDraft: null }]) {
  const f = fixture(overrides);
  check.throws(() => prepareExplicitCloseout(42, f));
  check.equal(f.calls.length, 0);
}
const missingBase = fixture();
check.throws(() => prepareExplicitCloseout(42, { ...missingBase, read: () => ({}) }));
check.equal(missingBase.calls.length, 0);
for (const options of [{ dryRun: true }, { isDraft: false }, { state: 'MERGED' }]) {
  const f = fixture(options);
  prepareExplicitCloseout(42, { ...f, dryRun: options.dryRun });
  check.equal(f.calls.length, 0);
}
const f = fixture();
prepareExplicitCloseout(42, f);
check.equal(f.calls.length, 1);
check.deepEqual(f.calls[0].slice(0, 2), ['gh', ['pr', 'ready', '42']]);
check.throws(() => prepareExplicitCloseout(42, {
  ...fixture(), run: () => ({ status: 1, stderr: 'denied' }),
}), /denied/);

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
