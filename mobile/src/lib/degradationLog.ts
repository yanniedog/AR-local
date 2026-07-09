import type { SuitabilityExclusionCounts } from '../data/access';
import { debugLog, type LogLevel } from './debugLog';
import { isDiagnosticsEnabled } from './observability';
import type { ProGateIntent } from './proAccess';
import type { SectionKey } from '../types';

export const DEGRADE_TAG = 'degrade';

export function summarizeUrl(url: string): string {
  try {
    const u = new URL(url);
    u.search = u.search ? '?…' : '';
    u.hash = '';
    const out = u.toString();
    return out.length > 120 ? `${out.slice(0, 117)}…` : out;
  } catch {
    const noQuery = url.split('?')[0] ?? url;
    return noQuery.length > 120 ? `${noQuery.slice(0, 117)}…` : noQuery;
  }
}

function formatFields(fields: Record<string, string | number | boolean | null | undefined>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined || value === null || value === '') continue;
    const strValue = String(value);
    const safeValue = strValue.includes(' ') ? `"${strValue.replace(/"/g, '\\"')}"` : strValue;
    parts.push(`${key}=${safeValue}`);
  }
  return parts.join(' ');
}

export function logDegradation(
  level: LogLevel,
  event: string,
  fields: Record<string, string | number | boolean | null | undefined> = {},
): void {
  const verbose = level === 'debug' || level === 'info';
  if (verbose && !isDiagnosticsEnabled()) return;
  const suffix = formatFields(fields);
  debugLog[level](DEGRADE_TAG, suffix ? `${event} ${suffix}` : event);
}

export function logFetchHttpError(url: string, status: number, context?: string): void {
  logDegradation('warn', 'fetch.httpError', { status, url: summarizeUrl(url), ...(context ? { ctx: context } : {}) });
}

export function logSwallowedError(context: string, err: unknown): void {
  let msg = String(err);
  if (err instanceof Error) {
    msg = err.message;
  } else if (err && typeof err === 'object') {
    if ('message' in err && typeof (err as { message?: unknown }).message === 'string') {
      msg = (err as { message: string }).message;
    } else if ('error' in err && typeof (err as { error?: unknown }).error === 'string') {
      msg = (err as { error: string }).error;
    }
  }
  logDegradation('warn', 'swallowed', { ctx: context, error: msg });
}

export function logProGateBlocked(intent: ProGateIntent, source?: string): void {
  logDegradation('info', 'pro.gateBlocked', { intent, ...(source ? { from: source } : {}) });
}

export function logTabNoOp(tab: string): void {
  logDegradation('debug', 'nav.tabNoOp', { tab });
}

export function logCategoryRowPress(input: {
  section: SectionKey; label: string; pathBefore: string[]; pathAfter: string[]; source: string;
}): void {
  logDegradation('info', 'nav.categoryPress', {
    section: input.section, label: input.label,
    from: input.pathBefore.join('.') || '(root)', to: input.pathAfter.join('.'),
    depthBefore: input.pathBefore.length, depthAfter: input.pathAfter.length, source: input.source,
  });
}

export function logNavDrillAttempt(input: { fn: string; section: SectionKey; path: string[] }): void {
  logDegradation('info', 'nav.drillAttempt', {
    fn: input.fn, section: input.section, path: input.path.join('.') || '(root)', depth: input.path.length,
  });
}

export function logNavDeadDrill(input: { section: SectionKey; expectedPath: string[]; actualPath: string[] }): void {
  logDegradation('warn', 'nav.deadDrill', {
    section: input.section,
    expected: input.expectedPath.join('.') || '(root)',
    actual: input.actualPath.join('.') || '(root)',
  });
}

export function logNavParamDrop(input: { param: string; expected?: string; actual?: string; screen: string }): void {
  logDegradation('warn', 'nav.paramDrop', {
    screen: input.screen, param: input.param,
    ...(input.expected !== undefined ? { expected: input.expected || '(empty)' } : {}),
    ...(input.actual !== undefined ? { actual: input.actual || '(empty)' } : {}),
  });
}

export function logStoreRefreshSkipped(reason: string): void {
  logDegradation('warn', 'store.refreshSkipped', { reason });
}

export function logEnsureSkipped(fn: string, reason: string): void {
  logDegradation('debug', 'store.ensureSkipped', { fn, reason });
}

/** One-shot diagnostic for the default suitability filter (Phase 1.1). */
export function logSuitabilityExclusions(
  runDate: string | null | undefined,
  counts: SuitabilityExclusionCounts,
): void {
  const fields: Record<string, string | number | boolean | null | undefined> = {
    run_date: runDate ?? null,
    total: counts.total,
    non_standard: counts.nonStandard,
  };
  for (const [cat, n] of Object.entries(counts.byAccess)) {
    if (n) fields[`access_${cat}`] = n;
  }
  logDegradation('info', 'suitability.exclusions', fields);
}

type RetryOutcome = 'start' | 'success' | 'failure';

export function logRetry(action: string, outcome: RetryOutcome, detail?: string): void {
  logDegradation(outcome === 'failure' ? 'warn' : 'info', `retry.${outcome}`, { action, ...(detail ? { detail } : {}) });
}

export async function runStoreRetry(
  action: string, fn: () => Promise<void>, ok: () => boolean, failDetail?: () => string | null,
): Promise<void> {
  logRetry(action, 'start');
  try {
    await fn();
  } catch (err) {
    logSwallowedError(action, err);
    logRetry(action, 'failure', failDetail?.() ?? undefined);
    return;
  }
  if (ok()) logRetry(action, 'success');
  else logRetry(action, 'failure', failDetail?.() ?? undefined);
}

const DRILL_OUTCOME_TIMEOUT_MS = 2000;

type PendingDrill = {
  section: SectionKey;
  path: string[];
  timer: ReturnType<typeof setTimeout>;
};

let pendingDrill: PendingDrill | null = null;
let lastObservedPath: { section: SectionKey; path: string[] } | null = null;

function clearPendingDrill(): void {
  if (pendingDrill) clearTimeout(pendingDrill.timer);
  pendingDrill = null;
}

/**
 * Record a drill navigation attempt. If no matching browse render confirms the
 * drill within the timeout, the tap was dead — log it with whatever path the
 * browse screen last rendered so expected-vs-actual is visible in the log.
 */
export function markDrillAttempt(section: SectionKey, path: string[]): void {
  clearPendingDrill();
  const timer = setTimeout(() => {
    if (!pendingDrill || pendingDrill.timer !== timer) return;
    const stale = pendingDrill;
    pendingDrill = null;
    logNavDeadDrill({
      section: stale.section,
      expectedPath: stale.path,
      actualPath: lastObservedPath?.section === stale.section ? lastObservedPath.path : [],
    });
  }, DRILL_OUTCOME_TIMEOUT_MS);
  pendingDrill = { section, path, timer };
}

/**
 * Called from the browse screen whenever its (section, path) settles. A render
 * matching the pending attempt confirms the drill and cancels the dead-drill
 * timer. Non-matching renders are interim states (the section flips before the
 * path param lands) — only the timeout declares a drill dead.
 */
export function checkDrillOutcome(section: SectionKey, actualPath: string[]): void {
  lastObservedPath = { section, path: actualPath };
  if (!pendingDrill || pendingDrill.section !== section) return;
  const attempt = pendingDrill;
  const pathsEqual = attempt.path.length === actualPath.length && attempt.path.every((seg, i) => seg === actualPath[i]);
  if (pathsEqual) {
    clearPendingDrill();
    logDegradation('debug', 'nav.drillConfirmed', { section, path: actualPath.join('.') || '(root)' });
  }
}

export function resetDegradationStateForTests(): void {
  clearPendingDrill();
  lastObservedPath = null;
}
