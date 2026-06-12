import type { BankHistoryPoint, HistoryWindow, SectionKey } from '../types';
import type { BankInsightsPayload } from './bankInsights';
import { historyDatesInWindow, parseYmd } from './bankHistoryTransform';

const DAY_MS = 24 * 60 * 60 * 1000;

function ymdFromTs(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10);
}

/** Monday-first weekday index (Mon=0 … Sun=6). */
function weekdayIndex(ts: number): number {
  return (new Date(ts).getUTCDay() + 6) % 7;
}

function centralValue(point: BankHistoryPoint | undefined): number | null {
  if (!point) return null;
  return point.median ?? point.mean ?? null;
}

// ---------------------------------------------------------------------------
// Rate heat calendar — GitHub-style grid of daily median moves.
// ---------------------------------------------------------------------------

export interface HeatCell {
  date: string;
  /** Day-over-day change of the section median, in basis points. Null = first observation. */
  deltaBps: number | null;
  /** |delta| scaled into 0..1 against the window's largest move. */
  intensity: number;
  hasData: boolean;
}

export interface RateHeatmapModel {
  /** Oldest → newest; each week holds Mon..Sun cells (null = before/after range). */
  weeks: (HeatCell | null)[][];
  monthLabels: { weekIndex: number; label: string }[];
  maxAbsBps: number;
}

const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * Calendar heatmap of daily median-rate moves. Cells without an ingest run are
 * rendered as "no data"; delta is computed against the previous observed run so
 * gaps don't zero the signal.
 */
export function rateHeatmapModel(
  dates: string[],
  points: BankHistoryPoint[],
  weeksBack = 16,
): RateHeatmapModel | null {
  const valueByDate = new Map<string, number>();
  for (const p of points) {
    const v = centralValue(p);
    if (v != null && parseYmd(p.date) != null) valueByDate.set(p.date, v);
  }
  const observed = dates.filter((d) => valueByDate.has(d)).sort();
  if (observed.length < 2) return null;

  const deltaByDate = new Map<string, number | null>();
  for (let i = 0; i < observed.length; i += 1) {
    if (i === 0) {
      deltaByDate.set(observed[i], null);
      continue;
    }
    const prev = valueByDate.get(observed[i - 1])!;
    const cur = valueByDate.get(observed[i])!;
    deltaByDate.set(observed[i], Math.round((cur - prev) * 10000 * 10) / 10);
  }

  let maxAbsBps = 0;
  for (const delta of deltaByDate.values()) {
    if (delta != null) maxAbsBps = Math.max(maxAbsBps, Math.abs(delta));
  }

  const lastTs = parseYmd(observed[observed.length - 1])!;
  // Snap the grid to whole weeks ending on the last observed date's week.
  const gridEnd = lastTs + (6 - weekdayIndex(lastTs)) * DAY_MS;
  const gridStart = gridEnd - (weeksBack * 7 - 1) * DAY_MS;

  const weeks: (HeatCell | null)[][] = [];
  const monthLabels: { weekIndex: number; label: string }[] = [];
  let lastLabelledMonth = -1;
  for (let w = 0; w < weeksBack; w += 1) {
    const week: (HeatCell | null)[] = [];
    for (let d = 0; d < 7; d += 1) {
      const ts = gridStart + (w * 7 + d) * DAY_MS;
      if (ts > lastTs) {
        week.push(null);
        continue;
      }
      const date = ymdFromTs(ts);
      const hasData = valueByDate.has(date);
      const deltaBps = hasData ? deltaByDate.get(date) ?? null : null;
      week.push({
        date,
        deltaBps,
        intensity: deltaBps != null && maxAbsBps > 0 ? Math.abs(deltaBps) / maxAbsBps : 0,
        hasData,
      });
    }
    weeks.push(week);
    const firstTs = gridStart + w * 7 * DAY_MS;
    const month = new Date(firstTs).getUTCMonth();
    if (month !== lastLabelledMonth) {
      monthLabels.push({ weekIndex: w, label: MONTHS_SHORT[month] });
      lastLabelledMonth = month;
    }
  }

  return { weeks, monthLabels, maxAbsBps };
}

// ---------------------------------------------------------------------------
// Lender race — rank-over-time bump chart of best advertised rates.
// ---------------------------------------------------------------------------

export interface RaceSeries {
  provider: string;
  /** Rank (1 = best) at each model date; null until the provider has data. */
  ranks: (number | null)[];
  /** Latest best advertised rate (fraction). */
  current: number | null;
  /** Rank change over the window (positive = climbed the board). */
  climbed: number;
}

export interface LenderRaceModel {
  dates: string[];
  series: RaceSeries[];
  topN: number;
  /** Total ranked lenders at the latest date (for "of N" context). */
  fieldSize: number;
}

const RACE_MAX_COLUMNS = 26;

function sampleIndices(length: number, maxColumns: number): number[] {
  if (length <= maxColumns) return Array.from({ length }, (_, i) => i);
  const out: number[] = [];
  for (let c = 0; c < maxColumns; c += 1) {
    out.push(Math.round((c / (maxColumns - 1)) * (length - 1)));
  }
  return Array.from(new Set(out));
}

/**
 * Rank lenders by best advertised rate at each run date (carry-forward), then
 * follow the lenders holding the top `topN` places today back through time.
 */
export function lenderRaceModel(
  payload: BankInsightsPayload | null | undefined,
  section: SectionKey,
  lowerIsBetter: boolean,
  window: HistoryWindow = '90D',
  topN = 6,
): LenderRaceModel | null {
  if (!payload?.run_dates?.length) return null;
  const windowDates = historyDatesInWindow(payload.run_dates, window);
  if (windowDates.length < 2) return null;
  const dateIndex = new Map(payload.run_dates.map((d, i) => [d, i]));

  const providers: { provider: string; values: (number | null)[] }[] = [];
  for (const [provider, sections] of Object.entries(payload.banks)) {
    const series = sections[section];
    if (!series) continue;
    let carried: number | null = null;
    const values = windowDates.map((date) => {
      const idx = dateIndex.get(date);
      if (idx == null) return carried;
      // Carry the last known value forward from the full series, not just the window.
      for (let i = idx; i >= 0; i -= 1) {
        const v = series.best[i];
        if (v != null) {
          carried = v;
          return v;
        }
        if (carried != null) break;
      }
      return carried;
    });
    if (values.some((v) => v != null)) providers.push({ provider, values });
  }
  if (providers.length < 2) return null;

  const columns = sampleIndices(windowDates.length, RACE_MAX_COLUMNS);
  const dates = columns.map((i) => windowDates[i]);

  // Rank per sampled column.
  const ranksByProvider = new Map<string, (number | null)[]>(
    providers.map((p) => [p.provider, columns.map(() => null as number | null)]),
  );
  let fieldSize = 0;
  for (let c = 0; c < columns.length; c += 1) {
    const col = columns[c];
    const ranked = providers
      .map((p) => ({ provider: p.provider, value: p.values[col] }))
      .filter((r): r is { provider: string; value: number } => r.value != null)
      .sort((a, b) =>
        (lowerIsBetter ? a.value - b.value : b.value - a.value) || a.provider.localeCompare(b.provider),
      );
    if (c === columns.length - 1) fieldSize = ranked.length;
    ranked.forEach((r, i) => {
      ranksByProvider.get(r.provider)![c] = i + 1;
    });
  }

  const lastCol = columns.length - 1;
  const leaders = providers
    .filter((p) => {
      const rank = ranksByProvider.get(p.provider)![lastCol];
      return rank != null && rank <= topN;
    })
    .sort((a, b) => ranksByProvider.get(a.provider)![lastCol]! - ranksByProvider.get(b.provider)![lastCol]!);
  if (!leaders.length) return null;

  const series: RaceSeries[] = leaders.map((p) => {
    const ranks = ranksByProvider.get(p.provider)!;
    const firstRank = ranks.find((r) => r != null) ?? null;
    const endRank = ranks[lastCol]!;
    let current: number | null = null;
    for (let i = p.values.length - 1; i >= 0; i -= 1) {
      if (p.values[i] != null) {
        current = p.values[i];
        break;
      }
    }
    return {
      provider: p.provider,
      ranks,
      current,
      climbed: firstRank != null ? firstRank - endRank : 0,
    };
  });

  return { dates, series, topN, fieldSize };
}

// ---------------------------------------------------------------------------
// Switcher's edge — gap between the market's typical and best rate over time.
// ---------------------------------------------------------------------------

export interface SpreadPoint {
  date: string;
  /** Best-vs-typical gap in basis points (always >= 0 when present). */
  gapBps: number | null;
}

export interface SpreadGapModel {
  points: SpreadPoint[];
  currentBps: number | null;
  maxBps: number;
  widestDate: string | null;
}

/**
 * "What does shopping around earn you?" — distance between the section median
 * and the best advertised rate (min for loans, max for deposits), per day.
 */
export function spreadGapModel(
  dates: string[],
  points: BankHistoryPoint[],
  lowerIsBetter: boolean,
): SpreadGapModel | null {
  const byDate = new Map(points.map((p) => [p.date, p]));
  const out: SpreadPoint[] = [];
  let maxBps = 0;
  let widestDate: string | null = null;
  let currentBps: number | null = null;
  for (const date of dates) {
    const p = byDate.get(date);
    const typical = centralValue(p);
    const best = lowerIsBetter ? p?.min ?? null : p?.max ?? null;
    let gapBps: number | null = null;
    if (typical != null && best != null) {
      gapBps = Math.max(0, Math.round(Math.abs(typical - best) * 10000 * 10) / 10);
      if (gapBps > maxBps) {
        maxBps = gapBps;
        widestDate = date;
      }
      currentBps = gapBps;
    }
    out.push({ date, gapBps });
  }
  if (!out.some((p) => p.gapBps != null)) return null;
  return { points: out, currentBps, maxBps, widestDate };
}

// ---------------------------------------------------------------------------
// Market seismograph — daily rate-move energy from the events feed.
// ---------------------------------------------------------------------------

export interface ActivityDay {
  date: string;
  /** Summed |avg_bps| of upward moves that day. */
  hikeBps: number;
  /** Summed |avg_bps| of downward moves that day. */
  cutBps: number;
  hikes: number;
  cuts: number;
}

export interface MarketActivityModel {
  days: ActivityDay[];
  /** Largest one-sided daily magnitude — scales the mirrored bars. */
  maxBps: number;
  totalMoves: number;
}

/** Mirrored daily activity trace: every detected lender move, sized by bps. */
export function marketActivityModel(
  payload: BankInsightsPayload | null | undefined,
  section: SectionKey | null,
  window: HistoryWindow = '90D',
): MarketActivityModel | null {
  if (!payload?.run_dates?.length) return null;
  const dates = historyDatesInWindow(payload.run_dates, window);
  if (!dates.length) return null;
  const byDate = new Map<string, ActivityDay>(
    dates.map((date) => [date, { date, hikeBps: 0, cutBps: 0, hikes: 0, cuts: 0 }]),
  );
  let totalMoves = 0;
  for (const event of payload.events) {
    if (section && event.section !== section) continue;
    const day = byDate.get(event.date);
    if (!day || event.avg_bps === 0) continue;
    totalMoves += 1;
    if (event.avg_bps > 0) {
      day.hikeBps += event.avg_bps;
      day.hikes += 1;
    } else {
      day.cutBps += Math.abs(event.avg_bps);
      day.cuts += 1;
    }
  }
  const days = dates.map((date) => byDate.get(date)!);
  const maxBps = days.reduce((acc, d) => Math.max(acc, d.hikeBps, d.cutBps), 0);
  if (maxBps === 0) return { days, maxBps: 0, totalMoves: 0 };
  return { days, maxBps, totalMoves };
}
