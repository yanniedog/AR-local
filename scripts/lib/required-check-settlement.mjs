export const DEFAULT_IGNORED_CHECK_NAMES = [
  'bot-presence-gate',
  'bot-feedback-gate',
  'pr-bot-presence-gate',
  'pr-bot-feedback-check',
  'pr-gates-advisory',
];

export function ignoredCheckNames(raw = process.env.BOT_WAIT_IGNORE_CHECK_NAMES || '') {
  const fromEnv = raw
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  return new Set([...DEFAULT_IGNORED_CHECK_NAMES, ...fromEnv]);
}

/** Match a full check name or trailing job segment (for example, workflow / job). */
export function checkNameMatchesIgnore(checkName, ignore) {
  const lower = (checkName || '').toLowerCase();
  if (ignore.has(lower)) return true;
  const slash = lower.lastIndexOf('/');
  const tail = slash >= 0 ? lower.slice(slash + 1).trim() : lower;
  return ignore.has(tail);
}

function pendingShape(extra = {}) {
  return { pending: true, failed: false, failedNames: [], ...extra };
}

export function parseRequiredChecksResult(result, ignore = ignoredCheckNames()) {
  const stdout = (result.stdout || '').trim();
  if (result.status !== 0 && result.status !== 8) {
    const message = (result.stderr || '').trim() || `gh pr checks exit ${result.status}`;
    if (/no required checks reported/i.test(message) || /no checks reported/i.test(message)) {
      return { pending: false, failed: false, failedNames: [] };
    }
    return pendingShape({ error: message });
  }
  if (!stdout) return pendingShape();

  let checks;
  try {
    checks = JSON.parse(stdout);
  } catch (error) {
    return pendingShape({ error: `Invalid JSON from gh pr checks: ${error.message}` });
  }

  let pending = false;
  let failed = false;
  const failedNames = [];
  for (const check of Array.isArray(checks) ? checks : []) {
    if (checkNameMatchesIgnore(check.name, ignore)) continue;
    if (
      check.bucket === 'pending'
      || check.state === 'PENDING'
      || check.state === 'IN_PROGRESS'
      || check.state === 'QUEUED'
    ) {
      pending = true;
    }
    if (
      check.bucket === 'fail'
      || check.bucket === 'cancel'
      || check.state === 'FAILURE'
      || check.state === 'ERROR'
      || check.state === 'CANCELLED'
    ) {
      failed = true;
      failedNames.push(check.name);
    }
  }
  return { pending, failed, failedNames };
}
