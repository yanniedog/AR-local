import type { BankHistoryPoint, RbaEntry, SectionKey } from '../types';
import { SECTION_KEYS } from '../types';
import { normalizeTimelineDates, parseYmd } from './bankHistoryTransform';
import { debugLog } from '../lib/debugLog';

export type BankMoveDir = 'cut' | 'hike' | 'mixed';

const MOVE_DIRS: readonly BankMoveDir[] = ['cut', 'hike', 'mixed'];

/** One provider rate-move detected by the Pi between consecutive ingest runs. */
export interface BankRateEvent {
  date: string;
  provider: string;
  section: SectionKey;
  dir: BankMoveDir;
  /** Products whose best advertised rate moved >= 5 bps. */
  moved: number;
  /** Products matched between the two runs. */
  total: number;
  /** Mean delta across moved products, in basis points (negative = cut). */
  avg_bps: number;
}

/** Per-provider daily series, positionally aligned to `run_dates`. */
export interface BankSectionSeries {
  median: (number | null)[];
  best: (number | null)[];
  count: (number | null)[];
}

/** Pre-aggregated per-bank history + events asset (see app_payload_mobile.py). */
export interface BankInsightsPayload {
  schema_version: number;
  run_date: string;
  run_dates: string[];
  banks: Record<string, Partial<Record<SectionKey, BankSectionSeries>>>;
  events: BankRateEvent[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

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
  };
}

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

export interface RbaDecisionRef {
  date: string;
  /** Decision size in basis points (negative = cut). RBA series is in percent. */
  bps: number;
}

export interface PassThroughRow {
  provider: string;
  /** Best-mortgage-rate change since the decision, in basis points. */
  passedBps: number;
  /** Days from the decision to the provider's first detected move, if any. */
  daysToFirstMove: number | null;
}

export interface PassThroughModel {
  decision: RbaDecisionRef;
  rows: PassThroughRow[];
}

/**
 * Score how each lender's best mortgage rate moved since the latest RBA decision
 * inside the tracked window. Null when no decision falls inside the history yet.
 */
export function rbaPassThrough(
  payload: BankInsightsPayload | null | undefined,
  rba: RbaEntry[] | null | undefined,
): PassThroughModel | null {
  if (!payload?.run_dates?.length || !rba?.length) return null;
  const firstDate = payload.run_dates[0];
  let decision: RbaDecisionRef | null = null;
  for (let i = 1; i < rba.length; i += 1) {
    const prior = rba[i - 1].rate;
    const rate = rba[i].rate;
    if (rate === prior) continue;
    const date = String(rba[i].date || '').slice(0, 10);
    if (date >= firstDate && date <= payload.run_date) {
      decision = { date, bps: Math.round((rate - prior) * 100) };
    }
  }
  if (!decision) return null;

  const decisionTs = parseYmd(decision.date);
  let baselineIdx = -1;
  for (let i = 0; i < payload.run_dates.length; i += 1) {
    if (payload.run_dates[i] <= decision.date) baselineIdx = i;
  }
  if (baselineIdx < 0 || decisionTs == null) return null;

  const rows: PassThroughRow[] = [];
  for (const [provider, sections] of Object.entries(payload.banks)) {
    const series = sections.Mortgage;
    if (!series) continue;
    const baseline = lastNonNull(series.best, baselineIdx);
    const current = lastNonNull(series.best);
    if (baseline == null || current == null) continue;
    let daysToFirstMove: number | null = null;
    for (const event of payload.events) {
      if (event.provider !== provider || event.section !== 'Mortgage' || event.date <= decision.date) continue;
      const ts = parseYmd(event.date);
      if (ts == null) continue;
      const days = Math.round((ts - decisionTs) / DAY_MS);
      if (daysToFirstMove == null || days < daysToFirstMove) daysToFirstMove = days;
    }
    rows.push({
      provider,
      passedBps: Math.round((current - baseline) * 10000 * 10) / 10,
      daysToFirstMove,
    });
  }
  if (!rows.length) return null;
  // Lead with the banks most aligned with the decision direction.
  rows.sort((a, b) =>
    decision!.bps < 0 ? a.passedBps - b.passedBps : b.passedBps - a.passedBps,
  );
  return { decision, rows };
}

export interface MarketPulse {
  /** Distinct providers that moved rates in the window. */
  banksMoved: number;
  cuts: number;
  hikes: number;
  sinceDate: string;
}

/** Headline activity counts for the trailing window (Home/Trends teaser). */
export function marketPulse(
  payload: BankInsightsPayload | null | undefined,
  sinceDays = 7,
): MarketPulse | null {
  if (!payload?.run_dates?.length) return null;
  const anchor = parseYmd(payload.run_dates[payload.run_dates.length - 1]);
  if (anchor == null) return null;
  const cutoffTs = anchor - sinceDays * DAY_MS;
  const movers = new Set<string>();
  let cuts = 0;
  let hikes = 0;
  let sinceDate = payload.run_dates[payload.run_dates.length - 1];
  for (const event of payload.events) {
    const ts = parseYmd(event.date);
    if (ts == null || ts < cutoffTs) continue;
    movers.add(event.provider);
    if (event.dir === 'cut') cuts += 1;
    else if (event.dir === 'hike') hikes += 1;
    if (event.date < sinceDate) sinceDate = event.date;
  }
  return { banksMoved: movers.size, cuts, hikes, sinceDate };
}
