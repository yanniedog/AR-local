import type {
  CorePayload,
  ProductDetail,
  SectionKey,
} from '../types';
import { SECTION_KEYS } from '../types';
import { normalizeTimelineDates, parseYmd } from './bankHistoryTransform';
import { toFraction, visibleAccountRows } from './format';
import { getSuitabilityAllowed, getSuitabilityRevision } from './suitabilityGate';
import {
  bankHistoryPairKey,
  quarantinedBankHistoryPairs,
  type CoreIntegrityContext,
} from './sectionIntegrity';
import {
  DEFAULT_PASS_THROUGH_WINDOW_DAYS,
  MOVE_DIRS,
  type BankInsightsPayload,
  type BankMoveDir,
  type BankRateEvent,
  type BankSectionSeries,
  type BehaviourDirectionSummary,
  type BehaviourProviderSummary,
  type BehaviourSectionSummary,
  type PassThroughConfidence,
} from './bankInsightsTypes';

export type {
  BankInsightsPayload,
  BankMoveDir,
  BankRateEvent,
  BankSectionSeries,
  BehaviourDirectionSummary,
  BehaviourProviderSummary,
  BehaviourSectionSummary,
  PassThroughConfidence,
} from './bankInsightsTypes';

export {
  comparePassThroughRows,
  decisionsFromRbaSeries,
  passThroughDaysLabel,
  rbaPassThrough,
  rbaPassThroughDecisionList,
  rbaPassThroughMultiSection,
  rbaResponseWindowList,
  resolvePassThroughDecisions,
  scorablePassThroughDecisions,
} from './bankPassThrough';
export type {
  MultiSectionPassThroughModel,
  MultiSectionPassThroughRow,
  PassThroughModel,
  PassThroughOpts,
  PassThroughRow,
  PassThroughSourceDecision,
  PassThroughStatus,
  RbaDecisionRef,
  RbaResponseWindowRef,
} from './bankPassThrough';

export {
  bankEventMedianContext,
  bankSnapshotAt,
  bankTrendChartModel,
  eventsOnDate,
  marketPulse,
  recentBankEvents,
  topMovers,
} from './bankInsightsQuery';
export type {
  BankEventRateContext,
  BankSnapshotRow,
  BankTrendModel,
  MarketPulse,
  MoverRow,
  RecentEventsOpts,
} from './bankInsightsQuery';

/**
 * Apply the app's shared standard-product gate to pre-aggregated bank insights.
 *
 * The history feed has no product keys, so an aggregate cannot be split safely
 * after download. Standard-only mode retains complete history only for
 * provider/sections whose current catalogue is entirely visible. Mixed
 * catalogues get a product-row-derived snapshot at the current run date, so the
 * Explorer remains useful without leaking their unfilterable historical rates.
 */
function explorerVisibleRows(
  rows: CorePayload['sections'][SectionKey]['rates'],
  detailsProducts?: Record<string, ProductDetail> | null,
) {
  return visibleAccountRows(rows, false, detailsProducts);
}

function median(values: number[]): number {
  const sorted = values.slice().sort((a, b) => a - b);
  const middle = sorted.length >> 1;
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function currentStandardSeries(
  rows: CorePayload['sections'][SectionKey]['rates'],
  section: SectionKey,
  length: number,
  currentIndex: number,
): BankSectionSeries | null {
  if (currentIndex < 0) return null;
  const values = rows
    .map((row) => toFraction(row.rate))
    .filter((value): value is number => value != null && value > 0);
  if (!values.length) return null;

  const medians: (number | null)[] = Array(length).fill(null);
  const best: (number | null)[] = Array(length).fill(null);
  const count: (number | null)[] = Array(length).fill(null);
  medians[currentIndex] = median(values);
  best[currentIndex] = section === 'Mortgage' ? Math.min(...values) : Math.max(...values);
  count[currentIndex] = values.length;
  return { median: medians, best, count };
}

let suitabilityFilterCache: {
  payload: BankInsightsPayload;
  core: CorePayload;
  detailsProducts: Record<string, ProductDetail> | null | undefined;
  integrity: CoreIntegrityContext | null | undefined;
  revision: number;
  result: BankInsightsPayload | null;
} | null = null;

function filterBankInsightsForSectionIntegrity(
  payload: BankInsightsPayload,
  integrity: CoreIntegrityContext | null | undefined,
): BankInsightsPayload {
  const quarantinedPairs = quarantinedBankHistoryPairs(integrity);
  if (!quarantinedPairs.size) return payload;

  const banks: BankInsightsPayload['banks'] = {};
  for (const [provider, sections] of Object.entries(payload.banks)) {
    const retained = Object.fromEntries(
      Object.entries(sections).filter(([section]) =>
        !quarantinedPairs.has(bankHistoryPairKey(provider, section as SectionKey)),
      ),
    ) as Partial<Record<SectionKey, BankSectionSeries>>;
    if (Object.keys(retained).length) banks[provider] = retained;
  }

  const behaviour: BankInsightsPayload['behaviour'] = {};
  for (const section of SECTION_KEYS) {
    const summary = payload.behaviour?.[section];
    if (!summary) continue;
    const providers = Object.fromEntries(
      Object.entries(summary.providers).filter(([provider]) =>
        !quarantinedPairs.has(bankHistoryPairKey(provider, section)),
      ),
    );
    if (Object.keys(providers).length) behaviour[section] = { ...summary, providers };
  }

  return {
    ...payload,
    banks,
    events: payload.events.filter((event) =>
      !quarantinedPairs.has(bankHistoryPairKey(event.provider, event.section)),
    ),
    behaviour: Object.keys(behaviour).length ? behaviour : undefined,
  };
}

export function filterBankInsightsForSuitability(
  payload: BankInsightsPayload | null | undefined,
  core: CorePayload | null | undefined,
  includeNonStandard: boolean,
  detailsProducts?: Record<string, ProductDetail> | null,
  suitabilityRevision = getSuitabilityRevision(),
  integrity?: CoreIntegrityContext | null,
): BankInsightsPayload | null {
  if (!payload) return null;
  if (!core) return null;
  const integrityPayload = filterBankInsightsForSectionIntegrity(payload, integrity);
  if (includeNonStandard) return integrityPayload;
  if (
    suitabilityFilterCache?.payload === payload &&
    suitabilityFilterCache.core === core &&
    suitabilityFilterCache.detailsProducts === detailsProducts &&
    suitabilityFilterCache.integrity === integrity &&
    suitabilityFilterCache.revision === suitabilityRevision
  ) return suitabilityFilterCache.result;
  if (getSuitabilityAllowed()?.size === 0) {
    suitabilityFilterCache = {
      payload,
      core,
      detailsProducts,
      integrity,
      revision: suitabilityRevision,
      result: null,
    };
    return null;
  }

  const historicalPairs = new Set<string>();
  const pairKey = bankHistoryPairKey;
  const visibleByPair = new Map<
    string,
    CorePayload['sections'][SectionKey]['rates']
  >();

  for (const section of SECTION_KEYS) {
    const rows = core.sections[section]?.rates ?? [];
    const visibleRows = explorerVisibleRows(rows, detailsProducts);
    const visibleKeys = new Set(visibleRows.map((row) => row.product_key));
    const byProvider = new Map<string, typeof rows>();
    const visibleByProvider = new Map<string, typeof rows>();
    for (const row of rows) {
      const providerRows = byProvider.get(row.provider);
      if (providerRows) providerRows.push(row);
      else byProvider.set(row.provider, [row]);
    }
    for (const row of visibleRows) {
      const providerRows = visibleByProvider.get(row.provider);
      if (providerRows) providerRows.push(row);
      else visibleByProvider.set(row.provider, [row]);
    }
    for (const [provider, providerRows] of byProvider) {
      const key = pairKey(provider, section);
      const visibleProviderRows = visibleByProvider.get(provider) ?? [];
      if (visibleProviderRows.length) visibleByPair.set(key, visibleProviderRows);
      if (
        providerRows.length > 0 &&
        providerRows.every((row) => visibleKeys.has(row.product_key))
      ) {
        historicalPairs.add(key);
      }
    }
  }

  const banks: BankInsightsPayload['banks'] = {};
  const currentIndex = integrityPayload.run_dates.indexOf(core.run_date);
  for (const [provider, sections] of Object.entries(integrityPayload.banks)) {
    const filteredSections: Partial<Record<SectionKey, BankSectionSeries>> = {};
    for (const section of SECTION_KEYS) {
      const series = sections[section];
      if (!series) continue;
      const key = pairKey(provider, section);
      if (historicalPairs.has(key)) {
        filteredSections[section] = series;
        continue;
      }
      const current = currentStandardSeries(
        visibleByPair.get(key) ?? [],
        section,
        integrityPayload.run_dates.length,
        currentIndex,
      );
      if (current) {
        filteredSections[section] = current;
      }
    }
    if (Object.keys(filteredSections).length) banks[provider] = filteredSections;
  }

  const behaviour: BankInsightsPayload['behaviour'] = {};
  for (const section of SECTION_KEYS) {
    const summary = integrityPayload.behaviour?.[section];
    if (!summary) continue;
    const providers = Object.fromEntries(
      Object.entries(summary.providers).filter(([provider]) =>
        historicalPairs.has(pairKey(provider, section)),
      ),
    );
    if (Object.keys(providers).length) {
      behaviour[section] = { ...summary, providers };
    }
  }

  const result: BankInsightsPayload = {
    ...integrityPayload,
    banks,
    events: integrityPayload.events.filter((event) =>
      historicalPairs.has(pairKey(event.provider, event.section)),
    ),
    behaviour: Object.keys(behaviour).length ? behaviour : undefined,
  };
  suitabilityFilterCache = {
    payload,
    core,
    detailsProducts,
    integrity,
    revision: suitabilityRevision,
    result,
  };
  return result;
}

function numberOrNull(value: unknown): number | null {
  if (value == null || value === '') return null; // Number(null) === 0 — keep gaps as gaps
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function alignedSeries(raw: unknown, length: number): (number | null)[] | null {
  if (!Array.isArray(raw)) return null;
  const out: (number | null)[] = [];
  for (let i = 0; i < length; i += 1) {
    out.push(i < raw.length ? numberOrNull(raw[i]) : null);
  }
  return out;
}

function emptyBehaviourDirection(): BehaviourDirectionSummary {
  return {
    n: 0,
    days_median: null,
    bps_median: null,
    ratio_median: null,
    confidence: 'insufficient',
  };
}

function normalizeBehaviourDirection(raw: unknown): BehaviourDirectionSummary {
  if (!raw || typeof raw !== 'object') return emptyBehaviourDirection();
  const obj = raw as Record<string, unknown>;
  const n = Math.max(0, Math.round(numberOrNull(obj.n) ?? 0));
  const confidenceRaw = typeof obj.confidence === 'string' ? obj.confidence : '';
  const confidence: PassThroughConfidence =
    confidenceRaw === 'early' ||
    confidenceRaw === 'emerging' ||
    confidenceRaw === 'established' ||
    confidenceRaw === 'insufficient'
      ? confidenceRaw
      : n >= 10
        ? 'established'
        : n >= 6
          ? 'emerging'
          : n >= 3
            ? 'early'
            : 'insufficient';
  return {
    n,
    days_median: numberOrNull(obj.days_median),
    bps_median: numberOrNull(obj.bps_median),
    ratio_median: numberOrNull(obj.ratio_median),
    confidence,
  };
}

function normalizeBehaviour(
  raw: unknown,
): Partial<Record<SectionKey, BehaviourSectionSummary>> | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const out: Partial<Record<SectionKey, BehaviourSectionSummary>> = {};
  for (const [section, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!(SECTION_KEYS as readonly string[]).includes(section) || !value || typeof value !== 'object') {
      continue;
    }
    const obj = value as Record<string, unknown>;
    const providersRaw = obj.providers;
    const providers: Record<string, BehaviourProviderSummary> = {};
    if (providersRaw && typeof providersRaw === 'object') {
      for (const [provider, dirs] of Object.entries(providersRaw as Record<string, unknown>)) {
        if (!provider || !dirs || typeof dirs !== 'object') continue;
        const d = dirs as Record<string, unknown>;
        providers[provider] = {
          hike: normalizeBehaviourDirection(d.hike),
          cut: normalizeBehaviourDirection(d.cut),
        };
      }
    }
    out[section as SectionKey] = {
      section: section as SectionKey,
      window_days: Math.max(1, Math.round(numberOrNull(obj.window_days) ?? DEFAULT_PASS_THROUGH_WINDOW_DAYS)),
      providers,
    };
  }
  return Object.keys(out).length ? out : undefined;
}

/** Drop corrupt bank-history JSON before it reaches insights/chart code. */
export function normalizeBankInsightsPayload(raw: unknown): BankInsightsPayload | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  const run_date = typeof obj.run_date === 'string' ? obj.run_date.slice(0, 10) : '';
  if (!run_date) return null;

  const run_dates = normalizeTimelineDates(
    Array.isArray(obj.run_dates)
      ? obj.run_dates.map((d) => (typeof d === 'string' ? d.slice(0, 10) : ''))
      : [],
  );
  if (!run_dates.length) return null;

  const banksRaw = obj.banks;
  if (!banksRaw || typeof banksRaw !== 'object') return null;
  const banks: BankInsightsPayload['banks'] = {};
  for (const [provider, sectionsRaw] of Object.entries(banksRaw as Record<string, unknown>)) {
    if (!provider || !sectionsRaw || typeof sectionsRaw !== 'object') continue;
    const sections: Partial<Record<SectionKey, BankSectionSeries>> = {};
    for (const [key, value] of Object.entries(sectionsRaw as Record<string, unknown>)) {
      if (!(SECTION_KEYS as readonly string[]).includes(key) || !value || typeof value !== 'object') continue;
      const series = value as Record<string, unknown>;
      const median = alignedSeries(series.median, run_dates.length);
      const best = alignedSeries(series.best, run_dates.length);
      const count = alignedSeries(series.count, run_dates.length);
      if (!median || !best || !median.some((v) => v != null)) continue;
      sections[key as SectionKey] = {
        median,
        best,
        count: count ?? median.map(() => null),
      };
    }
    if (Object.keys(sections).length) banks[provider] = sections;
  }
  if (!Object.keys(banks).length) return null;

  const events: BankRateEvent[] = [];
  if (Array.isArray(obj.events)) {
    for (const item of obj.events) {
      if (!item || typeof item !== 'object') continue;
      const e = item as Record<string, unknown>;
      const date = typeof e.date === 'string' ? e.date.slice(0, 10) : '';
      const provider = typeof e.provider === 'string' ? e.provider : '';
      const section = typeof e.section === 'string' ? e.section : '';
      const dir = typeof e.dir === 'string' ? e.dir : '';
      const avg_bps = numberOrNull(e.avg_bps);
      if (
        !parseYmd(date) ||
        !provider ||
        !(SECTION_KEYS as readonly string[]).includes(section) ||
        !(MOVE_DIRS as readonly string[]).includes(dir) ||
        avg_bps == null
      ) {
        continue;
      }
      events.push({
        date,
        provider,
        section: section as SectionKey,
        dir: dir as BankMoveDir,
        moved: Math.max(0, Math.round(numberOrNull(e.moved) ?? 0)),
        total: Math.max(0, Math.round(numberOrNull(e.total) ?? 0)),
        avg_bps,
      });
    }
  }

  return {
    schema_version: typeof obj.schema_version === 'number' ? obj.schema_version : 1,
    run_date,
    run_dates,
    banks,
    events,
    behaviour: normalizeBehaviour(obj.behaviour),
  };
}
