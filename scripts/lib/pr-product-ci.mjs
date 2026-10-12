/** Read-only, exact-head product CI shared by the required gate and local closeout. */
import { ghJson, repoSlug } from './gh-pr-review-threads.mjs';
import { getApplicableProductCi } from './pr-product-ci-policy.mjs';
export { PRODUCT_CI_WORKFLOWS, getApplicableProductCi } from './pr-product-ci-policy.mjs';

export const githubApi = (endpoint) => ghJson(['api', endpoint]);
const SHA = /^[0-9a-f]{40}$/;

export function readApiPages(api, endpoint, key, { maxPages = 100 } = {}) {
  const rows = [];
  for (let page = 1; page <= maxPages; page += 1) {
    const body = api(`${endpoint}${endpoint.includes('?') ? '&' : '?'}per_page=100&page=${page}`);
    const values = key ? body?.[key] : body;
    if (!Array.isArray(values)) throw new Error(`Invalid paginated response: ${endpoint}`);
    rows.push(...values);
    if (values.length < 100) {
      if (Number.isInteger(body?.total_count) && rows.length < body.total_count) {
        throw new Error(`Incomplete paginated response: ${endpoint}`);
      }
      return rows;
    }
  }
  throw new Error(`Pagination limit exceeded: ${endpoint}`);
}

export function productPrIdentity(pr) {
  return { number: pr.number, state: pr.state, headSha: pr.head?.sha, baseSha: pr.base?.sha,
    baseRef: pr.base?.ref, headRef: pr.head?.ref, headRepository: pr.head?.repo?.full_name,
    repository: pr.base?.repo?.full_name, changedFiles: pr.changed_files };
}

function validatePr(pr, repository, number, defaultBranch) {
  const meta = productPrIdentity(pr);
  if (meta.number !== number || meta.state !== 'open' || !SHA.test(meta.headSha || '') ||
      !SHA.test(meta.baseSha || '') || meta.repository !== repository || !meta.headRepository ||
      !Number.isInteger(meta.changedFiles) || meta.changedFiles < 0) throw new Error('Invalid or non-open PR identity');
  if (!defaultBranch || meta.baseRef !== defaultBranch) throw new Error('PR does not target the repository default branch');
  return meta;
}

function matchesRun(run, meta, workflow) {
  return run.workflow_id === workflow.id && run.path === workflow.path &&
    run.event === 'pull_request' && run.head_sha === meta.headSha &&
    run.repository?.full_name === meta.repository && run.head_repository?.full_name === meta.headRepository &&
    run.head_branch === meta.headRef && Array.isArray(run.pull_requests) &&
    (!run.pull_requests.length || run.pull_requests.some((pr) => pr.number === meta.number));
}

export function latestProductRun(runs, meta, workflow) {
  const matching = runs.filter((run) => matchesRun(run, meta, workflow));
  if (matching.some((run) => !Number.isSafeInteger(run.id) || !Number.isSafeInteger(run.run_attempt) || run.run_attempt < 1)) {
    throw new Error(`Invalid workflow run identity: ${workflow.name}`);
  }
  // An old run can be rerun after a newer run. Its id does not change, so ids
  // alone would allow the earlier success to hide a new pending/failing attempt.
  const unfinished = matching.filter((run) => run.status !== 'completed');
  if (unfinished.length) return unfinished.sort((a, b) => b.id - a.id || b.run_attempt - a.run_attempt)[0];
  if (matching.length > 1 && matching.some((run) => !Number.isFinite(Date.parse(run.run_started_at || '')))) {
    throw new Error(`Cannot order workflow attempts: ${workflow.name}`);
  }
  return matching.sort((a, b) => Date.parse(b.run_started_at) - Date.parse(a.run_started_at) || b.id - a.id || b.run_attempt - a.run_attempt)[0];
}

function evaluateWorkflow(workflow, run, jobs, meta) {
  const name = workflow.name;
  if (!run) return { name, bucket: 'pending', detail: 'workflow not reported for current head' };
  if (run.status !== 'completed') return { name, bucket: 'pending', detail: run.status || 'not completed', runId: run.id };
  if (run.conclusion !== 'success') return { name, bucket: 'fail', detail: run.conclusion || 'missing conclusion', runId: run.id };
  for (const jobName of workflow.jobs) {
    const found = jobs.filter((job) => job.name === jobName && job.run_id === run.id && job.head_sha === meta.headSha);
    if (found.length !== 1) return { name, bucket: 'fail', detail: `${jobName}: expected one latest job, found ${found.length}`, runId: run.id };
    const job = found[0];
    if (job.status !== 'completed' || job.conclusion !== 'success') {
      return { name, bucket: job.status === 'completed' ? 'fail' : 'pending', detail: `${jobName}: ${job.conclusion || job.status}`, runId: run.id };
    }
  }
  return { name, bucket: 'pass', detail: 'all expected jobs succeeded', runId: run.id };
}

export function evaluateProductCi({ meta, workflows, observations }) {
  const checks = workflows.map((workflow) => {
    const observed = observations[workflow.path] || {};
    return evaluateWorkflow(workflow, observed.run, observed.jobs || [], meta);
  });
  const pendingNames = checks.filter((check) => check.bucket === 'pending').map((check) => check.name);
  const failedNames = checks.filter((check) => check.bucket === 'fail').map((check) => check.name);
  return { ok: true, ...meta, pending: pendingNames.length > 0, failed: failedNames.length > 0,
    pendingNames, failedNames, checks, detail: checks.length ? checks.map((check) => `${check.name}: ${check.detail}`).join('; ') : 'No product workflows apply to changed paths' };
}

function readWorkflow(api, prefix, workflow, meta) {
  const identity = api(`${prefix}/actions/workflows/${encodeURIComponent(workflow.path.split('/').pop())}`);
  if (!Number.isSafeInteger(identity.id) || identity.path !== workflow.path || identity.name !== workflow.name) {
    throw new Error(`Unexpected workflow identity: ${workflow.path}`);
  }
  const bound = { ...workflow, id: identity.id };
  const endpoint = `${prefix}/actions/workflows/${identity.id}/runs?event=pull_request&head_sha=${meta.headSha}`;
  const runs = readApiPages(api, endpoint, 'workflow_runs');
  const run = latestProductRun(runs, meta, bound);
  const jobs = run?.status === 'completed' && run.conclusion === 'success'
    // filter=latest retains successful jobs reused by GitHub's rerun-failed-jobs,
    // while selecting the new execution of every job actually retried.
    ? readApiPages(api, `${prefix}/actions/runs/${run.id}/jobs?filter=latest`, 'jobs') : [];
  // A rerun may have started while jobs were read. Never reuse the old success.
  if (run) {
    const current = api(`${prefix}/actions/runs/${run.id}`);
    const newest = latestProductRun(readApiPages(api, endpoint, 'workflow_runs'), meta, bound);
    if (!matchesRun(current, meta, bound) || current.run_attempt !== run.run_attempt ||
        current.status !== run.status || current.conclusion !== run.conclusion ||
        !newest || newest.id !== run.id || newest.run_attempt !== run.run_attempt ||
        newest.status !== run.status || newest.conclusion !== run.conclusion) {
      return { run: { ...run, status: 'queued', conclusion: null }, jobs: [] };
    }
  }
  return { run, jobs };
}

export function readProductCi(prNumber, { repository, api = githubApi, expectedHeadSha } = {}) {
  let meta = {};
  try {
    if (!Number.isSafeInteger(prNumber) || prNumber <= 0) throw new Error('Invalid PR number');
    if (!repository) { const { owner, name } = repoSlug(); repository = `${owner}/${name}`; }
    if (!/^[\w.-]+\/[\w.-]+$/.test(repository)) throw new Error('Invalid repository');
    const prefix = `repos/${repository}`;
    const repo = api(prefix);
    const pr = api(`${prefix}/pulls/${prNumber}`);
    meta = validatePr(pr, repository, prNumber, repo.default_branch);
    if (expectedHeadSha && meta.headSha !== expectedHeadSha) throw new Error('PR head changed before CI read');
    const files = readApiPages(api, `${prefix}/pulls/${prNumber}/files`, null, { maxPages: 31 });
    if (files.length !== meta.changedFiles) throw new Error('Changed-file list incomplete; cannot determine applicable product CI');
    const workflows = getApplicableProductCi(files);
    const observations = {};
    for (const workflow of workflows) observations[workflow.path] = readWorkflow(api, prefix, workflow, meta);
    const current = productPrIdentity(api(`${prefix}/pulls/${prNumber}`));
    if (JSON.stringify(current) !== JSON.stringify(meta)) {
      return { ok: true, ...meta, pending: true, failed: false, pendingNames: ['PR identity changed'], failedNames: [], checks: [], detail: 'PR head/base changed during CI read; recheck the new head' };
    }
    return evaluateProductCi({ meta, workflows, observations });
  } catch (error) {
    return { ok: false, ...meta, pending: false, failed: true, failedNames: ['product CI verification'], pendingNames: [], checks: [], error: error.message, detail: error.message };
  }
}
