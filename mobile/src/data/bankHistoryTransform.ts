import type { BankHistoryPoint, HistoryWindow, RbaEntry } from '../types';

export const HISTORY_WINDOWS: Record<Exclude<HistoryWindow, 'All'>, number> = {
  '30D': 30,
  '90D': 90,
  '1Y': 365,
};

const YMD_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function parseYmd(date: string): number | null {
  const m = YMD_RE.exec(String(date || '').slice(0, 10));
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (!Number.isFinite(y) || !Number.isFinite(mo) || !Number.isFinite(d)) return null;
  return Date.UTC(y, mo - 1, d);
}

export function normalizeTimelineDates(rawDates: string[]): string[] {
  const seen = new Set<string>();
  const dates: string[] = [];
  for (const value of rawDates || []) {
    const date = String(value ?? '').slice(0, 10);
    if (!parseYmd(date) || seen.has(date)) continue;
    seen.add(date);
    dates.push(date);
  }
  dates.sort();
  return dates;
}

function finiteOrNull(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function sanitizeRibbonPoint(date: string, point?: Partial<BankHistoryPoint> | null): BankHistoryPoint {
  const source = point || {};
  let min = finiteOrNull(source.min);
  let max = finiteOrNull(source.max);
  let mean = finiteOrNull(source.mean);
  let median = finiteOrNull(source.median);
  if (min != null && max != null && min > max) {
    const swap = min;
    min = max;
    max = swap;
  }
  if (mean != null && min != null && max != null) {
    mean = Math.min(Math.max(mean, min), max);
  } else if (mean == null && min != null && max != null) {
    mean = (min + max) / 2;
  }
  if (median != null && min != null && max != null) {
    median = Math.min(Math.max(median, min), max);
  }
  if (min == null || max == null) {
    min = null;
    max = null;
  }
  const countRaw = Number(source.count);
  const count = Number.isFinite(countRaw) && countRaw > 0 ? Math.round(countRaw) : 0;
  return { date, min, max, mean, median, count };
}

/** Map sparse history points onto a sorted timeline (dashboard chart.js parity). */
export function alignPointsToTimeline(dates: string[], rawPoints: Partial<BankHistoryPoint>[]): BankHistoryPoint[] {
  const byDate: Record<string, Partial<BankHistoryPoint>> = {};
  for (let index = 0; index < (rawPoints || []).length; index += 1) {
    const point = rawPoints[index];
    const fallback = dates[index] || '';
    const date = String((point && point.date) || fallback).slice(0, 10);
    if (!date || !parseYmd(date)) continue;
    if (!byDate[date]) byDate[date] = point;
  }
  return dates.map((date) => sanitizeRibbonPoint(date, byDate[date]));
}

export function historyDatesInWindow(dates: string[], window: HistoryWindow): string[] {
  const sorted = (dates || [])
    .map((date) => ({ date: String(date || ''), ts: parseYmd(date) }))
    .filter((item): item is { date: string; ts: number } => item.ts != null)
    .sort((a, b) => a.ts - b.ts);
  if (window === 'All' || sorted.length < 2) {
    return sorted.map((item) => item.date);
  }
  const days = HISTORY_WINDOWS[window] || 30;
  const anchor = sorted[sorted.length - 1].ts;
  const cutoff = anchor - days * 24 * 60 * 60 * 1000;
  return sorted.filter((item) => item.ts >= cutoff).map((item) => item.date);
}

/** Nearest time-slice index from X within the plot area (0..plotWidth). Dashboard chart.js parity. */
export function sliceIndexFromPlotX(plotLocalX: number, plotWidth: number, sliceCount: number): number {
  if (sliceCount <= 1) return 0;
  const width = Math.max(1, plotWidth);
  const clamped = Math.max(0, Math.min(width, plotLocalX));
  const idx = Math.round((clamped / width) * (sliceCount - 1));
  return Math.max(0, Math.min(sliceCount - 1, idx));
}

export function sliceChartTimeline(
  dates: string[],
  points: BankHistoryPoint[],
  window: HistoryWindow,
): { dates: string[]; points: BankHistoryPoint[] } {
  const normalizedDates = normalizeTimelineDates(dates);
  const aligned = alignPointsToTimeline(normalizedDates, points);
  const slicedDates = historyDatesInWindow(normalizedDates, window);
  const pointByDate = Object.fromEntries(aligned.map((p) => [p.date, p]));
  return {
    dates: slicedDates,
    points: slicedDates.map((date) => pointByDate[date] ?? sanitizeRibbonPoint(date)),
  };
}

export function rbaRateAsOf(rba: RbaEntry[], dateYmd: string): number | null {
  if (!rba.length) return null;
  const target = parseYmd(dateYmd);
  if (target == null) return null;
  let last: number | null = null;
  for (const entry of rba) {
    const ts = parseYmd(entry.date);
    if (ts == null) continue;
    if (ts <= target) last = entry.rate;
    else break;
  }
  return last;
}

/** Cash-rate step values per plotted date (fraction, dashboard parity). */
export function rbaStepForDates(dates: string[], rba: RbaEntry[]): (number | null)[] {
  return dates.map((date) => {
    const rate = rbaRateAsOf(rba, date);
    if (rate == null || !Number.isFinite(rate)) return null;
    const fraction = rate / 100;
    return Number.isFinite(fraction) ? fraction : null;
  });
}

export interface RbaChangeMark {
  date: string;
  snap: string;
  rate: number;
  prior: number;
  bp: number;
}

export function rbaChangesInWindow(dates: string[], rba: RbaEntry[]): RbaChangeMark[] {
  if (!dates.length || !rba.length) return [];
  const first = dates[0];
  const last = dates[dates.length - 1];
  const firstTs = parseYmd(first);
  const lastTs = parseYmd(last);
  if (firstTs == null || lastTs == null) return [];

  const changes: RbaChangeMark[] = [];
  for (let i = 1; i < rba.length; i += 1) {
    const prior = rba[i - 1].rate;
    const rate = rba[i].rate;
    if (rate === prior) continue;
    const date = rba[i].date;
    const ts = parseYmd(date);
    if (ts == null || ts < firstTs || ts > lastTs) continue;
    changes.push({
      date,
      snap: snapRbaChangeToTimeline(date, dates),
      rate,
      prior,
      bp: Math.round((rate - prior) * 100),
    });
  }

  if (!changes.length) {
    for (let i = rba.length - 1; i >= 1; i -= 1) {
      const prior = rba[i - 1].rate;
      const rate = rba[i].rate;
      if (rate === prior) continue;
      const date = rba[i].date;
      const ts = parseYmd(date);
      if (ts != null && ts < firstTs) {
        changes.push({
          date,
          snap: snapRbaChangeToTimeline(date, dates),
          rate,
          prior,
          bp: Math.round((rate - prior) * 100),
        });
        break;
      }
    }
  }
  return changes;
}

function snapRbaChangeToTimeline(changeDate: string, dates: string[]): string {
  const dateSet = new Set(dates);
  if (dateSet.has(changeDate)) return changeDate;
  for (let i = 0; i < dates.length; i += 1) {
    if (dates[i] >= changeDate) return dates[i];
  }
  return dates[dates.length - 1] || changeDate;
}

export function chartYDomain(
  points: BankHistoryPoint[],
  rbaSteps: (number | null)[],
  extra: (number | null)[] = [],
): { min: number; max: number } {
  let min: number | null = null;
  let max: number | null = null;
  const consider = (v: number | null) => {
    if (v == null || !Number.isFinite(v)) return;
    if (min == null || v < min) min = v;
    if (max == null || v > max) max = v;
  };
  for (const p of points) {
    consider(p.min);
    consider(p.max);
    consider(p.mean);
    consider(p.median);
  }
  for (const r of rbaSteps) consider(r);
  for (const v of extra) consider(v);
  const baseMin = min ?? 0;
  const baseMax = max ?? 0.001;
  return {
    min: Math.max(0, Math.floor((baseMin - 0.003) * 1000) / 1000),
    max: Math.max(0.001, Math.ceil((baseMax + 0.003) * 1000) / 1000),
  };
}

export function formatAxisDateLabel(dateYmd: string): string {
  const ts = parseYmd(dateYmd);
  if (ts == null) return dateYmd;
  const d = new Date(ts);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${d.getUTCDate()} ${months[d.getUTCMonth()]}`;
}

export function axisLabelInterval(count: number): number {
  if (count <= 6) return 0;
  if (count <= 12) return 1;
  if (count <= 24) return 2;
  return Math.ceil(count / 8);
}
