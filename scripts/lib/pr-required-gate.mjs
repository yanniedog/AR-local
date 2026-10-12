/** Trusted, event-driven publisher for the single required merge check. */
import { spawnSync } from 'node:child_process';
import { classifyThreads, fetchPullRequestThreads } from './gh-pr-review-threads.mjs';
import { githubApi, productPrIdentity, readApiPages, readProductCi } from './pr-product-ci.mjs';

export const REQUIRED_GATE_NAME = 'bot-feedback-gate';

export function validPrNumber(value) {
  if (!/^[1-9][0-9]*$/.test(String(value))) throw new Error('Invalid PR number');
  const number = Number(value);
  if (!Number.isSafeInteger(number)) throw new Error('Invalid PR number');
  return number;
}

function validateRepository(repository) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository || '')) throw new Error('Invalid repository');
}

export function discoverGatePrs(event, eventName, repository, api = githubApi) {
  validateRepository(repository);
  if (eventName === 'workflow_dispatch') return [validPrNumber(event.inputs?.pr_number)];
  if (eventName === 'pull_request_target') return [validPrNumber(event.pull_request?.number)];
  if (eventName === 'issue_comment') return event.issue?.pull_request ? [validPrNumber(event.issue.number)] : [];
  if (eventName !== 'workflow_run') throw new Error('Unsupported gate event');
  const run = event.workflow_run;
  if (run?.event !== 'pull_request' && run?.event !== 'pull_request_review' &&
      run?.event !== 'pull_request_review_comment') return [];
  if (run.repository?.full_name !== repository || !run.head_repository?.full_name) {
    throw new Error('Unexpected workflow repository');
  }
  // Fork runs can have an empty pull_requests array. Resolve from live PRs,
  // never from workflow artifacts or a caller-provided checkout path.
  const prs = readApiPages(api, 'repos/' + repository + '/pulls?state=open');
  return prs.filter((pr) => pr.head?.repo?.full_name === run.head_repository.full_name &&
    pr.head?.ref === run.head_branch).map((pr) => validPrNumber(pr.number));
}

export function writeCheck(endpoint, body, method = 'POST') {
  const result = spawnSync('gh', ['api', '--method', method, endpoint, '--input', '-'], {
    input: JSON.stringify(body), encoding: 'utf8', timeout: 120_000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(result.stderr?.trim() || result.error?.message || 'Check publication failed');
  }
  return JSON.parse(result.stdout);
}

export function combineRequiredGate(product, violations) {
  if (!product.ok || product.failed) {
    return { status: 'completed', conclusion: 'failure',
      title: 'Applicable product CI has not passed', summary: product.error || product.detail };
  }
  if (violations.length) {
    return { status: 'completed', conclusion: 'failure', title: 'Review feedback requires resolution',
      summary: String(violations.length) + ' substantive unresolved review thread(s). Resolve feedback, then refresh this gate.' };
  }
  if (product.pending) {
    return { status: 'in_progress', title: 'Waiting for applicable product CI', summary: product.detail };
  }
  return { status: 'completed', conclusion: 'success', title: 'Applicable CI and feedback passed',
    summary: product.detail + '\nReview vendors remain advisory; existing substantive feedback was checked.' };
}

function samePr(a, b) {
  return JSON.stringify(productPrIdentity(a)) === JSON.stringify(productPrIdentity(b));
}

/** Complete abandoned evaluations without touching workflow jobs or other PRs. */
function retirePendingEvaluations(prNumber, headSha, { prefix, api, write, now, beforeId = Infinity }) {
  const rows = readApiPages(api,
    prefix + '/commits/' + headSha + '/check-runs?check_name=' + REQUIRED_GATE_NAME + '&filter=all', 'check_runs');
  const owned = rows.filter((check) => check.name === REQUIRED_GATE_NAME && check.head_sha === headSha &&
    check.external_id === 'ar-local-required:' + prNumber + ':' + headSha &&
    check.app?.id === 15368 && check.app?.slug === 'github-actions' &&
    ['in_progress', 'queued'].includes(check.status));
  if (owned.some((check) => !Number.isSafeInteger(check.id) || check.id <= 0)) {
    throw new Error('Invalid pending required-check identity');
  }
  for (const check of owned.filter((check) => check.id < beforeId)) {
    write(prefix + '/check-runs/' + check.id, {
      status: 'completed', conclusion: 'cancelled', completed_at: now(),
      output: { title: 'Evaluation retired', summary: beforeId === Infinity
        ? 'The pull request is closed; this pending evaluation no longer applies.'
        : 'A newer required-gate evaluation supersedes this pending snapshot.' },
    }, 'PATCH');
  }
}

export function publishRequiredGate(prNumber, {
  repository, api = githubApi, write = writeCheck, productReader = readProductCi,
  threadReader = fetchPullRequestThreads, now = () => new Date().toISOString(), detailsUrl,
} = {}) {
  validateRepository(repository);
  validPrNumber(prNumber);
  const prefix = 'repos/' + repository;
  const prPath = prefix + '/pulls/' + prNumber;
  const initial = api(prPath);
  if (initial.number !== prNumber || !['open', 'closed'].includes(initial.state) || initial.base?.repo?.full_name !== repository ||
      !/^[0-9a-f]{40}$/.test(initial.head?.sha || '')) throw new Error('Invalid PR identity');
  if (initial.state !== 'open') {
    retirePendingEvaluations(prNumber, initial.head.sha, { prefix, api, write, now });
    return { skipped: true, detail: 'PR is closed; owned pending evaluations retired, no new gate published' };
  }
  const startedAt = now();
  // Publish pending first. API errors and interrupted evaluation cannot leave
  // this evaluation green. Each serialized evaluation gets its own check run.
  const created = write(prefix + '/check-runs', {
    name: REQUIRED_GATE_NAME, head_sha: initial.head.sha, status: 'in_progress',
    started_at: startedAt, external_id: 'ar-local-required:' + prNumber + ':' + initial.head.sha,
    ...(detailsUrl ? { details_url: detailsUrl } : {}),
    output: { title: 'Evaluating current CI and feedback', summary: 'Reading live PR evidence.' },
  });
  if (!Number.isSafeInteger(created.id) || created.id <= 0) throw new Error('Missing published check id');
  let outcome;
  try {
    // Establish the newer pending requirement before retiring older snapshots.
    // Otherwise cancelling the sole current check could briefly release merge.
    retirePendingEvaluations(prNumber, initial.head.sha, { prefix, api, write, now, beforeId: created.id });
    const [owner, name] = repository.split('/');
    const threads = threadReader(owner, name, prNumber).threads;
    if (!Array.isArray(threads)) throw new Error('Review threads unavailable');
    // Review pagination can take time. Read product runs afterwards so a rerun
    // started during feedback collection cannot reuse an earlier green result.
    const product = productReader(prNumber, { repository, api, expectedHeadSha: initial.head.sha });
    outcome = combineRequiredGate(product, classifyThreads(threads));
    if (!samePr(initial, api(prPath))) {
      outcome = { status: 'in_progress', title: 'PR changed during evaluation',
        summary: 'The head or base changed. A fresh evaluation is required before merge.' };
    }
  } catch (error) {
    outcome = { status: 'completed', conclusion: 'failure', title: 'Gate verification unavailable',
      summary: error.message };
  }
  const body = { status: outcome.status, output: { title: outcome.title, summary: outcome.summary } };
  if (outcome.conclusion) Object.assign(body, { conclusion: outcome.conclusion, completed_at: now() });
  write(prefix + '/check-runs/' + created.id, body, 'PATCH');
  return { ...outcome, checkId: created.id, headSha: initial.head.sha, prNumber };
}
