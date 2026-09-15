import type { BankHistoryPoint, SectionKey } from '../types';
import { parseYmd } from './bankHistoryTransform';
import { debugLog } from '../lib/debugLog';
import {
  DAY_MS,
  type BankInsightsPayload,
  type BankRateEvent,
} from './bankInsightsTypes';

function sortEventsDesc(events: BankRateEvent[]): BankRateEvent[] {
  return events
    .slice()
    .sort((a, b) => (a.date === b.date ? a.provider.localeCompare(b.provider) : b.date.localeCompare(a.date)));
}

export interface RecentEventsOpts {
  sections?: SectionKey[];
  provider?: string;
  limit?: number;
}

/** Newest-first provider rate-move feed. */
export function recentBankEvents(
  payload: BankInsightsPayload | null | undefined,
  opts: RecentEventsOpts = {},
): BankRateEvent[] {
  if (!payload?.events?.length) return [];
  const sections = opts.sections?.length ? new Set(opts.sections) : null;
  const filtered = payload.events.filter(
    (e) => (!sections || sections.has(e.section)) && (!opts.provider || e.provider === opts.provider),
  );
  const sorted = sortEventsDesc(filtered);
  return opts.limit && opts.limit > 0 ? sorted.slice(0, opts.limit) : sorted;
}

/** Lender moves that contributed to a Pulse column on `date`, largest first. */
export function eventsOnDate(
  payload: BankInsightsPayload | null | undefined,
  section: SectionKey,
  date: string,
): BankRateEvent[] {
  if (!payload?.events?.length) return [];
  const day = String(date || '').slice(0, 10);
  if (!day) return [];
  return payload.events
    .filter((event) => event.section === section && event.date === day)
    .slice()
    .sort(
      (a, b) =>
        Math.abs(b.avg_bps) - Math.abs(a.avg_bps) ||
        a.provider.localeCompare(b.provider),
    );
}

export interface BankEventRateContext {
  /** Provider median on the day before the move (fraction). */
  before: number;
  /** Provider median on the move date (fraction). */
  after: number;
  /** Signed median change in basis points. */
  medianBps: number;
}

/**
 * Median before→after rates for a bank-move event, giving the headline bps
 * figure a concrete rate context (e.g. 5.99% → 5.94%).
 */
export function bankEventMedianContext(
  payload: BankInsightsPayload | null | undefined,
  event: Pick<BankRateEvent, 'provider' | 'section' | 'date'>,
): BankEventRateContext | null {
  const series = payload?.banks?.[event.provider]?.[event.section]?.median;
  if (!payload || !series?.length) return null;
  const idx = payload.run_dates.indexOf(event.date);
  if (idx < 0) return null;
  const after = series[idx];
  if (after == null) return null;
  const before = lastNonNull(series, idx - 1);
  if (before == null) return null;
  return {
    before,
    after,
    medianBps: Math.round((after - before) * 10000 * 10) / 10,
  };
}

function windowStartIndex(run_dates: string[], windowDays: number): number {
  const anchor = parseYmd(run_dates[run_dates.length - 1] ?? '');
  if (anchor == null) return 0;
  const cutoff = anchor - windowDays * DAY_MS;
  for (let i = 0; i < run_dates.length; i += 1) {
    const ts = parseYmd(run_dates[i]);
    if (ts != null && ts >= cutoff) return i;
  }
  return run_dates.length;
}

function firstNonNull(values: (number | null)[], from: number): number | null {
  for (let i = from; i < values.length; i += 1) {
    const v = values[i];
    if (v != null) return v;
  }
  return null;
}

function lastNonNull(values: (number | null)[], upTo?: number): number | null {
  for (let i = Math.min(upTo ?? values.length - 1, values.length - 1); i >= 0; i -= 1) {
    const v = values[i];
    if (v != null) return v;
  }
  return null;
}

export interface MoverRow {
  provider: string;
  /** Net change of the provider's median rate over the window, in basis points. */
  netBps: number;
  /** Latest median rate (fraction). */
  current: number;
  /**
   * run_date of the most recent median change inside the window (or null when the
   * median did not move). Prefer this over the window label when telling the user
   * when the move happened.
   */
  movedOn: string | null;
}

/** Most recent date inside the window where the median differed from the prior observation. */
function lastMedianChangeDate(
  run_dates: string[],
  values: (number | null)[],
  start: number,
): string | null {
  let prev = start > 0 ? lastNonNull(values, start - 1) : null;
  let changedOn: string | null = null;
  for (let i = start; i < values.length; i += 1) {
    const value = values[i];
    if (value == null) continue;
    if (prev != null && value !== prev) changedOn = run_dates[i];
    prev = value;
  }
  return changedOn;
}

/**
 * Net per-provider median-rate change over the trailing window, biggest cuts first.
 * Pure array math over the precomputed series — no per-row aggregation on device.
 */
export function topMovers(
  payload: BankInsightsPayload | null | undefined,
  section: SectionKey,
  windowDays = 30,
): MoverRow[] {
  if (!payload) return [];
  const start = windowStartIndex(payload.run_dates, windowDays);
  const rows: MoverRow[] = [];
  for (const [provider, sections] of Object.entries(payload.banks)) {
    const series = sections[section];
    if (!series) continue;
    const first = firstNonNull(series.median, start);
    const last = lastNonNull(series.median);
    if (first == null || last == null) continue;
    rows.push({
      provider,
      netBps: Math.round((last - first) * 10000 * 10) / 10,
      current: last,
      movedOn: lastMedianChangeDate(payload.run_dates, series.median, start),
    });
  }
  rows.sort((a, b) => a.netBps - b.netBps || a.provider.localeCompare(b.provider));
  return rows;
}

export interface BankTrendModel {
  dates: string[];
  points: BankHistoryPoint[];
  allDates: string[];
}

/**
 * Chart model for one provider+section: band spans best↔median ("sharpest offer"
 * to "typical rate"), mean line tracks the median. Feeds BankHistoryChart as-is.
 */
export function bankTrendChartModel(
  payload: BankInsightsPayload | null | undefined,
  provider: string,
  section: SectionKey,
): BankTrendModel | null {
  try {
    const series = payload?.banks?.[provider]?.[section];
    if (!payload || !series) return null;
    const dates: string[] = [];
    const points: BankHistoryPoint[] = [];
    for (let i = 0; i < payload.run_dates.length; i += 1) {
      const median = series.median[i];
      const best = series.best[i];
      if (median == null && best == null) continue;
      const lo = Math.min(median ?? best ?? 0, best ?? median ?? 0);
      const hi = Math.max(median ?? best ?? 0, best ?? median ?? 0);
      dates.push(payload.run_dates[i]);
      points.push({
        date: payload.run_dates[i],
        min: lo,
        max: hi,
        mean: median ?? best,
        median: median ?? best,
        count: series.count[i] ?? 0,
      });
    }
    if (!points.length) return null;
    return { dates, points, allDates: payload.run_dates };
  } catch (err) {
    debugLog.error(
      'bankInsights',
      `bankTrendChartModel failed provider=${provider} section=${section}: ${String((err as Error)?.message ?? err)}`,
    );
    return null;
  }
}

export interface BankSnapshotRow {
  provider: string;
  /** Best advertised rate as of the snapshot date (last known value carried forward). */
  best: number | null;
  median: number | null;
  /** Best-rate change at its most recent move on/before the date, in bps. */
  changeBps: number | null;
  /** run_date of that most recent move (null when no prior data or no change). */
  changedOn: string | null;
}

/** Per-bank market state as of `date` — powers the ribbon-scrub rewind list. */
export function bankSnapshotAt(
  payload: BankInsightsPayload | null | undefined,
  section: SectionKey,
  date: string,
  lowerIsBetter: boolean,
): BankSnapshotRow[] {
  if (!payload?.run_dates?.length) return [];
  let idx = -1;
  for (let i = payload.run_dates.length - 1; i >= 0; i -= 1) {
    if (payload.run_dates[i] <= date) {
      idx = i;
      break;
    }
  }
  if (idx < 0) return [];

  const lastKnown = (
    series: (number | null)[],
  ): { value: number | null; index: number } => {
    for (let i = idx; i >= 0; i -= 1) {
      const v = series[i];
      if (v != null) return { value: v, index: i };
    }
    return { value: null, index: -1 };
  };

  const rows: BankSnapshotRow[] = [];
  for (const [provider, sections] of Object.entries(payload.banks)) {
    const series = sections[section];
    if (!series) continue;
    const best = lastKnown(series.best);
    const median = lastKnown(series.median);
    if (best.value == null && median.value == null) continue;
    // Most recent move on/before the date: walk back over equal values to the
    // first run where the current value appeared, then diff against the prior one.
    let changeBps: number | null = null;
    let changedOn: string | null = null;
    if (best.value != null) {
      let firstHeldIdx = best.index;
      for (let i = best.index - 1; i >= 0; i -= 1) {
        const v = series.best[i];
        if (v == null) continue;
        if (v !== best.value) {
          // Rates are fractions (0.0574), so one basis point is 0.0001.
          changeBps = Math.round((best.value - v) * 10000 * 10) / 10;
          changedOn = payload.run_dates[firstHeldIdx];
          break;
        }
        firstHeldIdx = i;
      }
    }
    rows.push({
      provider,
      best: best.value,
      median: median.value,
      changeBps,
      changedOn,
    });
  }
  rows.sort((a, b) => {
    const av = a.best ?? a.median;
    const bv = b.best ?? b.median;
    if (av == null) return 1;
    if (bv == null) return -1;
    return lowerIsBetter ? av - bv : bv - av;
  });
  return rows;
}

export interface MarketPulse {
  /** Distinct providers that moved rates in the window. */
  banksMoved: number;
  cuts: number;
  hikes: number;
  mixed: number;
  sinceDate: string;
}

/** Headline activity counts for the trailing window (Home/Trends teaser). */
export function marketPulse(
  payload: BankInsightsPayload | null | undefined,
  sinceDays = 7,
  sections?: readonly SectionKey[],
): MarketPulse | null {
  if (!payload?.run_dates?.length) return null;
  const anchor = parseYmd(payload.run_dates[payload.run_dates.length - 1]);
  if (anchor == null) return null;
  const cutoffTs = anchor - sinceDays * DAY_MS;
  const movers = new Set<string>();
  let cuts = 0;
  let hikes = 0;
  let mixed = 0;
  let sinceDate = payload.run_dates[payload.run_dates.length - 1];
  for (const event of payload.events) {
    if (sections && !sections.includes(event.section)) continue;
    const ts = parseYmd(event.date);
    if (ts == null || ts < cutoffTs) continue;
    movers.add(event.provider);
    if (event.dir === 'cut') cuts += 1;
    else if (event.dir === 'hike') hikes += 1;
    else mixed += 1;
    if (event.date < sinceDate) sinceDate = event.date;
  }
  return { banksMoved: movers.size, cuts, hikes, mixed, sinceDate };
}
