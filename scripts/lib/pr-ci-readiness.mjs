/** Local closeout must satisfy applicable CI as well as GitHub-required checks. */
import { spawnSync } from 'node:child_process';
import { ghJson } from './gh-pr-review-threads.mjs';
import { readCheckResult, selectLatestChecks } from './pr-check-history.mjs';
import { readProductCi, readApiPages, githubApi } from './pr-product-ci.mjs';

/** Custom reporter checks have no workflow/job identity in gh pr checks JSON. */
export function readUniversalCheck(prNumber, { repository, headSha, api = githubApi } = {}) {
  if (!Number.isSafeInteger(prNumber) || prNumber <= 0 ||
      !/^[\w.-]+\/[\w.-]+$/.test(repository || '') || !/^[0-9a-f]{40}$/.test(headSha || '')) {
    throw new Error('Current repository/head unavailable for required check verification');
  }
  const rows = readApiPages(api, `repos/${repository}/commits/${headSha}/check-runs?check_name=bot-feedback-gate&filter=all`, 'check_runs');
  const trusted = rows.filter((check) => check.name === 'bot-feedback-gate' && check.head_sha === headSha &&
    check.app?.id === 15368 && check.app?.slug === 'github-actions' &&
    check.external_id === `ar-local-required:${prNumber}:${headSha}`);
  if (trusted.some((check) => !Number.isSafeInteger(check.id))) throw new Error('Required check has invalid identity');
  const latest = trusted.sort((a, b) => b.id - a.id)[0];
  return { name: 'bot-feedback-gate', appId: 15368, id: latest?.id,
    bucket: !latest || latest.status !== 'completed' ? 'pending' : latest.conclusion === 'success' ? 'pass' : 'fail',
    state: latest?.conclusion || latest?.status || 'PENDING', link: latest?.details_url,
    startedAt: latest?.started_at, completedAt: latest?.completed_at };
}

export function readRequiredCi(prNumber, { ignoredNames = [], run = spawnSync, ...options } = {}) {
  const result = readCheckResult(run('gh', ['pr', 'checks', String(prNumber), '--required', '--json',
    'name,bucket,state,startedAt,completedAt,workflow,link'], { encoding: 'utf8', timeout: 120_000 }));
  if (result.error) return { ok: false, error: result.error };
  const ignored = new Set(ignoredNames.map((name) => name.toLowerCase()));
  const latest = selectLatestChecks(result.checks.filter((check) => {
    const name = String(check.name || '').toLowerCase();
    const tail = name.slice(name.lastIndexOf('/') + 1).trim();
    return tail !== 'bot-feedback-gate' && !ignored.has(name) && !ignored.has(tail);
  }));
  if (latest.error) return { ok: false, error: latest.error };
  const checks = latest.checks;
  // gh --required omits unreported contexts and loses custom-check app identity.
  if (!ignored.has('bot-feedback-gate')) {
    try { checks.push(readUniversalCheck(prNumber, options)); }
    catch (error) { return { ok: false, error: error.message }; }
  }
  const pendingNames = checks.filter((check) => check.bucket === 'pending').map((check) => check.name);
  const failedNames = checks.filter((check) => !['pass', 'pending'].includes(check.bucket)).map((check) => check.name);
  return { ok: true, pending: pendingNames.length > 0, failed: failedNames.length > 0, pendingNames, failedNames, checks };
}

export function readMergeCi(prNumber, { readProduct = readProductCi, read = ghJson, ...options } = {}) {
  const product = readProduct(prNumber, options);
  if (!product.ok) return product;
  const required = readRequiredCi(prNumber, { ...options, repository: product.repository, headSha: product.headSha });
  if (!required.ok) return { ...required, headSha: product.headSha };
  try {
    const current = read(['pr', 'view', String(prNumber), '--json', 'number,state,headRefOid,baseRefOid,baseRefName']);
    if (current.number !== prNumber || current.state !== 'OPEN' || current.headRefOid !== product.headSha ||
        current.baseRefOid !== product.baseSha || current.baseRefName !== product.baseRef) {
      return { ok: true, headSha: product.headSha, pending: true, failed: false,
        pendingNames: ['PR head/base changed during CI read'], failedNames: [], checks: [] };
    }
    return { ...product, pending: product.pending || required.pending, failed: product.failed || required.failed,
      pendingNames: [...product.pendingNames, ...required.pendingNames],
      failedNames: [...product.failedNames, ...required.failedNames], checks: [...product.checks, ...required.checks] };
  } catch (error) {
    return { ok: false, headSha: product.headSha, error: error.message };
  }
}
