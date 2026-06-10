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
    parts.push(`${key}=${String(value)}`);
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
  logDegradation('warn', 'fetch.httpError', {
    status,
    url: summarizeUrl(url),
    ...(context ? { ctx: context } : {}),
  });
}

export function logSwallowedError(context: string, err: unknown): void {
  const msg = err instanceof Error ? err.message : String(err);
  logDegradation('warn', 'swallowed', { ctx: context, error: msg });
}

export function logProGateBlocked(intent: ProGateIntent, source?: string): void {
  logDegradation('info', 'pro.gateBlocked', { intent, ...(source ? { from: source } : {}) });
}

export function logTabNoOp(tab: string): void {
  logDegradation('debug', 'nav.tabNoOp', { tab });
}

export function logCategoryRowPress(input: {
  section: SectionKey;
  label: string;
  pathBefore: string[];
  pathAfter: string[];
  source: string;
}): void {
  logDegradation('info', 'nav.categoryPress', {
    section: input.section,
    label: input.label,
    from: input.pathBefore.join('.') || '(root)',
    to: input.pathAfter.join('.'),
    depthBefore: input.pathBefore.length,
    depthAfter: input.pathAfter.length,
    source: input.source,
  });
}

export function logNavDrillAttempt(input: { fn: string; section: SectionKey; path: string[] }): void {
  logDegradation('info', 'nav.drillAttempt', {
    fn: input.fn,
    section: input.section,
    path: input.path.join('.') || '(root)',
    depth: input.path.length,
  });
}

export function logNavDeadDrill(input: {
  section: SectionKey;
  expectedPath: string[];
  actualPath: string[];
}): void {
  logDegradation('warn', 'nav.deadDrill', {
    section: input.section,
    expected: input.expectedPath.join('.') || '(root)',
    actual: input.actualPath.join('.') || '(root)',
  });
}

export function logNavParamDrop(input: {
  param: string;
  expected?: string;
  actual?: string;
  screen: string;
}): void {
  logDegradation('warn', 'nav.paramDrop', {
    screen: input.screen,
    param: input.param,
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

type RetryOutcome = 'start' | 'success' | 'failure';

export function logRetry(action: string, outcome: RetryOutcome, detail?: string): void {
  logDegradation(outcome === 'failure' ? 'warn' : 'info', `retry.${outcome}`, {
    action,
    ...(detail ? { detail } : {}),
  });
}

export async function runStoreRetry(
  action: string,
  fn: () => Promise<void>,
  ok: () => boolean,
  failDetail?: () => string | null,
): Promise<void> {
  logRetry(action, 'start');
  await fn();
  if (ok()) logRetry(action, 'success');
  else logRetry(action, 'failure', failDetail?.() ?? undefined);
}

let pendingDrill: { section: SectionKey; path: string[]; at: number } | null = null;

export function markDrillAttempt(section: SectionKey, path: string[]): void {
  pendingDrill = { section, path, at: Date.now() };
}

export function checkDrillOutcome(section: SectionKey, actualPath: string[]): void {
  if (!pendingDrill) return;
  const attempt = pendingDrill;
  pendingDrill = null;
  if (Date.now() - attempt.at > 2000) return;
  const sameSection = attempt.section === section;
  const pathsEqual =
    attempt.path.length === actualPath.length &&
    attempt.path.every((seg, i) => seg === actualPath[i]);
  if (sameSection && pathsEqual && attempt.path.length > 0) {
    logNavDeadDrill({ section, expectedPath: attempt.path, actualPath });
  } else if (sameSection && !pathsEqual && attempt.path.length > actualPath.length) {
    logNavParamDrop({
      screen: 'browse',
      param: 'path',
      expected: attempt.path.join('.'),
      actual: actualPath.join('.'),
    });
  }
}

export function watchTapOutcome(label: string, snapshot: () => string, delayMs = 300): () => void {
  if (!isDiagnosticsEnabled()) return () => {};
  const before = snapshot();
  return () => {
    setTimeout(() => {
      if (snapshot() === before) {
        logDegradation('warn', 'tap.noEffect', { label, snapshot: before.slice(0, 80) });
      }
    }, delayMs);
  };
}

export function resetDegradationStateForTests(): void {
  pendingDrill = null;
}
