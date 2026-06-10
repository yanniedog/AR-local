import type { BankHistoryPoint, HistoryWindow, SectionKey } from '../types';
import { SECTION_KEYS } from '../types';
import {
  alignPointsToTimeline,
  normalizeTimelineDates,
  sanitizeRibbonPoint,
  sliceChartTimeline,
} from './bankHistoryTransform';
import { debugLog } from '../lib/debugLog';

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


/** Drop corrupt history-banks JSON before it reaches chart code (prevents `.map` throws). */
export function normalizeHistoryBanksPayload(raw: unknown): HistoryBanksPayload | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  const run_date = typeof obj.run_date === 'string' ? obj.run_date.slice(0, 10) : '';
  if (!run_date) return null;

  const run_dates = Array.isArray(obj.run_dates)
    ? obj.run_dates
        .map((d) => (typeof d === 'string' ? d.slice(0, 10) : ''))
        .filter(Boolean)
    : [];

  const sectionsRaw = obj.sections;
  if (!sectionsRaw || typeof sectionsRaw !== 'object') return null;

  const sections: HistoryBanksPayload['sections'] = {};
  for (const [key, value] of Object.entries(sectionsRaw as Record<string, unknown>)) {
    if (!(SECTION_KEYS as readonly string[]).includes(key) || !value || typeof value !== 'object') continue;
    const pointsRaw = (value as { points?: unknown }).points;
    if (!Array.isArray(pointsRaw) || !pointsRaw.length) continue;
    const points: BankHistoryPoint[] = [];
    for (const item of pointsRaw) {
      if (!item || typeof item !== 'object') continue;
      const partial = item as Partial<BankHistoryPoint>;
      const date = String(partial.date ?? '').slice(0, 10);
      if (!date) continue;
      points.push(sanitizeRibbonPoint(date, partial));
    }
    if (points.length) sections[key as SectionKey] = { points };
  }

  if (!Object.keys(sections).length) return null;

  return {
    schema_version: typeof obj.schema_version === 'number' ? obj.schema_version : 1,
    run_date,
    run_dates,
    sections,
  };
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
  try {
    const sectionData = payload?.sections?.[section];
    const points = sectionData?.points;
    if (!Array.isArray(points) || !points.length) return null;

    const fallbackDates = points
      .map((p) => (p && typeof p === 'object' ? String(p.date ?? '').slice(0, 10) : ''))
      .filter(Boolean);
    const allDates = normalizeTimelineDates(
      payload?.run_dates?.length ? payload.run_dates : fallbackDates,
    );
    if (!allDates.length) return null;

    const aligned = alignPointsToTimeline(allDates, points);
    const sliced = sliceChartTimeline(allDates, aligned, window);
    return {
      dates: sliced.dates,
      points: sliced.points,
      allDates,
    };
  } catch (err) {
    debugLog.error(
      'historyPayload',
      `chartModelFromPrebuiltHistory failed section=${section}: ${String((err as Error)?.message ?? err)}`,
    );
    return null;
  }
}

