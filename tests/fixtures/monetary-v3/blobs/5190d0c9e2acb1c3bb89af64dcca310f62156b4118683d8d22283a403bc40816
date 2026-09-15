/** Compact perf-audit encodings for bounded local raw-log exports; full report stays in the sidecar. */

import { readCompatibleAppHealthReport, toPublicAppHealthReport } from './appHealth';

const LONG_HEX = /\b[a-f0-9]{24,}\b/gi;

/**
 * A deep audit records ~260 checks. Hermes stacks, readiness dumps and joined
 * runtime-error lists are individually unbounded, so a run with many failed
 * steps produced multi-megabyte reports; teardown then serialized, redacted,
 * compacted and exported several copies of that body at once and exhausted the
 * JS heap right after progress reached 100%. Evidence is capped per check so
 * the report stays diagnosable without being unbounded.
 */
export const MAX_AUDIT_EVIDENCE_CHARS = 2_000;
export const MAX_AUDIT_METRIC_TEXT_CHARS = 512;
const AUDIT_PROOF_METRIC_KEYS = [
  'measurementMode',
  'executionAttempted',
  'actionInvoked',
  'actionCompleted',
  'actionSource',
  'actionRevisionBefore',
  'actionRevisionAfter',
  'renderRevisionBefore',
  'renderRevisionAfter',
  'actionResultEvidence',
  'actionMs',
  'forwardMs',
  'forwardWorkMs',
  'readinessQuietWindowMs',
  'backMs',
  'backgroundSettleMs',
  'expectedPath',
  'expectedSurface',
  'destinationReadinessMs',
  'backDestination',
  'backReturnedToAudit',
  'readinessActionEvidence',
] as const;

export function truncateAuditText(value: string, maxChars: number): string {
  if (value.length <= maxChars) return value;
  return `${value.slice(0, maxChars)}…[truncated ${value.length - maxChars} chars]`;
}

interface BoundableAuditCheck {
  metrics: Record<string, unknown>;
  trace?: string;
  error?: string;
}

/**
 * Cap a single check's evidence text. The same object is returned when nothing
 * exceeds its budget so a healthy run allocates no replacement checks.
 */
export function boundAuditCheckEvidence<T extends BoundableAuditCheck>(check: T): T {
  const boundedError = typeof check.error === 'string'
    ? truncateAuditText(check.error, MAX_AUDIT_EVIDENCE_CHARS)
    : check.error;
  const boundedTrace = typeof check.trace === 'string'
    ? truncateAuditText(check.trace, MAX_AUDIT_EVIDENCE_CHARS)
    : check.trace;
  let metrics = check.metrics;
  let metricsChanged = false;
  for (const [key, value] of Object.entries(check.metrics ?? {})) {
    if (typeof value !== 'string' || value.length <= MAX_AUDIT_METRIC_TEXT_CHARS) continue;
    if (!metricsChanged) {
      metrics = { ...check.metrics };
      metricsChanged = true;
    }
    metrics[key] = truncateAuditText(value, MAX_AUDIT_METRIC_TEXT_CHARS);
  }
  if (
    !metricsChanged &&
    boundedError === check.error &&
    boundedTrace === check.trace
  ) {
    return check;
  }
  return {
    ...check,
    metrics,
    ...(boundedError === undefined ? {} : { error: boundedError }),
    ...(boundedTrace === undefined ? {} : { trace: boundedTrace }),
  };
}

export function omitNullishDeep<T>(value: T): T {
  if (value == null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map((entry) => omitNullishDeep(entry)) as T;
  const out: Record<string, unknown> = {};
  for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
    if (nested == null) continue;
    out[key] = omitNullishDeep(nested);
  }
  return out as T;
}

export function shortenAuditEvidenceText(value: string): string {
  return value.replace(LONG_HEX, (match) => `${match.slice(0, 12)}…`);
}

export function compactAuditMetrics(
  metrics: Record<string, unknown> | null | undefined,
): Record<string, unknown> | undefined {
  if (!metrics) return undefined;
  const out: Record<string, unknown> = {};
  for (const [key, nested] of Object.entries(metrics)) {
    if (nested == null) continue;
    out[key] = typeof nested === 'string' ? shortenAuditEvidenceText(nested) : nested;
  }
  return Object.keys(out).length ? out : undefined;
}

export function compactAuditCheckForLog(check: {
  id: string;
  label: string;
  kind: string;
  status: string;
  durationMs: number | null;
  metrics: Record<string, unknown>;
  error?: string | null;
  trace?: string | null;
}): Record<string, unknown> {
  const base: Record<string, unknown> = {
    id: check.id,
    label: check.label,
    kind: check.kind,
    status: check.status,
    durationMs: check.durationMs,
  };
  if (check.status === 'pass' || check.status === 'skipped') {
    if (check.metrics.iteration != null) base.phase = check.metrics.iteration;
    if (typeof check.metrics.maxEventLoopLagMs === 'number') {
      base.maxEventLoopLagMs = check.metrics.maxEventLoopLagMs;
    }
    if (typeof check.metrics.maxFrameGapMs === 'number') {
      base.maxFrameGapMs = check.metrics.maxFrameGapMs;
    }
    if (typeof check.metrics.reason === 'string') base.reason = check.metrics.reason;
    const proof: Record<string, unknown> = {};
    for (const key of AUDIT_PROOF_METRIC_KEYS) {
      const value = check.metrics[key];
      if (value != null) proof[key] = typeof value === 'string'
        ? shortenAuditEvidenceText(value)
        : value;
    }
    if (Object.keys(proof).length) base.metrics = proof;
    return base;
  }
  const metrics = compactAuditMetrics(check.metrics);
  if (metrics) base.metrics = metrics;
  if (check.error) base.error = shortenAuditEvidenceText(check.error);
  if (check.trace) base.trace = shortenAuditEvidenceText(check.trace);
  return base;
}

export function compactPerformanceAuditReportForLog(report: unknown): unknown {
  if (report == null || typeof report !== 'object' || Array.isArray(report)) return report;
  const source = report as Record<string, unknown>;
  const checks = Array.isArray(source.checks)
    ? source.checks.map((entry) => {
      if (entry == null || typeof entry !== 'object' || Array.isArray(entry)) return entry;
      const check = entry as Record<string, unknown>;
      if (
        typeof check.id !== 'string' ||
        typeof check.label !== 'string' ||
        typeof check.kind !== 'string' ||
        typeof check.status !== 'string' ||
        (check.durationMs != null && typeof check.durationMs !== 'number') ||
        check.metrics == null ||
        typeof check.metrics !== 'object' ||
        Array.isArray(check.metrics)
      ) {
        return omitNullishDeep(entry);
      }
      return compactAuditCheckForLog({
        id: check.id,
        label: check.label,
        kind: check.kind,
        status: check.status,
        durationMs: typeof check.durationMs === 'number' ? check.durationMs : null,
        metrics: check.metrics as Record<string, unknown>,
        error: typeof check.error === 'string' ? check.error : null,
        trace: typeof check.trace === 'string' ? check.trace : null,
      });
    })
    : source.checks;

  let compactPlan: unknown = source.plan;
  if (source.plan != null && typeof source.plan === 'object' && !Array.isArray(source.plan)) {
    const plan = source.plan as Record<string, unknown>;
    const passes = Array.isArray(plan.passes) ? plan.passes : null;
    compactPlan = omitNullishDeep({
      schemaVersion: plan.schemaVersion,
      inputs: plan.inputs,
      passCount: passes?.length,
      stepCount: passes?.reduce((sum: number, pass) => {
        if (pass == null || typeof pass !== 'object' || Array.isArray(pass)) return sum;
        const steps = (pass as { steps?: unknown }).steps;
        return sum + (Array.isArray(steps) ? steps.length : 0);
      }, 0),
    });
  }

  const readableAppHealth = readCompatibleAppHealthReport(source.appHealth);
  const compactAppHealth = readableAppHealth?.kind === 'app-health-v7'
    ? toPublicAppHealthReport(readableAppHealth.report)
    : undefined;

  const kept = new Set([
    'schemaVersion', 'sessionId', 'startedAt', 'finishedAt', 'durationMs', 'partial',
    'app', 'watchdog', 'environment', 'plan', 'coverage', 'summary', 'checks', 'routeAggregates', 'limitations',
    'appHealth',
  ]);
  const extras: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(source)) {
    if (kept.has(key)) continue;
    if (typeof value === 'string' && value.length <= 2048) extras[key] = value;
    else if (typeof value === 'number' || typeof value === 'boolean') extras[key] = value;
  }

  return omitNullishDeep({
    schemaVersion: source.schemaVersion,
    sessionId: source.sessionId,
    startedAt: source.startedAt,
    finishedAt: source.finishedAt,
    durationMs: source.durationMs,
    partial: source.partial,
    app: source.app,
    watchdog: source.watchdog,
    environment: source.environment,
    plan: compactPlan,
    coverage: source.coverage,
    summary: source.summary,
    checks,
    routeAggregates: source.routeAggregates,
    limitations: source.limitations,
    appHealth: compactAppHealth,
    ...extras,
  });
}

export function compactAuditLogJson(value: unknown): string {
  return JSON.stringify(omitNullishDeep(value), (_key, nested) => (
    typeof nested === 'string' ? shortenAuditEvidenceText(nested) : nested
  ));
}
