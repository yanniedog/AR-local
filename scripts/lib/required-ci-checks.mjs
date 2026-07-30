import { spawnSync } from 'node:child_process';

export const DEFAULT_REQUIRED_CHECKS = ['bot-feedback-gate'];

function runGhJson(args) {
  const result = spawnSync('gh', args, {
    encoding: 'utf8',
    timeout: 120_000,
    maxBuffer: 8 * 1024 * 1024,
  });
  if (result.error) return { ok: false, error: result.error.message };
  if (result.status !== 0) {
    return {
      ok: false,
      error: (result.stderr || result.stdout || `gh exit ${result.status}`).trim(),
      status: result.status,
    };
  }
  try {
    return { ok: true, data: JSON.parse((result.stdout || '').trim() || '[]') };
  } catch (error) {
    return { ok: false, error: `Invalid JSON from gh: ${error.message}` };
  }
}

export function requiredChecksFromProtection(protection) {
  return requiredCheckSpecsFromProtection(protection).map((row) => row.context);
}

export function requiredChecksFromRules(rules) {
  return requiredCheckSpecsFromRules(rules).map((row) => row.context);
}

function asRequiredCheck(context, appId = null) {
  if (!context) return null;
  const parsedAppId = Number(appId);
  return {
    context,
    appId: Number.isFinite(parsedAppId) && parsedAppId > 0 ? parsedAppId : null,
  };
}

export function requiredCheckSpecsFromProtection(protection) {
  const checks = (protection?.required_status_checks?.checks || [])
    .map((row) => asRequiredCheck(row.context, row.app_id))
    .filter(Boolean);
  const boundContexts = new Set(checks.map((row) => normalizedName(row.context)));
  const legacyContexts = (protection?.required_status_checks?.contexts || [])
    .filter((context) => !boundContexts.has(normalizedName(context)))
    .map((context) => asRequiredCheck(context))
    .filter(Boolean);
  return [...checks, ...legacyContexts];
}

export function requiredCheckSpecsFromRules(rules) {
  return (rules || [])
    .filter((rule) => rule?.type === 'required_status_checks')
    .flatMap((rule) => rule?.parameters?.required_status_checks || [])
    .map((row) => asRequiredCheck(row.context, row.integration_id ?? row.app_id))
    .filter(Boolean);
}

function uniqueRequiredChecks(checks) {
  const seen = new Set();
  return (checks || []).filter((row) => {
    if (!row?.context) return false;
    const key = `${normalizedName(row.context)}:${row.appId ?? '*'}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function mergePolicyAndPrRequiredChecks(policy, prChecks = []) {
  return uniqueRequiredChecks([
    ...(policy?.requirements || []),
    ...prChecks
      .filter((row) =>
        !(policy?.values || []).some(
          (name) => normalizedName(name) === normalizedName(row.name),
        ))
      .map((row) => asRequiredCheck(row.name))
      .filter(Boolean),
  ]);
}

export function combineRequiredCheckState({
  protectionOk,
  protection,
  rulesOk,
  rules,
  fallbackRequiredNames = DEFAULT_REQUIRED_CHECKS,
}) {
  const sources = [];
  const liveChecks = [];
  if (protectionOk) {
    sources.push('branch protection');
    liveChecks.push(...requiredCheckSpecsFromProtection(protection));
  }
  if (rulesOk) {
    sources.push('rules');
    liveChecks.push(...requiredCheckSpecsFromRules(rules));
  }
  const completeLivePolicy = protectionOk && rulesOk;
  const liveNames = new Set(liveChecks.map((row) => normalizedName(row.context)));
  const fallbackChecks = completeLivePolicy
    ? []
    : fallbackRequiredNames
      .filter((name) => !liveNames.has(normalizedName(name)))
      .map((name) => asRequiredCheck(name))
      .filter(Boolean);
  const requirements = uniqueRequiredChecks([...liveChecks, ...fallbackChecks]);
  const source = completeLivePolicy
    ? `live ${sources.join(' + ')}`
    : sources.length
      ? `partial live ${sources.join(' + ')} + configured policy fallback`
      : 'configured policy fallback; live policy APIs unavailable';
  return {
    values: [...new Set(requirements.map((row) => row.context))],
    requirements,
    source,
  };
}

function normalizedName(value) {
  return String(value || '').trim().toLowerCase();
}

function nameMatches(candidate, expected) {
  const actual = normalizedName(candidate);
  const wanted = normalizedName(expected);
  if (actual === wanted) return true;
  const slash = actual.lastIndexOf('/');
  return slash >= 0 && actual.slice(slash + 1).trim() === wanted;
}

function observationTime(row) {
  return new Date(
    row.startedAt
      || row.started_at
      || row.completedAt
      || row.completed_at
      || row.updated_at
      || row.created_at
      || 0,
  ).getTime();
}

function selectNewest(rows) {
  return rows.reduce((newest, row) => {
    if (!newest) return row;
    const priorAt = observationTime(newest);
    const nextAt = observationTime(row);
    if (nextAt !== priorAt) return nextAt > priorAt ? row : newest;
    return Number(row.id || 0) >= Number(newest.id || 0) ? row : newest;
  }, null);
}

function observationState(row) {
  const bucket = normalizedName(row?.bucket);
  const state = normalizedName(row?.state || row?.status);
  const conclusion = normalizedName(row?.conclusion);
  if (
    bucket === 'fail'
    || bucket === 'cancel'
    || ['failure', 'error', 'cancelled', 'timed_out', 'action_required'].includes(state)
    || [
      'failure',
      'cancelled',
      'timed_out',
      'action_required',
      'startup_failure',
    ].includes(conclusion)
  ) {
    return 'failed';
  }
  if (
    bucket === 'pending'
    || ['queued', 'pending', 'in_progress', 'waiting', 'requested'].includes(state)
  ) {
    return 'pending';
  }
  if (
    bucket === 'pass'
    || state === 'success'
    || ['success', 'neutral', 'skipped'].includes(conclusion)
  ) {
    return 'passed';
  }
  return 'pending';
}

function observationAppId(row) {
  const parsed = Number(row?.app?.id ?? row?.app_id ?? row?.appId);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function requiredCheckMatches(candidate, required) {
  if (!nameMatches(candidate.name || candidate.context, required.context)) return false;
  return required.appId == null || observationAppId(candidate) === required.appId;
}

/**
 * Evaluate required contexts on the exact current PR head. Missing contexts are
 * pending because branch protection cannot merge until they are reported.
 */
export function evaluateRequiredCheckState({
  requiredNames,
  requiredChecks,
  ignoredNames = [],
  prChecks = [],
  headCheckRuns = [],
  commitStatuses = [],
}) {
  const ignored = new Set(ignoredNames.map(normalizedName));
  const requirements = uniqueRequiredChecks(
    requiredChecks?.length
      ? requiredChecks
      : (requiredNames || []).map((name) => asRequiredCheck(name)).filter(Boolean),
  ).filter((row) => !ignored.has(normalizedName(row.context)));
  const observations = [
    ...(prChecks || []),
    ...(headCheckRuns || []),
    ...(commitStatuses || []),
  ];
  const checks = [];
  const failedNames = [];
  const pendingNames = [];
  const missingNames = [];

  for (const required of requirements) {
    const name = required.context;
    const row = selectNewest(
      observations.filter((candidate) => requiredCheckMatches(candidate, required)),
    );
    if (!row) {
      missingNames.push(name);
      pendingNames.push(name);
      continue;
    }
    const state = observationState(row);
    checks.push({ name, state, ...(required.appId == null ? {} : { appId: required.appId }) });
    if (state === 'failed') failedNames.push(name);
    else if (state !== 'passed') pendingNames.push(name);
  }

  return {
    pending: pendingNames.length > 0,
    failed: failedNames.length > 0,
    failedNames,
    pendingNames,
    missingNames,
    checks,
  };
}

function encodeRef(value) {
  return encodeURIComponent(String(value || 'main'));
}

function policyForBranch(repo, baseRefName, fallbackRequiredNames) {
  const branch = encodeRef(baseRefName);
  const protection = runGhJson([
    'api',
    `repos/${repo}/branches/${branch}/protection`,
  ]);
  const rules = runGhJson(['api', `repos/${repo}/rules/branches/${branch}`]);
  return combineRequiredCheckState({
    protectionOk: protection.ok,
    protection: protection.data,
    rulesOk: rules.ok,
    rules: rules.data,
    fallbackRequiredNames,
  });
}

function prRequiredChecks(prNumber) {
  const result = spawnSync(
    'gh',
    [
      'pr',
      'checks',
      String(prNumber),
      '--required',
      '--json',
      'name,bucket,state,startedAt,completedAt',
    ],
    { encoding: 'utf8', timeout: 120_000 },
  );
  if (result.error) return { ok: false, error: result.error.message };
  if (result.status === 0 || result.status === 8) {
    try {
      return { ok: true, data: JSON.parse((result.stdout || '').trim() || '[]') };
    } catch (error) {
      return { ok: false, error: `Invalid JSON from gh pr checks: ${error.message}` };
    }
  }
  const error = (result.stderr || result.stdout || `gh exit ${result.status}`).trim();
  if (/no required checks reported/i.test(error) || /no checks reported/i.test(error)) {
    return { ok: true, data: [] };
  }
  return { ok: false, error, status: result.status };
}

/**
 * Read policy plus check-runs/statuses bound to the exact PR head. This catches
 * workflow_dispatch checks, which `gh pr checks` can omit.
 */
export function fetchRequiredCheckState({
  prNumber,
  repo,
  headSha,
  baseRefName = 'main',
  ignoredNames = [],
  fallbackRequiredNames = DEFAULT_REQUIRED_CHECKS,
}) {
  const policy = policyForBranch(repo, baseRefName, fallbackRequiredNames);
  const prChecks = prRequiredChecks(prNumber);
  const checkRuns = runGhJson([
    'api',
    `repos/${repo}/commits/${headSha}/check-runs?per_page=100`,
  ]);
  const statuses = runGhJson([
    'api',
    `repos/${repo}/commits/${headSha}/status?per_page=100`,
  ]);

  const evaluated = evaluateRequiredCheckState({
    requiredChecks: mergePolicyAndPrRequiredChecks(
      policy,
      prChecks.ok ? prChecks.data : [],
    ),
    ignoredNames,
    prChecks: prChecks.ok ? prChecks.data : [],
    headCheckRuns: checkRuns.ok ? checkRuns.data?.check_runs || [] : [],
    commitStatuses: statuses.ok ? statuses.data?.statuses || [] : [],
  });

  if (
    evaluated.missingNames.length > 0
    && !prChecks.ok
    && !checkRuns.ok
    && !statuses.ok
  ) {
    return {
      ...evaluated,
      error: [prChecks.error, checkRuns.error, statuses.error].filter(Boolean).join('; '),
      policySource: policy.source,
    };
  }
  return { ...evaluated, policySource: policy.source };
}
