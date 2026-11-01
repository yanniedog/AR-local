/** Opt-in recovery of a merged head's gate; no open-PR or deployment policy changes. */
import { githubApi, mergedPrIdentity, readProductCi } from './pr-product-ci.mjs';
import { combineRequiredGate, REQUIRED_GATE_NAME, validPrNumber, writeCheck } from './pr-required-gate.mjs';
import { mergedFeedbackViolations, readMergedFeedback } from './pr-merged-feedback.mjs';

const SHA = /^[0-9a-f]{40}$/;

/** Only explicit dispatch inputs can select recovery; event text never becomes shell code. */
export function mergedDispatch(event, eventName, repository, prNumber) {
  const inputs = event.inputs || {};
  if (eventName !== 'workflow_dispatch') return null;
  const enabled = inputs.merged_revalidation === true || inputs.merged_revalidation === 'true';
  if (!enabled) {
    if (inputs.expected_head || inputs.expected_merge) throw new Error('Pinned merged inputs require explicit merged_revalidation');
    if (![undefined, false, 'false', ''].includes(inputs.merged_revalidation)) throw new Error('Invalid merged_revalidation input');
    return null;
  }
  if (event.repository?.full_name !== repository || validPrNumber(inputs.pr_number) !== prNumber ||
      inputs.retired_head || !SHA.test(inputs.expected_head || '') || !SHA.test(inputs.expected_merge || '')) {
    throw new Error('Invalid merged revalidation dispatch');
  }
  return { expectedHeadSha: inputs.expected_head, expectedMergeSha: inputs.expected_merge };
}

function snapshot(api, repository, number, expectedHeadSha, expectedMergeSha) {
  const prefix = `repos/${repository}`, repo = api(prefix);
  if (repo.full_name !== repository || typeof repo.default_branch !== 'string' || !repo.default_branch) {
    throw new Error('Unexpected repository/default branch');
  }
  const identity = mergedPrIdentity(api(`${prefix}/pulls/${number}`), repository, number,
    repo.default_branch, expectedHeadSha, expectedMergeSha);
  const branch = api(`${prefix}/branches/${encodeURIComponent(repo.default_branch)}`);
  if (branch.name !== repo.default_branch || !SHA.test(branch.commit?.sha || '')) throw new Error('Invalid default branch identity');
  const comparison = api(`${prefix}/compare/${expectedMergeSha}...${branch.commit.sha}`);
  if (!['ahead', 'identical'].includes(comparison.status) || comparison.merge_base_commit?.sha !== expectedMergeSha ||
      comparison.base_commit?.sha !== expectedMergeSha) throw new Error('Merged commit is not proven in default branch ancestry');
  return { ...identity, defaultBranch: repo.default_branch, defaultHead: branch.commit.sha };
}

export function publishMergedGate(prNumber, {
  repository, expectedHeadSha, expectedMergeSha, reporterSha, runId, runAttempt,
  api = githubApi, write = writeCheck, productReader = readProductCi,
  threadReader = readMergedFeedback, now = () => new Date().toISOString(),
} = {}) {
  validPrNumber(prNumber);
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository || '') || !SHA.test(expectedHeadSha || '') ||
      !SHA.test(expectedMergeSha || '') || !SHA.test(reporterSha || '') ||
      !Number.isSafeInteger(runId) || runId <= 0 || !Number.isSafeInteger(runAttempt) || runAttempt <= 0) {
    throw new Error('Invalid merged reporter identity');
  }
  // Reject an unrelated target before creating a check. Once bound, all unavailable
  // evidence becomes a new failed check rather than leaving an old success current.
  const initial = snapshot(api, repository, prNumber, expectedHeadSha, expectedMergeSha);
  const prefix = `repos/${repository}`;
  const binding = { repository, prNumber, expectedHeadSha, expectedMergeSha, reporterSha, runId, runAttempt };
  const created = write(`${prefix}/check-runs`, {
    name: REQUIRED_GATE_NAME, head_sha: expectedHeadSha, status: 'in_progress', started_at: now(),
    // Ordinary closed/prior-head retirement must not own this explicit evaluation.
    external_id: `ar-local-merged-required:${prNumber}:${expectedHeadSha}:${expectedMergeSha}`,
    details_url: `https://github.com/${repository}/actions/runs/${runId}/attempts/${runAttempt}`,
    output: { title: 'Revalidating pinned merged PR', summary: JSON.stringify(binding) },
  });
  if (!Number.isSafeInteger(created.id) || created.id <= 0) throw new Error('Missing published check id');
  let outcome, product;
  try {
    const threads = threadReader(repository, prNumber, initial);
    const violations = mergedFeedbackViolations(threads);
    const feedbackSnapshot = JSON.stringify(threads);
    product = productReader(prNumber, { repository, api, expectedHeadSha, expectedMergeSha });
    // Keep the live substantive-feedback rules, not the historical audit's leniency.
    outcome = combineRequiredGate(product, violations);
    const current = snapshot(api, repository, prNumber, expectedHeadSha, expectedMergeSha);
    if (JSON.stringify(current) !== JSON.stringify(initial)) throw new Error('Merged identity or default branch changed during revalidation');
    if (outcome.conclusion === 'success') {
      // Feedback can be added, reopened, edited or deleted during CI/identity reads.
      // Make a complete second snapshot the final evidence read before publication.
      const finalThreads = threadReader(repository, prNumber, current);
      const finalViolations = mergedFeedbackViolations(finalThreads);
      if (JSON.stringify(finalThreads) !== feedbackSnapshot) throw new Error('Review feedback changed during revalidation');
      outcome = combineRequiredGate(product, finalViolations);
    }
  } catch (error) {
    outcome = { status: 'completed', conclusion: 'failure', title: 'Merged gate verification unavailable', summary: error.message };
  }
  const evidence = { ...binding, checkId: created.id, defaultHead: initial.defaultHead,
    workflowRuns: product?.workflowRuns || [] };
  outcome.summary += '\n\n' + JSON.stringify(evidence) +
    '\nEffective protection, all required contexts and complete resolved-thread deployment evidence remain enforced by unchanged D027 producer_checks.';
  write(`${prefix}/check-runs/${created.id}`, { status: outcome.status,
    ...(outcome.conclusion ? { conclusion: outcome.conclusion, completed_at: now() } : {}),
    output: { title: outcome.title, summary: outcome.summary } }, 'PATCH');
  return { ...outcome, ...evidence };
}
