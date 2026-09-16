import {
  APP_HEALTH_CHECK_CODES,
  APP_HEALTH_DOMAINS,
  APP_HEALTH_SCHEMA_VERSION,
  type AppHealthCheck,
  type AppHealthCheckCode,
  type AppHealthCoverage,
  type AppHealthDomain,
  type AppHealthDomainSummary,
  type AppHealthMetricValue,
  type AppHealthOverall,
  type AppHealthReport,
  type AppHealthStatus,
  type AppHealthSummary,
  type FinalizeAppHealthReportInput,
  type LegacyPerformanceAuditReportV6,
  type PublicAppHealthReport,
  type ReadableAppHealthReport,
} from './types';

interface StatusCounts {
  pass: number;
  warn: number;
  fail: number;
  unavailable: number;
  notRun: number;
  total: number;
}

function countStatuses(checks: readonly AppHealthCheck[]): StatusCounts {
  const counts: StatusCounts = {
    pass: 0,
    warn: 0,
    fail: 0,
    unavailable: 0,
    notRun: 0,
    total: checks.length,
  };
  for (const check of checks) {
    if (check.status === 'not-run') counts.notRun += 1;
    else counts[check.status] += 1;
  }
  return counts;
}

function overallFor(counts: StatusCounts): AppHealthOverall {
  if (counts.fail > 0) return 'bottleneck';
  if (counts.total === 0 || counts.warn > 0 || counts.unavailable > 0 || counts.notRun > 0) {
    return 'attention';
  }
  return 'healthy';
}

export function summarizeAppHealthDomains(
  checks: readonly AppHealthCheck[],
): AppHealthDomainSummary[] {
  return APP_HEALTH_DOMAINS.map((domain) => {
    const counts = countStatuses(checks.filter((check) => check.domain === domain));
    return { domain, overall: overallFor(counts), ...counts };
  });
}

export function summarizeAppHealth(checks: readonly AppHealthCheck[]): AppHealthSummary {
  const counts = countStatuses(checks);
  const executed = counts.pass + counts.warn + counts.fail;
  return {
    overall: overallFor(counts),
    ...counts,
    coveragePercent: counts.total ? Math.round((executed / counts.total) * 10_000) / 100 : null,
  };
}

function repeated(values: readonly string[]): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  }
  return [...duplicates].sort();
}

function planIntegrity(
  checks: readonly AppHealthCheck[],
  plannedCheckIds: readonly string[],
  reservedPlanChecks: number,
): { coverage: AppHealthCoverage; check: AppHealthCheck } {
  const duplicatePlannedCheckIds = repeated(plannedCheckIds);
  const expected = new Set(plannedCheckIds);
  const storedIds = checks.map((check) => check.id);
  const stored = new Set(storedIds);
  const missingPlannedCheckIds = [...expected].filter((id) => !stored.has(id)).sort();
  const duplicateStoredCheckIds = repeated(storedIds);
  const unexpectedStoredCheckIds = [...stored].filter((id) => !expected.has(id)).sort();
  const complete =
    expected.size > 0 &&
    duplicatePlannedCheckIds.length === 0 &&
    missingPlannedCheckIds.length === 0 &&
    duplicateStoredCheckIds.length === 0 &&
    unexpectedStoredCheckIds.length === 0 &&
    reservedPlanChecks === 0;
  const coverage: AppHealthCoverage = {
    plannedChecks: expected.size + 1,
    storedChecks: checks.length + 1,
    missingPlannedCheckIds,
    duplicateStoredCheckIds,
    unexpectedStoredCheckIds,
    complete,
  };
  return {
    coverage,
    check: {
      id: APP_HEALTH_CHECK_CODES.AUDIT_PLAN,
      code: APP_HEALTH_CHECK_CODES.AUDIT_PLAN,
      label: 'Audit plan integrity',
      domain: 'performance',
      status: complete ? 'pass' : 'fail',
      metrics: {
        plannedChecks: coverage.plannedChecks,
        storedChecks: coverage.storedChecks,
        missingChecks: missingPlannedCheckIds.length,
        duplicateChecks: duplicateStoredCheckIds.length,
        unexpectedChecks: unexpectedStoredCheckIds.length,
        duplicatePlannedChecks: duplicatePlannedCheckIds.length,
        reservedPlanChecks,
        complete,
      },
      ...(complete
        ? {}
        : {
            summary: 'The stored audit results do not exactly cover the declared plan.',
            localEvidence: {
              missingPlannedCheckIds,
              duplicateStoredCheckIds,
              unexpectedStoredCheckIds,
              duplicatePlannedCheckIds,
            },
          }),
    },
  };
}

/**
 * Finalize only after all check producers have stopped. Plan integrity is itself
 * a stored check, so incomplete coverage can never coexist with a healthy result.
 */
export function finalizeAppHealthReport(
  input: FinalizeAppHealthReportInput,
): AppHealthReport {
  const reservedPlanChecks = input.checks.filter(
    (check) => check.id === APP_HEALTH_CHECK_CODES.AUDIT_PLAN,
  ).length;
  const baseChecks = input.checks.filter(
    (check) => check.id !== APP_HEALTH_CHECK_CODES.AUDIT_PLAN,
  );
  const plannedIds = input.plannedCheckIds.filter(
    (id) => id !== APP_HEALTH_CHECK_CODES.AUDIT_PLAN,
  );
  const integrity = planIntegrity(baseChecks, plannedIds, reservedPlanChecks);
  const checks = [...baseChecks, integrity.check];
  return {
    schemaVersion: APP_HEALTH_SCHEMA_VERSION,
    sessionId: input.sessionId,
    mode: input.mode,
    startedAt: input.startedAt,
    finishedAt: input.finishedAt,
    checks,
    domains: summarizeAppHealthDomains(checks),
    summary: summarizeAppHealth(checks),
    coverage: integrity.coverage,
    limitations: [...(input.limitations ?? [])],
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isAppHealthStatus(value: unknown): value is AppHealthStatus {
  return ['pass', 'warn', 'fail', 'unavailable', 'not-run'].includes(String(value));
}

function isAppHealthDomain(value: unknown): value is AppHealthDomain {
  return (APP_HEALTH_DOMAINS as readonly unknown[]).includes(value);
}

function isV7Check(value: unknown): value is AppHealthCheck {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    Object.values(APP_HEALTH_CHECK_CODES).includes(value.code as AppHealthCheckCode) &&
    typeof value.label === 'string' &&
    isAppHealthDomain(value.domain) &&
    isAppHealthStatus(value.status) &&
    isRecord(value.metrics)
  );
}

/** Read schema v7 without deleting or mislabelling still-readable schema-v6 reports. */
export function readCompatibleAppHealthReport(value: unknown): ReadableAppHealthReport | null {
  if (!isRecord(value)) return null;
  if (
    value.schemaVersion === APP_HEALTH_SCHEMA_VERSION &&
    typeof value.sessionId === 'string' &&
    (value.mode === 'local' || value.mode === 'live-source') &&
    typeof value.startedAt === 'string' &&
    typeof value.finishedAt === 'string' &&
    Array.isArray(value.checks) &&
    value.checks.every(isV7Check) &&
    Array.isArray(value.domains) &&
    isRecord(value.summary) &&
    isRecord(value.coverage) &&
    Array.isArray(value.limitations)
  ) {
    return { kind: 'app-health-v7', report: value as unknown as AppHealthReport };
  }
  if (
    value.schemaVersion === 6 &&
    typeof value.sessionId === 'string' &&
    typeof value.startedAt === 'string' &&
    typeof value.finishedAt === 'string' &&
    Array.isArray(value.checks) &&
    isRecord(value.summary)
  ) {
    return {
      kind: 'performance-audit-v6',
      report: value as LegacyPerformanceAuditReportV6,
    };
  }
  return null;
}

/**
 * Public diagnostics use an explicit aggregate-only metric allowlist. URLs,
 * hostnames, labels, timings, exceptions, and localEvidence are not copied.
 */
export const APP_HEALTH_PUBLIC_METRIC_ALLOWLIST: Readonly<
  Partial<Record<AppHealthCheckCode, readonly string[]>>
> = {
  [APP_HEALTH_CHECK_CODES.SOURCE_STATE]: ['source', 'coreAvailable'],
  [APP_HEALTH_CHECK_CODES.MANIFEST_CONTRACT]: [
    'manifestAvailable',
    'schemaSupported',
    'repoMatches',
    'tagMatches',
    'appCompatible',
    'validRunDate',
    'validGeneratedAt',
    'violations',
  ],
  [APP_HEALTH_CHECK_CODES.ASSET_DESCRIPTORS]: [
    'requiredAssets',
    'invalidRequired',
    'optionalAssets',
    'missingOptional',
    'invalidOptional',
  ],
  [APP_HEALTH_CHECK_CODES.RUN_IDENTITY]: [
    'coreAvailable',
    'validCoreRunDate',
    'comparisons',
    'mismatches',
    'indexLag',
  ],
  [APP_HEALTH_CHECK_CODES.REQUIRED_SECTIONS]: [
    'requiredSections',
    'missingSections',
    'emptySections',
    'rateRows',
  ],
  [APP_HEALTH_CHECK_CODES.RATE_VALUES]: [
    'rows',
    'invalidHeadlineRates',
    'invalidOptionalRates',
  ],
  [APP_HEALTH_CHECK_CODES.EXACT_TIER_IDENTITIES]: [
    'products',
    'missingProductKeys',
    'missingRowIdentity',
    'ineligibleExactRows',
    'ambiguousMultiTierProducts',
    'duplicateExactTiers',
  ],
  [APP_HEALTH_CHECK_CODES.TAXONOMY_ROOTS]: ['rows', 'missingTaxonomy', 'wrongRoot'],
  [APP_HEALTH_CHECK_CODES.RIBBON_RECONCILIATION]: [
    'checkedSections',
    'invalidSections',
    'declaredCountComparisons',
    'declaredCountAdjustments',
    'declaredCountMismatches',
    'quarantinedRows',
    'quarantineImpactsAvailable',
    'quarantineRateImpact',
    'quarantineProductImpact',
    'quarantineProviderImpact',
  ],
  [APP_HEALTH_CHECK_CODES.COVERAGE]: [
    'coverageAvailable',
    'totalsAvailable',
    'providersAttempted',
    'providersSucceeded',
    'providersFailed',
    'providersPartial',
    'limitations',
    'invalidCounts',
  ],
  [APP_HEALTH_CHECK_CODES.QUARANTINE]: [
    'evidenceAvailable',
    'quarantinedRows',
    'quarantinedBankHistoryPairs',
    'quarantineReasons',
  ],
  [APP_HEALTH_CHECK_CODES.FRESHNESS]: [
    'nextDueAvailable',
    'validNextDue',
    'graceMs',
    'overdueMs',
  ],
  [APP_HEALTH_CHECK_CODES.DETAILS_COMPLETENESS]: [
    'coreProducts',
    'detailProducts',
    'matchedProducts',
    'missingProducts',
    'orphanProducts',
    'coveragePercent',
    'runMatches',
    'impossibleCounts',
  ],
  [APP_HEALTH_CHECK_CODES.ASSET_AVAILABILITY]: [
    'requiredAssets',
    'requiredUnavailable',
    'requiredEmpty',
    'optionalAssets',
    'optionalUnavailable',
    'optionalEmpty',
    'optionalNotObserved',
    'mismatchedRunDates',
  ],
  [APP_HEALTH_CHECK_CODES.DISPLAY_CONTRACT]: [
    'plannedSurfaces',
    'observedSurfaces',
    'missingSurfaces',
    'unexpectedSurfaces',
    'duplicateContracts',
    'duplicateObservations',
    'duplicateEvidenceRoles',
  ],
  [APP_HEALTH_CHECK_CODES.DISPLAY_MODEL]: ['checked', 'missing', 'failed', 'warned', 'unavailable'],
  [APP_HEALTH_CHECK_CODES.DISPLAY_LIST]: ['checked', 'missing', 'failed', 'warned', 'unavailable'],
  [APP_HEALTH_CHECK_CODES.DISPLAY_VISIBILITY]: ['checked', 'missing', 'failed', 'warned', 'unavailable'],
  [APP_HEALTH_CHECK_CODES.DISPLAY_EMPTY_STATE]: ['checked', 'missing', 'failed', 'warned', 'unavailable'],
  [APP_HEALTH_CHECK_CODES.DISPLAY_LAYOUT]: ['checked', 'missing', 'failed', 'warned', 'unavailable'],
  [APP_HEALTH_CHECK_CODES.DISPLAY_CHART]: ['checked', 'missing', 'failed', 'warned', 'unavailable'],
  [APP_HEALTH_CHECK_CODES.DISPLAY_LOGO]: ['checked', 'missing', 'failed', 'warned', 'unavailable'],
  [APP_HEALTH_CHECK_CODES.NETWORK_POLICY]: [
    'localMode',
    'authorizationAttempts',
    'authorizedAttempts',
    'blockedAttempts',
    'transportCalls',
    'policyViolations',
  ],
  [APP_HEALTH_CHECK_CODES.AUDIT_PLAN]: [
    'plannedChecks',
    'storedChecks',
    'missingChecks',
    'duplicateChecks',
    'unexpectedChecks',
    'duplicatePlannedChecks',
    'reservedPlanChecks',
    'complete',
  ],
};

function publicMetrics(check: AppHealthCheck): Record<string, AppHealthMetricValue> {
  const allowed = new Set(APP_HEALTH_PUBLIC_METRIC_ALLOWLIST[check.code] ?? []);
  return Object.fromEntries(
    Object.entries(check.metrics).filter(
      ([key, value]) =>
        allowed.has(key) &&
        (value == null ||
          typeof value === 'string' ||
          typeof value === 'boolean' ||
          (typeof value === 'number' && Number.isFinite(value))),
    ),
  );
}

export function toPublicAppHealthReport(report: AppHealthReport): PublicAppHealthReport {
  return {
    schemaVersion: APP_HEALTH_SCHEMA_VERSION,
    mode: report.mode,
    summary: { ...report.summary },
    domains: report.domains.map((domain) => ({ ...domain })),
    coverage: {
      plannedChecks: report.coverage.plannedChecks,
      storedChecks: report.coverage.storedChecks,
      complete: report.coverage.complete,
    },
    checks: report.checks.map((check) => ({
      code: check.code,
      domain: check.domain,
      status: check.status,
      metrics: publicMetrics(check),
    })),
  };
}
