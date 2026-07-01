import type {
  BankHistoryCache,
  BankHistoryChartModel,
  BankHistoryPoint,
  CorePayload,
  HistoryWindow,
  RateRow,
  SectionKey,
} from '../types';
import { chartModelFromPrebuiltHistory, type HistoryBanksPayload } from './historyPayload';
import {
  alignPointsToTimeline,
  historyDatesInWindow,
  normalizeTimelineDates,
  sanitizeRibbonPoint,
} from './bankHistoryTransform';
import { debugLog } from '../lib/debugLog';
import { isBroadlyAvailable, toFraction } from './format';
import { rowsUnder } from './taxonomy';

function medianOf(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

type AggSlot = {
  min: number;
  max: number;
  sum: number;
  count: number;
  rates: number[];
};

function accumulate(slot: AggSlot | undefined, rate: number): AggSlot {
  if (!slot) return { min: rate, max: rate, sum: rate, count: 1, rates: [rate] };
  slot.min = Math.min(slot.min, rate);
  slot.max = Math.max(slot.max, rate);
  slot.sum += rate;
  slot.count += 1;
  slot.rates.push(rate);
  return slot;
}

/** Build aggregate ribbon points from retained history rows (dashboard buildAggregateRibbon). */
export function buildAggregateRibbonFromHistory(
  historyRows: Array<RateRow & { run_date?: string }>,
  retainedRunDates: string[],
  window: HistoryWindow,
): { dates: string[]; points: BankHistoryPoint[]; allDates: string[] } {
  const sliceDates = new Set<string>();
  const byDate: Record<string, AggSlot> = {};

  for (const row of historyRows) {
    const date = String(row.run_date || '').slice(0, 10);
    const rate = toFraction(row.rate);
    if (!date || rate == null || rate <= 0) continue;
    sliceDates.add(date);
    byDate[date] = accumulate(byDate[date], rate);
  }

  const sliceDatesSorted = normalizeTimelineDates(Array.from(sliceDates));
  const timelineSource = retainedRunDates.length ? retainedRunDates : sliceDatesSorted;
  const dates = historyDatesInWindow(timelineSource, window);
  const points = dates.map((date) => {
    const agg = byDate[date];
    if (!agg) return { date, min: null, max: null, mean: null, median: null, count: 0 };
    return {
      date,
      min: agg.min,
      max: agg.max,
      mean: agg.sum / Math.max(1, agg.count),
      median: medianOf(agg.rates),
      count: agg.count,
    };
  });

  return {
    dates,
    points,
    allDates: timelineSource,
  };
}

function currentRibbonFallback(
  core: CorePayload,
  section: SectionKey,
  includeNonStandard: boolean,
): BankHistoryChartModel | null {
  const sectionData = core.sections[section];
  if (!sectionData) return null;
  const hierRows = rowsUnder(sectionData.rates, section, []);
  const visibleKeys = new Set(
    hierRows
      .filter((row) => includeNonStandard || isBroadlyAvailable(row))
      .map((row) => row.product_key),
  );
  if (!visibleKeys.size && sectionData.ribbon?.range?.min == null) return null;

  const date = String(core.run_date || '').slice(0, 10);
  if (!date) return null;
  const range = sectionData.ribbon?.range;
  const point = sanitizeRibbonPoint(date, {
    min: range?.min ?? null,
    max: range?.max ?? null,
    mean: range?.mean ?? null,
    median: range?.median ?? null,
    count: sectionData.ribbon?.counts?.rates ?? 0,
  });
  if (point.min == null && point.max == null && point.mean == null) return null;

  return {
    section,
    dates: [date],
    points: [point],
    allDates: [date],
  };
}

export interface HistorySelectorState {
  core: CorePayload | null;
  historyBanks?: HistoryBanksPayload | null;
  historyCache?: BankHistoryCache | null;
  includeNonStandard?: boolean;
}

/**
 * Select bank-history chart model for a section.
 * Returns the full retained timeline; BankHistoryChart applies window chips locally.
 */
export function selectBankHistoryChartModel(
  state: HistorySelectorState,
  section: SectionKey,
  window: HistoryWindow = 'All',
): BankHistoryChartModel | null {
  try {
    const { core, historyBanks, historyCache, includeNonStandard = false } = state;
    if (!core) return null;

    const prebuilt = chartModelFromPrebuiltHistory(historyBanks, section, window);
    if (prebuilt?.dates.length) {
      return {
        section,
        dates: prebuilt.dates,
        points: prebuilt.points,
        allDates: prebuilt.allDates,
      };
    }

    if (historyCache && historyCache.section === section && historyCache.rates?.length) {
      const sectionRows = core.sections[section]?.rates ?? [];
      const hierRows = rowsUnder(sectionRows, section, []);
      const visibleKeys = new Set(
        hierRows
          .filter((row) => includeNonStandard || isBroadlyAvailable(row))
          .map((row) => row.product_key),
      );
      const filtered = historyCache.rates.filter((row) => visibleKeys.has(row.product_key));
      const retained = normalizeTimelineDates(historyCache.run_dates || []);
      const aggregate = buildAggregateRibbonFromHistory(filtered, retained, window);
      if (!aggregate.dates.length) return null;
      return {
        section,
        dates: aggregate.dates,
        points: alignPointsToTimeline(aggregate.dates, aggregate.points),
        allDates: aggregate.allDates,
      };
    }

    const fallback = currentRibbonFallback(core, section, includeNonStandard);
    if (!fallback) return null;
    return {
      section,
      dates: fallback.dates,
      points: fallback.points,
      allDates: fallback.allDates ?? fallback.dates,
    };
  } catch (err) {
    debugLog.error(
      'historySelectors',
      `selectBankHistoryChartModel failed section=${section}: ${String((err as Error)?.message ?? err)}`,
    );
    return null;
  }
}

/** Read on-device history cache from store state when wired. */
export function selectBankHistoryCache(state: { historyCache?: BankHistoryCache | null }): BankHistoryCache | null {
  return state.historyCache ?? null;
}
