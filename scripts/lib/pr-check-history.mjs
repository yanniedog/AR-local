/** gh returns useful JSON with exit 1 (failure) and 8 (pending). */
export function readCheckResult(result) {
  if (result.error) return { error: result.error.message };
  const message = (result.stderr || '').trim();
  if (/no (required )?checks reported/i.test(message)) return { checks: [] };
  if (![0, 1, 8].includes(result.status)) {
    return { error: message || `gh pr checks exit ${result.status}` };
  }
  try {
    const checks = JSON.parse(result.stdout || '[]');
    if (!Array.isArray(checks)) throw new Error('expected an array');
    if (!checks.length && result.status !== 0) throw new Error('nonzero exit without check observations');
    return { checks };
  } catch (error) {
    return { error: `Invalid gh pr checks output: ${error.message}` };
  }
}

/** Select reruns by start time; completion order can let an older run hide a new pending run. */
export function selectLatestChecks(checks) {
  const groups = new Map();
  for (const check of checks) {
    if (!check || typeof check.name !== 'string' || !check.name) {
      return { error: 'Check observation has no name' };
    }
    // Workflow and app identity keep independent producers from hiding one another.
    const key = JSON.stringify([check.name, check.workflow || '', check.app?.id ?? check.appId ?? '']);
    const group = groups.get(key) || [];
    group.push(check);
    groups.set(key, group);
  }
  const latest = [];
  for (const group of groups.values()) {
    if (group.length === 1) { latest.push(group[0]); continue; }
    if (!group.every((check) => check.app?.id || check.appId ||
      (check.workflow && /^https:\/\/github\.com\/[^/]+\/[^/]+\/actions\/runs\/\d+\/job\/\d+$/.test(check.link || '')))) {
      return { error: `Cannot identify producer of duplicate check runs: ${group[0].name}` };
    }
    const times = group.map((check) => Date.parse(check.startedAt || ''));
    if (times.some((time) => !Number.isFinite(time) || time <= 0)) {
      return { error: `Cannot order duplicate check runs: ${group[0].name} (missing startedAt)` };
    }
    const newest = Math.max(...times);
    const candidates = group.filter((_, index) => times[index] === newest);
    if (candidates.length > 1) {
      return { error: `Cannot order duplicate check runs: ${group[0].name} (equal startedAt)` };
    }
    latest.push(candidates[0]);
  }
  return { checks: latest };
}

/** Scope chronology errors to the requested gates, not unrelated advisory jobs. */
export function selectNamedCheckHistory(checks, names) {
  const wanted = new Set(names.map((name) => name.toLowerCase()));
  return selectLatestChecks(checks.filter((check) => {
    const name = String(check.name || '').toLowerCase();
    const tail = name.slice(name.lastIndexOf('/') + 1).trim();
    return wanted.has(name) || wanted.has(tail);
  }));
}
