#!/usr/bin/env node
/**
 * Self-test for the optimized review-thread gate logic (classifyThreads /
 * isClosureReply). Standalone, no test framework. Run: node scripts/verify-pr-gate-logic.mjs
 *
 * Rules under test (WORKFLOW.md step 6, optimized):
 *  - A RESOLVED thread always passes (resolution is the acknowledgement).
 *  - An UNRESOLVED bot thread passes only with a disposition reply (fixed /
 *    implemented / deferred / declined / by design / "fixed in <sha>" …).
 *  - Low-signal bot threads never block. Unresolved human threads block.
 */
import { classifyThreads, isClosureReply } from './lib/gh-pr-review-threads.mjs';

const BOT = { login: 'gemini-code-assist[bot]', __typename: 'Bot' };
const HUMAN = { login: 'yanniedog', __typename: 'User' };
const T0 = '2026-06-06T00:00:00Z';
const T1 = '2026-06-06T01:00:00Z';

function thread(isResolved, comments) {
  return { isResolved, comments: { nodes: comments } };
}
function c(author, body, createdAt = T0) {
  return { author, body, createdAt };
}

// Substantive bot findings must be >= 40 chars (shorter ones are low-signal noise).
const FINDING = 'high-priority: this dereferences a null pointer when the list is empty';
const cases = [
  ['resolved bot thread, no reply -> pass',
    thread(true, [c(BOT, FINDING)]), 0],
  ['unresolved bot thread, no reply -> 1 violation',
    thread(false, [c(BOT, FINDING)]), 1],
  ['unresolved bot thread + "Fixed in 6f3f466" -> pass',
    thread(false, [c(BOT, FINDING, T0), c(HUMAN, 'Fixed in 6f3f466', T1)]), 0],
  ['unresolved bot thread + "Deferred — follow-up" -> pass',
    thread(false, [c(BOT, FINDING, T0), c(HUMAN, 'Deferred to a follow-up', T1)]), 0],
  ['unresolved bot thread + "Done" -> pass',
    thread(false, [c(BOT, FINDING, T0), c(HUMAN, 'Done', T1)]), 0],
  ['unresolved bot thread + plain "thanks" -> 1 violation',
    thread(false, [c(BOT, FINDING, T0), c(HUMAN, 'thanks', T1)]), 1],
  ['low-signal unresolved bot thread -> pass',
    thread(false, [c(BOT, 'Useful? React with 👍 / 👎')]), 0],
  ['unresolved human thread, no reply -> 1 violation',
    thread(false, [c(HUMAN, 'please change this blocking thing in the parser now')]), 1],
  ['bot self-addressed "fixed in <sha>" unresolved -> pass',
    thread(false, [c(BOT, FINDING, T0), c(BOT, 'fixed in abc1234', T1)]), 0],
];

const failures = [];
for (const [name, t, expected] of cases) {
  const got = classifyThreads([t]).length;
  if (got !== expected) failures.push(`${name}: got ${got} violations, expected ${expected}`);
}

// isClosureReply phrasing coverage
for (const [body, want] of [
  ['Fixed in abc123', true], ['Addressed', true], ['Implemented', true],
  ['Resolved', true], ['Declined — by design', true], ['Deferred', true],
  ['done', true], ["won't fix", true], ['not applicable', true],
  ['thanks', false], ['ok', false], ['', false],
]) {
  if (isClosureReply(body) !== want) failures.push(`isClosureReply(${body!=='' ? body : '<empty>'}) !== ${want}`);
}

if (failures.length) {
  console.error('FAIL verify-pr-gate-logic:');
  for (const f of failures) console.error('  -', f);
  process.exit(1);
}
console.log(`PASS verify-pr-gate-logic: ${cases.length} classify cases + closure-phrasing checks`);
