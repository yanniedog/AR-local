/**
 * Canonical PR merge flags for AR-local ship bar (WORKFLOW.md step 7).
 * Squash + auto-merge + delete branch is the default for all automation.
 */
import { spawnSync } from 'node:child_process';
import { readMergeCi } from './pr-ci-readiness.mjs';

/** gh pr merge flags used by agents, pr-watch, and CI workflows. */
export const PR_MERGE_FLAGS = ['--auto', '--squash', '--delete-branch'];

const GH_TIMEOUT_MS = 120_000;

/**
 * @param {number} prNumber
 * @param {{ dryRun?: boolean, extraArgs?: string[] }} [opts]
 * @returns {{ ok: boolean, stdout: string, stderr: string, exitCode: number }}
 */
export function mergePullRequest(prNumber, opts = {}) {
  const { dryRun = false, extraArgs = [], readCi = readMergeCi, run = spawnSync } = opts;
  if (extraArgs.some((arg) => /^--(?:admin|match-head-commit|merge|rebase)(?:=|$)/.test(arg))) {
    return { ok: false, stdout: '', stderr: 'Merge safety flags cannot be overridden', exitCode: 1 };
  }
  const ci = readCi(prNumber);
  if (!ci.ok || ci.failed || ci.pending || !/^[0-9a-f]{40}$/.test(ci.headSha || '')) {
    const detail = ci.error || (ci.failed ? `CI failed: ${(ci.failedNames || []).join(', ')}` :
      `CI pending: ${(ci.pendingNames || []).join(', ') || 'verified current head unavailable'}`);
    return { ok: false, stdout: '', stderr: detail, exitCode: ci.ok && !ci.failed && ci.pending ? 2 : 1 };
  }
  const args = ['pr', 'merge', String(prNumber), ...PR_MERGE_FLAGS, '--match-head-commit', ci.headSha, ...extraArgs];
  if (dryRun) {
    return { ok: true, stdout: `gh ${args.join(' ')}`, stderr: '', exitCode: 0 };
  }
  const r = run('gh', args, { encoding: 'utf8', timeout: GH_TIMEOUT_MS });
  if (r.error?.code === 'ETIMEDOUT') {
    return {
      ok: false,
      stdout: '',
      stderr: `gh timed out after ${GH_TIMEOUT_MS}ms`,
      exitCode: 1,
    };
  }
  if (r.error) {
    return {
      ok: false,
      stdout: '',
      stderr: r.error.message,
      exitCode: 1,
    };
  }
  return {
    ok: r.status === 0,
    stdout: (r.stdout || '').trim(),
    stderr: (r.stderr || '').trim(),
    exitCode: r.status ?? 1,
  };
}

/** Human/agent one-liner (documented in skills and WORKFLOW.md). */
export function mergeCommandLine(prNumber) {
  return `gh pr merge ${prNumber} ${PR_MERGE_FLAGS.join(' ')}`;
}
