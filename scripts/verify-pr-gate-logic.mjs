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
import {
  isMatrixCommitTitle,
  isReportsOnlyFileList,
  isReportsOnlyPath,
} from './lib/pr-reports-only.mjs';
import {
  isAutoReleaseBumpTitle,
  isAutoReleaseCommitOnly,
  isAutoReleaseCommitPath,
} from './lib/pr-mobile-auto-release-commit.mjs';
import {
  gateExemptReasonFromPrMeta,
  gateExemptReasonFromTitle,
  isBotPrAuthor,
  isChorePrTitle,
  isGateExemptFileList,
} from './lib/pr-gate-exempt.mjs';

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
  // LIVE gate: an unresolved thread fails even WITH a disposition reply, because
  // required_conversation_resolution means it must actually be resolved to merge.
  ['unresolved bot thread + "Fixed in 6f3f466" -> still 1 (must resolve)',
    thread(false, [c(BOT, FINDING, T0), c(HUMAN, 'Fixed in 6f3f466', T1)]), 1],
  ['unresolved bot thread + "Deferred" -> still 1 (must resolve)',
    thread(false, [c(BOT, FINDING, T0), c(HUMAN, 'Deferred to a follow-up', T1)]), 1],
  ['low-signal unresolved bot thread -> pass',
    thread(false, [c(BOT, 'Useful? React with 👍 / 👎')]), 0],
  ['unresolved human thread, no reply -> 1 violation',
    thread(false, [c(HUMAN, 'please change this blocking thing in the parser now')]), 1],
];

// mergedAudit is lenient: a historical PR with a disposition reply (but not
// resolved) is acceptable; plain "thanks" is not.
const auditCases = [
  ['[audit] unresolved bot + "Fixed in <sha>" -> pass',
    thread(false, [c(BOT, FINDING, T0), c(HUMAN, 'Fixed in abc1234', T1)]), 0],
  ['[audit] unresolved bot + "thanks" -> 1 violation',
    thread(false, [c(BOT, FINDING, T0), c(HUMAN, 'thanks', T1)]), 1],
  ['[audit] resolved bot -> pass',
    thread(true, [c(BOT, FINDING)]), 0],
];

const failures = [];
for (const [name, t, expected] of cases) {
  const got = classifyThreads([t]).length;
  if (got !== expected) failures.push(`${name}: got ${got} violations, expected ${expected}`);
}
for (const [name, t, expected] of auditCases) {
  const got = classifyThreads([t], { mergedAudit: true }).length;
  if (got !== expected) failures.push(`${name}: got ${got} violations, expected ${expected}`);
}

// isClosureReply phrasing coverage — incl. negation rejection (Gemini PR #148).
for (const [body, want] of [
  ['Fixed in abc123', true], ['Addressed', true], ['Implemented', true],
  ['Resolved', true], ['Declined — by design', true], ['Deferred', true],
  ['done', true], ["won't fix", true], ['not applicable', true], ['this is not a bug', true],
  ['not fixed', false], ['not done yet', false], ["isn't resolved", false],
  ['this was never addressed', false], ['still not implemented', false],
  ['thanks', false], ['ok', false], ['', false],
]) {
  if (isClosureReply(body) !== want) failures.push(`isClosureReply(${body !== '' ? body : '<empty>'}) !== ${want}`);
}

for (const [path, want] of [
  ['reports/pr-bot-matrix.md', true],
  ['reports/pr-bot-matrix.html', true],
  ['reports/foo.json', true],
  ['scripts/foo.mjs', false],
  ['', false],
]) {
  if (isReportsOnlyPath(path) !== want) {
    failures.push(`isReportsOnlyPath(${path || '<empty>'}) !== ${want}`);
  }
}
for (const [name, files, want] of [
  ['matrix md+html+json only', ['reports/pr-bot-matrix.md', 'reports/pr-bot-matrix.html', 'reports/pr-bot-matrix.json'], true],
  ['matrix html+json only', ['reports/pr-bot-matrix.html', 'reports/pr-bot-matrix.json'], true],
  ['empty list', [], false],
  ['mixed reports+scripts', ['reports/a.html', 'scripts/b.mjs'], false],
  ['non-reports only', ['docs/PR_BOT_MATRIX.md'], false],
]) {
  if (isReportsOnlyFileList(files) !== want) {
    failures.push(`${name}: isReportsOnlyFileList !== ${want}`);
  }
}

for (const [path, want] of [['mobile/app.json', true], ['mobile/changelog/versions/1.0.8.json', true], ['mobile/package.json', false]]) {
  if (isAutoReleaseCommitPath(path) !== want) failures.push(`isAutoReleaseCommitPath(${path}) !== ${want}`);
}
for (const [name, files, want] of [
  ['auto-release only', ['mobile/app.json', 'mobile/changelog/manifest.json'], true],
  ['gate exempt auto-release', ['mobile/app.json', 'mobile/changelog/manifest.json'], true],
]) {
  const fn = name.startsWith('gate exempt') ? isGateExemptFileList : isAutoReleaseCommitOnly;
  if (fn(files) !== want) failures.push(`${name}: ${fn.name} !== ${want}`);
}

for (const [title, want] of [
  ['chore(mobile): auto-release bump to v1.0.13 (after c1f0e31)', true],
  ['chore(mobile): auto-release bump to v1.0.8 (after b481ace)', true],
  ['feat(mobile): new screen', false],
]) {
  if (isAutoReleaseBumpTitle(title) !== want) {
    failures.push(`isAutoReleaseBumpTitle(${title}) !== ${want}`);
  }
}
for (const [title, want] of [
  ['chore: update PR bot feedback matrix', true],
  ['chore: ignore local worktrees', true],
  ['feat(mobile): new screen', false],
  ['fix(dashboard): ING code', false],
]) {
  if (isChorePrTitle(title) !== want) failures.push(`isChorePrTitle(${title}) !== ${want}`);
}
if (!isMatrixCommitTitle('chore: update PR bot feedback matrix')) {
  failures.push('isMatrixCommitTitle(matrix title) !== true');
}
if (gateExemptReasonFromTitle('chore(mobile): auto-release bump to v1.0.13 (after c1f0e31)') !== 'mobile-auto-release') {
  failures.push('gateExemptReasonFromTitle(auto-release) !== mobile-auto-release');
}
if (gateExemptReasonFromTitle('chore: update PR bot feedback matrix') !== 'reports') {
  failures.push('gateExemptReasonFromTitle(matrix) !== reports');
}

for (const [author, want] of [
  [{ login: 'github-actions[bot]', type: 'Bot' }, true],
  [{ login: 'dependabot[bot]', __typename: 'Bot' }, true],
  [{ login: 'yanniedog', type: 'User' }, false],
  ['sourcery-ai[bot]', true],
]) {
  if (isBotPrAuthor(author) !== want) failures.push(`isBotPrAuthor(${JSON.stringify(author)}) !== ${want}`);
}

for (const [meta, want] of [
  [{ title: 'feat: dashboard fix', authorLogin: 'yanniedog', authorType: 'User' }, null],
  [{ title: 'chore: tidy scripts', authorLogin: 'yanniedog', authorType: 'User' }, 'chore'],
  [{ title: 'feat: from actions', authorLogin: 'github-actions[bot]', authorType: 'Bot' }, 'bot-authored'],
  [{ title: 'chore(mobile): auto-release bump to v1.0.13 (after c1f0e31)', authorLogin: 'github-actions[bot]', authorType: 'Bot' }, 'bot-authored'],
  [{ title: 'agent/foo-bar', authorLogin: 'yanniedog', authorType: 'User' }, null],
]) {
  const got = gateExemptReasonFromPrMeta(meta);
  if (got !== want) failures.push(`gateExemptReasonFromPrMeta(${JSON.stringify(meta)}) got ${got}, want ${want}`);
}

if (failures.length) {
  console.error('FAIL verify-pr-gate-logic:');
  for (const f of failures) console.error('  -', f);
  process.exit(1);
}
console.log(
  `PASS verify-pr-gate-logic: ${cases.length} live + ${auditCases.length} audit + title-exempt checks`,
);
