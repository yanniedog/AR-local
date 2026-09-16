import type {
  CorePayload,
  Manifest,
  PayloadSource,
  SectionKey,
} from '../../types';

export const APP_HEALTH_SCHEMA_VERSION = 7 as const;

export const APP_HEALTH_DOMAINS = [
  'performance',
  'data-integrity',
  'data-completeness',
  'asset-availability',
  'display-completeness',
  'storage',
  'network',
  'update',
] as const;

export type AppHealthDomain = (typeof APP_HEALTH_DOMAINS)[number];
export type AppHealthAuditMode = 'local' | 'live-source';
export type AppHealthStatus = 'pass' | 'warn' | 'fail' | 'unavailable' | 'not-run';
export type AppHealthOverall = 'healthy' | 'attention' | 'bottleneck';
export type AppHealthMetricValue = string | number | boolean | null;

export const APP_HEALTH_CHECK_CODES = {
  SOURCE_STATE: 'data-source-state',
  MANIFEST_CONTRACT: 'manifest-contract',
  CORE_SCHEMA: 'core-schema',
  ASSET_DESCRIPTORS: 'asset-descriptors',
  RUN_IDENTITY: 'payload-run-identity',
  REQUIRED_SECTIONS: 'required-sections',
  RATE_VALUES: 'rate-values',
  EXACT_TIER_IDENTITIES: 'exact-tier-identities',
  TAXONOMY_ROOTS: 'taxonomy-roots',
  RIBBON_RECONCILIATION: 'ribbon-reconciliation',
  COVERAGE: 'coverage-reconciliation',
  QUARANTINE: 'quarantine-impact',
  FRESHNESS: 'freshness-window',
  DETAILS_COMPLETENESS: 'details-completeness',
  ASSET_AVAILABILITY: 'asset-availability',
  DISPLAY_CONTRACT: 'display-contract',
  DISPLAY_MODEL: 'display-model',
  DISPLAY_LIST: 'display-list',
  DISPLAY_VISIBILITY: 'display-visible',
  DISPLAY_EMPTY_STATE: 'display-empty-state',
  DISPLAY_LAYOUT: 'display-layout',
  DISPLAY_CHART: 'display-chart',
  DISPLAY_LOGO: 'display-logo',
  NETWORK_POLICY: 'network-policy',
  AUDIT_PLAN: 'audit-plan-integrity',
} as const;

/** Fixed run contract. A missing producer must remain visible as a plan failure. */
export const APP_HEALTH_EXPECTED_CHECK_IDS = [
  APP_HEALTH_CHECK_CODES.SOURCE_STATE,
  APP_HEALTH_CHECK_CODES.MANIFEST_CONTRACT,
  APP_HEALTH_CHECK_CODES.CORE_SCHEMA,
  APP_HEALTH_CHECK_CODES.ASSET_DESCRIPTORS,
  APP_HEALTH_CHECK_CODES.RUN_IDENTITY,
  APP_HEALTH_CHECK_CODES.REQUIRED_SECTIONS,
  APP_HEALTH_CHECK_CODES.RATE_VALUES,
  APP_HEALTH_CHECK_CODES.EXACT_TIER_IDENTITIES,
  APP_HEALTH_CHECK_CODES.TAXONOMY_ROOTS,
  APP_HEALTH_CHECK_CODES.RIBBON_RECONCILIATION,
  APP_HEALTH_CHECK_CODES.COVERAGE,
  APP_HEALTH_CHECK_CODES.QUARANTINE,
  APP_HEALTH_CHECK_CODES.FRESHNESS,
  APP_HEALTH_CHECK_CODES.DETAILS_COMPLETENESS,
  APP_HEALTH_CHECK_CODES.ASSET_AVAILABILITY,
  APP_HEALTH_CHECK_CODES.DISPLAY_CONTRACT,
  APP_HEALTH_CHECK_CODES.DISPLAY_MODEL,
  APP_HEALTH_CHECK_CODES.DISPLAY_LIST,
  APP_HEALTH_CHECK_CODES.DISPLAY_VISIBILITY,
  APP_HEALTH_CHECK_CODES.DISPLAY_EMPTY_STATE,
  APP_HEALTH_CHECK_CODES.DISPLAY_LAYOUT,
  APP_HEALTH_CHECK_CODES.DISPLAY_CHART,
  APP_HEALTH_CHECK_CODES.DISPLAY_LOGO,
  APP_HEALTH_CHECK_CODES.NETWORK_POLICY,
] as const;

export type AppHealthCheckCode =
  (typeof APP_HEALTH_CHECK_CODES)[keyof typeof APP_HEALTH_CHECK_CODES];

export interface AppHealthCheck {
  /** Unique within one report. Prefer the stable check code for aggregate checks. */
  id: string;
  code: AppHealthCheckCode;
  label: string;
  domain: AppHealthDomain;
  status: AppHealthStatus;
  metrics: Record<string, AppHealthMetricValue>;
  summary?: string;
  /** Never included in public diagnostics. May contain local-only identifiers. */
  localEvidence?: Readonly<Record<string, unknown>>;
}

export const APP_HEALTH_ASSET_KEYS = [
  'core',
  'details',
  'search_index',
  'history_banks',
  'bank_history',
  'bank_spread_history',
  'rba_calendar',
] as const;

export type AppHealthAssetKey = (typeof APP_HEALTH_ASSET_KEYS)[number];

export interface AppHealthSourceContract {
  readonly contract: 'v1';
  readonly repo: string;
  readonly rollingTag: string;
  readonly manifestUrl: string;
  readonly datesIndexUrl: string;
  readonly datedTagPrefix: string;
  readonly supportedManifestSchemas: readonly number[];
  readonly supportedCoreSchemas: readonly number[];
  readonly requiredSections: readonly SectionKey[];
  readonly taxonomyRoots: Readonly<Record<SectionKey, string>>;
  readonly requiredAssets: readonly AppHealthAssetKey[];
  readonly optionalAssets: readonly AppHealthAssetKey[];
  /** Grace after the producer-declared next_due_utc before data is stale. */
  readonly freshnessGraceMs: number;
}

export type AppHealthAssetObservationState =
  | 'ready'
  | 'missing'
  | 'failed'
  | 'not-requested';

export interface AppHealthAssetObservation {
  state: AppHealthAssetObservationState;
  runDate?: string | null;
  itemCount?: number | null;
}

export interface AppHealthDatesIndexObservation {
  dates: readonly string[];
  latestRunDate?: string | null;
}

export interface AppHealthDetailsObservation {
  runDate: string;
  productCount: number;
  /** Exact key intersection when the caller has both core and details records. */
  matchedProductCount?: number;
  /** Detail records that do not correspond to a core product key. */
  orphanProductCount?: number;
}

export interface AppHealthQuarantineObservation {
  rowsByReason: Readonly<Record<string, number>>;
  bankHistoryPairs: number;
  /** Exact count changes introduced by client-side quarantine normalization. */
  countImpacts?: Readonly<{
    rates: number;
    products: number;
    providers: number;
  }>;
}

export interface AppHealthDataSnapshot {
  source: PayloadSource | 'unavailable';
  core: CorePayload | null;
  manifest: Manifest | null;
  appVersion?: string | null;
  datesIndex?: AppHealthDatesIndexObservation | null;
  details?: AppHealthDetailsObservation | null;
  assets?: Partial<Record<AppHealthAssetKey, AppHealthAssetObservation>>;
  quarantine?: AppHealthQuarantineObservation | null;
}

export type AppHealthDisplayEvidence =
  | {
      role: 'model';
      sourceCount: number;
      modelCount: number;
    }
  | {
      role: 'list';
      modelCount: number;
      renderedCount: number;
    }
  | {
      role: 'visible';
      expectedMinimum: number;
      visibleCount: number;
    }
  | {
      role: 'empty-state';
      expected: boolean;
      rendered: boolean;
    }
  | {
      role: 'critical-layout';
      measured: boolean;
      /** Optional independent viewport/content comparison; absence is not invented as false. */
      clipped?: boolean | null;
      width: number | null;
      height: number | null;
    }
  | {
      role: 'chart';
      modelPointCount: number;
      renderedPointCount: number;
      accessibleSummary: boolean;
    }
  | {
      role: 'logo';
      expectedCount: number;
      decodedCount: number;
      fallbackCount: number;
      missingCount: number;
    };

export type AppHealthDisplayRole = AppHealthDisplayEvidence['role'];

export interface AppHealthSurfaceContract {
  id: string;
  requiredRoles: readonly AppHealthDisplayRole[];
  /** A deliberately empty model is healthy only when this is true and an empty state renders. */
  allowsIntentionalEmpty?: boolean;
  chartRequired?: boolean;
  logosRequired?: boolean;
}

export interface AppHealthSurfaceObservation {
  surfaceId: string;
  evidence: readonly AppHealthDisplayEvidence[];
}

export type AppHealthNetworkPurpose = 'manifest' | 'dates-index' | 'asset';

export interface AppHealthNetworkDecision {
  allowed: boolean;
  reason: 'local-mode' | 'allowlisted' | 'not-allowlisted' | 'invalid-url' | 'inactive-session';
}

export interface AppHealthNetworkSnapshot {
  mode: AppHealthAuditMode;
  authorizationAttempts: number;
  authorizedAttempts: number;
  blockedAttempts: number;
  transportCalls: number;
  policyViolations: number;
}

export interface AppHealthDomainSummary {
  domain: AppHealthDomain;
  overall: AppHealthOverall;
  pass: number;
  warn: number;
  fail: number;
  unavailable: number;
  notRun: number;
  total: number;
}

export interface AppHealthSummary {
  overall: AppHealthOverall;
  pass: number;
  warn: number;
  fail: number;
  unavailable: number;
  notRun: number;
  total: number;
  coveragePercent: number | null;
}

export interface AppHealthCoverage {
  plannedChecks: number;
  storedChecks: number;
  missingPlannedCheckIds: string[];
  duplicateStoredCheckIds: string[];
  unexpectedStoredCheckIds: string[];
  complete: boolean;
}

export interface AppHealthReport {
  schemaVersion: typeof APP_HEALTH_SCHEMA_VERSION;
  sessionId: string;
  mode: AppHealthAuditMode;
  startedAt: string;
  finishedAt: string;
  checks: AppHealthCheck[];
  domains: AppHealthDomainSummary[];
  summary: AppHealthSummary;
  coverage: AppHealthCoverage;
  limitations: string[];
}

export interface FinalizeAppHealthReportInput {
  sessionId: string;
  mode: AppHealthAuditMode;
  startedAt: string;
  finishedAt: string;
  checks: readonly AppHealthCheck[];
  plannedCheckIds: readonly string[];
  limitations?: readonly string[];
}

export interface LegacyPerformanceAuditReportV6 {
  schemaVersion: 6;
  sessionId: string;
  startedAt: string;
  finishedAt: string;
  checks: readonly unknown[];
  summary: Readonly<Record<string, unknown>>;
  [key: string]: unknown;
}

export type ReadableAppHealthReport =
  | { kind: 'app-health-v7'; report: AppHealthReport }
  | { kind: 'performance-audit-v6'; report: LegacyPerformanceAuditReportV6 };

export interface PublicAppHealthCheck {
  code: AppHealthCheckCode;
  domain: AppHealthDomain;
  status: AppHealthStatus;
  metrics: Record<string, AppHealthMetricValue>;
}

export interface PublicAppHealthReport {
  schemaVersion: typeof APP_HEALTH_SCHEMA_VERSION;
  mode: AppHealthAuditMode;
  summary: AppHealthSummary;
  domains: AppHealthDomainSummary[];
  coverage: Pick<AppHealthCoverage, 'plannedChecks' | 'storedChecks' | 'complete'>;
  checks: PublicAppHealthCheck[];
}
