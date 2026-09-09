/** Validate the repository default base before the explicit merge CLI promotes a draft. */
import { spawnSync } from 'node:child_process';
import { ghJson } from './gh-pr-review-threads.mjs';

export function prepareExplicitCloseout(prNumber, { dryRun = false, read = ghJson,
  run = spawnSync } = {}) {
  if (!Number.isSafeInteger(prNumber) || prNumber <= 0) throw new Error('Invalid PR number');
  const repo = read(['repo', 'view', '--json', 'defaultBranchRef']);
  const meta = read(['pr', 'view', String(prNumber), '--json',
    'number,state,baseRefName,isDraft']);
  const base = repo?.defaultBranchRef?.name;
  if (!base || meta.number !== prNumber || meta.baseRefName !== base) {
    throw new Error('PR does not target the repository default branch');
  }
  if (meta.state === 'MERGED') return { merged: true };
  if (meta.state !== 'OPEN' || typeof meta.isDraft !== 'boolean') {
    throw new Error('PR is not open or its draft state is unavailable');
  }
  if (meta.isDraft && !dryRun) {
    const result = run('gh', ['pr', 'ready', String(prNumber)], {
      encoding: 'utf8', timeout: 120_000,
    });
    if (result.error || result.status !== 0) {
      throw new Error(result.error?.message || result.stderr || 'Draft promotion failed');
    }
  }
  return { merged: false };
}
