import type { BankHistoryPoint, HistoryWindow, SectionKey } from '../types';
import {
  alignPointsToTimeline,
  normalizeTimelineDates,
  sliceChartTimeline,
} from './bankHistoryTransform';

/** Pre-aggregated section ribbon series (see app_history_export.py). */
export interface HistoryBanksPayload {
  schema_version: number;
  run_date: string;
  run_dates: string[];
  sections: Partial<
    Record<
      SectionKey,
      {
        points: BankHistoryPoint[];
      }
    >
  >;
}

export interface PrebuiltHistorySection {
  dates: string[];
  points: BankHistoryPoint[];
  allDates: string[];
}

/** Chart-ready slice from a pre-built history asset (no per-row aggregation on device). */
export function chartModelFromPrebuiltHistory(
  payload: HistoryBanksPayload | null | undefined,
  section: SectionKey,
  window: HistoryWindow = '30D',
): PrebuiltHistorySection | null {
  const sectionData = payload?.sections?.[section];
  if (!sectionData?.points?.length) return null;

  const allDates = normalizeTimelineDates(
    payload?.run_dates?.length ? payload.run_dates : sectionData.points.map((p) => p.date),
  );
  const aligned = alignPointsToTimeline(allDates, sectionData.points);
  const sliced = sliceChartTimeline(allDates, aligned, window);
  return {
    dates: sliced.dates,
    points: sliced.points,
    allDates,
  };
}
