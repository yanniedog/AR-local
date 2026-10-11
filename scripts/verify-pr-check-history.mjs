import assert from 'node:assert/strict';
import { readCheckResult, selectLatestChecks } from './lib/pr-check-history.mjs';
const old = { name: 'bot-feedback-gate', workflow: 'feedback', bucket: 'fail', state: 'FAILURE', startedAt: '2026-10-11T05:15:23Z', completedAt: '2026-10-11T05:18:00Z' };
const newer = { ...old, bucket: 'pass', state: 'SUCCESS', startedAt: '2026-10-11T05:16:03Z', completedAt: '2026-10-11T05:17:00Z' };
for (const rows of [[old, newer], [newer, old]]) {
  assert.deepEqual(selectLatestChecks(rows).checks, [newer]);
  const pending = { ...newer, bucket: 'pending', state: 'IN_PROGRESS', completedAt: '' };
  assert.deepEqual(selectLatestChecks([old, pending]).checks, [pending]);
}
assert.equal(selectLatestChecks([old, { ...newer, workflow: 'independent' }]).checks.length, 2);
assert.equal(selectLatestChecks([{ ...old, appId: 1 }, { ...newer, appId: 2 }]).checks.length, 2);
assert.match(selectLatestChecks([old, { ...newer, startedAt: '' }]).error, /Cannot order/);
assert.match(selectLatestChecks([old, { ...newer, startedAt: old.startedAt }]).error, /Cannot order/);
for (const status of [0, 1, 8]) {
  assert.deepEqual(readCheckResult({ status, stdout: JSON.stringify([old, newer]) }).checks, [old, newer]);
}
assert.ok(readCheckResult({ status: 1, stdout: 'broken' }).error);
assert.ok(readCheckResult({ status: 8, stdout: '[]' }).error);
assert.ok(readCheckResult({ status: 2, stderr: 'auth failed' }).error);
assert.ok(readCheckResult({ status: 0, stdout: '{}' }).error);
assert.deepEqual(readCheckResult({ status: 1, stderr: 'no required checks reported' }).checks, []);
console.log('PR check history regression tests passed');
