/** Required aggregate gate; review-vendor presence remains advisory. */
export const REQUIRED_AGGREGATE_GATE = 'bot-feedback-gate';
const ADVISORY_PRESENCE_GATE = 'bot-presence-gate';

function normalizeChecks(protection) {
  if (!protection || typeof protection.strict !== 'boolean'
    || !Array.isArray(protection.checks) || !Array.isArray(protection.contexts)) {
    throw new Error('Existing status-check protection and check source metadata are required; no settings changed');
  }
  const checks = new Map();
  for (const check of protection.checks) {
    const { context, app_id: appId } = check || {};
    if (typeof context !== 'string' || !context || checks.has(context)
      || !(appId == null || appId === -1 || (Number.isSafeInteger(appId) && appId > 0))) {
      throw new Error('Invalid or duplicate existing required-check source metadata');
    }
    // A null source is intentionally unrestricted. Omitting app_id would let
    // GitHub infer a recent producer, changing unrelated policy on a rerun.
    checks.set(context, { context, app_id: appId ?? -1 });
  }
  if (protection.contexts.some((context) => !checks.has(context))) {
    throw new Error('A required context has no source metadata; refusing to weaken its binding');
  }
  return [...checks.values()];
}

export function buildStatusCheckPatch(existing, actionsAppId) {
  if (!Number.isSafeInteger(actionsAppId) || actionsAppId <= 0) {
    throw new Error('Cannot identify the GitHub Actions app');
  }
  const checks = normalizeChecks(existing).filter((check) => check.context !== ADVISORY_PRESENCE_GATE);
  const aggregate = checks.find((check) => check.context === REQUIRED_AGGREGATE_GATE);
  if (aggregate && aggregate.app_id !== -1 && aggregate.app_id !== actionsAppId) {
    throw new Error('bot-feedback-gate is bound to a different app; review the source binding before changing it');
  }
  if (aggregate) aggregate.app_id = actionsAppId;
  else checks.push({ context: REQUIRED_AGGREGATE_GATE, app_id: actionsAppId });
  // Strict freshness is part of exact-head CI acceptance. Product paths remain
  // enforced inside the aggregate, not as permanently required skipped workflows.
  return { strict: true, checks };
}

function samePolicy(observed, expected) {
  const key = (checks) => JSON.stringify([...checks].sort((a, b) => a.context.localeCompare(b.context)));
  return observed.strict === expected.strict && key(normalizeChecks(observed)) === key(expected.checks);
}

export function applyStatusCheckPolicy({ branch, dryRun = false } = {}, { read, write }) {
  const repo = read(['repo', 'view', '--json', 'nameWithOwner,defaultBranchRef']);
  const selectedBranch = branch ?? repo?.defaultBranchRef?.name;
  if (!repo?.nameWithOwner || typeof selectedBranch !== 'string' || !selectedBranch.trim()) {
    throw new Error('Cannot determine repository or default branch');
  }
  const endpoint = `repos/${repo.nameWithOwner}/branches/${encodeURIComponent(selectedBranch)}/protection/required_status_checks`;
  const existing = read(['api', endpoint]);
  const actionsApp = read(['api', 'apps/github-actions']);
  if (actionsApp?.slug !== 'github-actions') throw new Error('Unexpected GitHub Actions app identity');
  const patch = buildStatusCheckPatch(existing, actionsApp.id);
  const changed = !samePolicy(existing, patch);
  if (changed && !dryRun) {
    write(['api', '--method', 'PATCH', endpoint, '--input', '-'], patch);
    const observed = read(['api', endpoint]);
    if (!samePolicy(observed, patch)) throw new Error('Required-check policy readback did not match the requested update');
  }
  return { repo: repo.nameWithOwner, branch: selectedBranch, dryRun, changed, patch };
}
