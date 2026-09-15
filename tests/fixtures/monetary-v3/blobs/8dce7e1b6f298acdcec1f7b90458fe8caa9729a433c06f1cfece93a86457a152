import type { RbaCalendar, RbaOutcome } from './rbaCalendar';
import {
  bankHistoryPairKey,
  quarantinedBankHistoryPairs,
  type CoreIntegrityContext,
} from './sectionIntegrity';

export type BankSpreadQuality =
  | 'complete'
  | 'missing_mortgage'
  | 'missing_savings'
  | 'missing_both';

export interface BankSpreadSeries {
  mortgage_mean: (number | null)[];
  savings_mean: (number | null)[];
  gap: (number | null)[];
  mortgage_count: number[];
  savings_count: number[];
  mortgage_hash: string[];
  savings_hash: string[];
  quality: BankSpreadQuality[];
}

export interface BankSpreadHistoryPayload {
  schema_version: 1;
  run_date: string;
  run_dates: string[];
  method: 'mean_rate_rows_per_product_then_mean_products_per_provider';
  cohorts: { mortgage: string; savings: string };
  banks: Record<string, BankSpreadSeries>;
}

export interface BankSpreadPlotPoint {
  date: string;
  runIndex: number;
  gapPp: number;
  mortgagePct: number;
  savingsPct: number;
  membershipChanged: boolean;
}

export interface BankSpreadPlotLine {
  provider: string;
  points: BankSpreadPlotPoint[];
}

export interface BankSpreadDecisionMarker {
  date: string;
  outcome: RbaOutcome;
  rate: number;
  deltaBps: number;
}

export interface BankSpreadChartModel {
  dates: string[];
  lines: BankSpreadPlotLine[];
  decisions: BankSpreadDecisionMarker[];
  minGapPp: number;
  maxGapPp: number;
}

const QUALITY = new Set<BankSpreadQuality>([
  'complete', 'missing_mortgage', 'missing_savings', 'missing_both',
]);
const YMD = /^\d{4}-\d{2}-\d{2}$/;

function finiteOrNull(value: unknown): number | null | undefined {
  return value === null ? null : typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function normalizeSeries(value: unknown, length: number): BankSpreadSeries | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  const numberKeys = ['mortgage_mean', 'savings_mean', 'gap'] as const;
  const countKeys = ['mortgage_count', 'savings_count'] as const;
  const hashKeys = ['mortgage_hash', 'savings_hash'] as const;
  if (![...numberKeys, ...countKeys, ...hashKeys, 'quality'].every((key) => Array.isArray(row[key]) && (row[key] as unknown[]).length === length)) return null;
  const numbers = Object.fromEntries(numberKeys.map((key) => [key, (row[key] as unknown[]).map(finiteOrNull)]));
  if (numberKeys.some((key) => (numbers[key] as (number | null | undefined)[]).some((item) => item === undefined))) return null;
  const counts = Object.fromEntries(countKeys.map((key) => [key, row[key] as unknown[]]));
  if (countKeys.some((key) => (counts[key] as unknown[]).some((item) => !Number.isInteger(item) || (item as number) < 0))) return null;
  const hashes = Object.fromEntries(hashKeys.map((key) => [key, row[key] as unknown[]]));
  if (hashKeys.some((key) => (hashes[key] as unknown[]).some((item) => typeof item !== 'string'))) return null;
  const quality = row.quality as unknown[];
  if (quality.some((item) => !QUALITY.has(item as BankSpreadQuality))) return null;

  for (let index = 0; index < length; index += 1) {
    const mortgage = (numbers.mortgage_mean as (number | null)[])[index];
    const savings = (numbers.savings_mean as (number | null)[])[index];
    const gap = (numbers.gap as (number | null)[])[index];
    const complete = quality[index] === 'complete';
    const expectedQuality: BankSpreadQuality = mortgage != null
      ? savings != null ? 'complete' : 'missing_savings'
      : savings != null ? 'missing_mortgage' : 'missing_both';
    if (quality[index] !== expectedQuality) return null;
    if (complete !== (mortgage != null && savings != null && gap != null)) return null;
    if (complete && Math.abs((mortgage! - savings!) - gap!) > 0.000002) return null;
    if (!complete && gap != null) return null;
    const mortgageCount = (counts.mortgage_count as number[])[index];
    const savingsCount = (counts.savings_count as number[])[index];
    const mortgageHash = (hashes.mortgage_hash as string[])[index];
    const savingsHash = (hashes.savings_hash as string[])[index];
    if ((mortgage != null) !== (mortgageCount > 0 && mortgageHash.length > 0)) return null;
    if ((savings != null) !== (savingsCount > 0 && savingsHash.length > 0)) return null;
  }
  return {
    mortgage_mean: numbers.mortgage_mean as (number | null)[],
    savings_mean: numbers.savings_mean as (number | null)[],
    gap: numbers.gap as (number | null)[],
    mortgage_count: counts.mortgage_count as number[],
    savings_count: counts.savings_count as number[],
    mortgage_hash: hashes.mortgage_hash as string[],
    savings_hash: hashes.savings_hash as string[],
    quality: quality as BankSpreadQuality[],
  };
}

export function normalizeBankSpreadHistoryPayload(value: unknown): BankSpreadHistoryPayload | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const runDate = typeof raw.run_date === 'string' && YMD.test(raw.run_date) ? raw.run_date : '';
  const dates = Array.isArray(raw.run_dates) ? raw.run_dates : [];
  if (raw.schema_version !== 1 || !YMD.test(runDate) || !dates.length) return null;
  if (dates.some((date) => typeof date !== 'string' || !YMD.test(date) || date > runDate)) return null;
  if (new Set(dates).size !== dates.length || dates.some((date, index) => index > 0 && date <= dates[index - 1])) return null;
  if (raw.method !== 'mean_rate_rows_per_product_then_mean_products_per_provider') return null;
  if (!raw.cohorts || typeof raw.cohorts !== 'object' || !raw.banks || typeof raw.banks !== 'object') return null;
  const cohorts = raw.cohorts as Record<string, unknown>;
  if (typeof cohorts.mortgage !== 'string' || typeof cohorts.savings !== 'string') return null;
  const banks: Record<string, BankSpreadSeries> = {};
  for (const [provider, series] of Object.entries(raw.banks as Record<string, unknown>)) {
    const normalized = provider.trim() && normalizeSeries(series, dates.length);
    if (!normalized) return null;
    banks[provider] = normalized;
  }
  if (!Object.keys(banks).length) return null;
  return { schema_version: 1, run_date: runDate, run_dates: dates as string[], method: raw.method, cohorts: cohorts as BankSpreadHistoryPayload['cohorts'], banks };
}

/**
 * Pre-aggregated spread rows cannot be repaired after a provider/section cohort
 * has been quarantined. Fail closed without matching core provenance and remove
 * the whole provider line when either side of its advertised gap is tainted.
 */
export function filterBankSpreadHistoryForIntegrity(
  payload: BankSpreadHistoryPayload | null | undefined,
  integrity: CoreIntegrityContext | null | undefined,
): BankSpreadHistoryPayload | null {
  if (
    !payload ||
    !integrity ||
    integrity.runDate !== payload.run_date ||
    integrity.core.run_date !== payload.run_date
  ) return null;
  const quarantined = quarantinedBankHistoryPairs(integrity);
  if (!quarantined.size) return payload;
  const banks = Object.fromEntries(
    Object.entries(payload.banks).filter(([provider]) =>
      !quarantined.has(bankHistoryPairKey(provider, 'Mortgage')) &&
      !quarantined.has(bankHistoryPairKey(provider, 'Savings')),
    ),
  );
  return Object.keys(banks).length ? { ...payload, banks } : null;
}

export function buildBankSpreadChartModel(
  payload: BankSpreadHistoryPayload,
  calendar: RbaCalendar | null | undefined,
): BankSpreadChartModel {
  const lines = Object.entries(payload.banks)
    .map(([provider, series]) => {
      const points: BankSpreadPlotPoint[] = [];
      let previousCompleteMembership = '';
      for (let index = 0; index < payload.run_dates.length; index += 1) {
        const gap = series.gap[index];
        const mortgage = series.mortgage_mean[index];
        const savings = series.savings_mean[index];
        if (series.quality[index] !== 'complete' || gap == null || mortgage == null || savings == null) continue;
        const current = `${series.mortgage_hash[index]}:${series.savings_hash[index]}`;
        points.push({
          date: payload.run_dates[index], runIndex: index, gapPp: gap * 100,
          mortgagePct: mortgage * 100, savingsPct: savings * 100,
          membershipChanged: Boolean(previousCompleteMembership && current !== previousCompleteMembership),
        });
        previousCompleteMembership = current;
      }
      return { provider, points };
    })
    .filter((line) => line.points.length > 0)
    .sort((a, b) => a.provider.localeCompare(b.provider));
  const gaps = lines.flatMap((line) => line.points.map((point) => point.gapPp));
  const padding = Math.max(0.05, ((Math.max(...gaps) - Math.min(...gaps)) || 0.1) * 0.08);
  const start = payload.run_dates[0];
  const end = payload.run_dates[payload.run_dates.length - 1];
  const decisions = (calendar?.decisions ?? [])
    .filter((decision) => decision.date >= start && decision.date <= end)
    .map((decision) => ({ date: decision.date, outcome: decision.outcome, rate: decision.rate, deltaBps: decision.delta_bps }));
  return {
    dates: payload.run_dates, lines, decisions,
    minGapPp: gaps.length ? Math.min(...gaps) - padding : 0,
    maxGapPp: gaps.length ? Math.max(...gaps) + padding : 1,
  };
}
