import { DATES_INDEX_URL, datedManifestUrl } from '../config';
import { debugLog } from '../lib/debugLog';
import type { BankHistoryPoint, CorePayload, SectionKey } from '../types';
import { SECTION_KEYS } from '../types';
import { normalizeTimelineDates, sanitizeRibbonPoint } from './bankHistoryTransform';
import { normalizeHistoryBanksPayload, type HistoryBanksPayload } from './historyPayload';
import { downloadCore, fetchManifest } from './payload';

/** Earliest run_date published as an immutable dated GitHub release (app_payload.py). */
export const HISTORY_MIN_DATE = '2026-05-13';

export interface DatesIndex {
  schema_version: number;
  dates: string[];
  count: number;
  min_date: string;
  latest_date: string;
}

const YMD = /^\d{4}-\d{2}-\d{2}$/;

/** Parse ``dates-index.json`` from the rolling GitHub release. */
export function parseDatesIndex(raw: unknown): DatesIndex | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  const dates = Array.isArray(obj.dates)
    ? obj.dates
        .map((d) => (typeof d === 'string' ? d.slice(0, 10) : ''))
        .filter((d) => YMD.test(d))
    : [];
  if (!dates.length) return null;
  const sorted = normalizeTimelineDates(dates);
  return {
    schema_version: typeof obj.schema_version === 'number' ? obj.schema_version : 1,
    dates: sorted,
    count: typeof obj.count === 'number' ? obj.count : sorted.length,
    min_date: typeof obj.min_date === 'string' ? obj.min_date.slice(0, 10) : HISTORY_MIN_DATE,
    latest_date: sorted.at(-1) ?? '',
  };
}

export function historyDatesUpTo(index: DatesIndex, targetRunDate: string): string[] {
  const floor =
    index.min_date && index.min_date >= HISTORY_MIN_DATE ? index.min_date : HISTORY_MIN_DATE;
  const cap = String(targetRunDate || '').slice(0, 10);
  return index.dates.filter((d) => d >= floor && (!cap || d <= cap));
}

export function dailyHistorySha(runDates: string[]): string {
  return `daily:${runDates.join(',')}`;
}

export function historyBanksCoversDates(
  payload: HistoryBanksPayload | null | undefined,
  dates: string[],
): boolean {
  if (!payload?.run_dates?.length || !dates.length) return false;
  const have = new Set(payload.run_dates);
  return dates.every((d) => have.has(d));
}

function extractSectionPoint(core: CorePayload, section: SectionKey): BankHistoryPoint | null {
  const date = String(core.run_date || '').slice(0, 10);
  const sectionData = core.sections?.[section];
  if (!date || !sectionData?.ribbon?.range) return null;
  const range = sectionData.ribbon.range;
  const point = sanitizeRibbonPoint(date, {
    min: range.min,
    max: range.max,
    mean: range.mean,
    median: range.median,
    count: sectionData.ribbon.counts?.rates ?? 0,
  });
  if (point.min == null && point.max == null && point.mean == null) return null;
  return point;
}

/** Merge cached section points with freshly downloaded dated cores. */
export function mergeHistoryFromCores(
  existing: HistoryBanksPayload | null | undefined,
  coresByDate: Map<string, CorePayload>,
  orderedDates: string[],
  latestRunDate: string,
): HistoryBanksPayload | null {
  const run_dates = normalizeTimelineDates(orderedDates);
  if (!run_dates.length) return null;

  const sections: HistoryBanksPayload['sections'] = {};
  for (const section of SECTION_KEYS) {
    const byDate = new Map<string, BankHistoryPoint>();
    for (const point of existing?.sections?.[section]?.points ?? []) {
      const date = String(point.date || '').slice(0, 10);
      if (date) byDate.set(date, point);
    }
    for (const date of run_dates) {
      const core = coresByDate.get(date);
      if (!core) continue;
      const point = extractSectionPoint(core, section);
      if (point) byDate.set(date, point);
    }
    const points = run_dates.map((d) => byDate.get(d)).filter((p): p is BankHistoryPoint => !!p);
    if (points.length) sections[section] = { points };
  }
  if (!Object.keys(sections).length) return null;

  return normalizeHistoryBanksPayload({
    schema_version: 1,
    run_date: latestRunDate,
    run_dates,
    sections,
  });
}

async function fetchDatesIndexJson(url: string = DATES_INDEX_URL): Promise<DatesIndex> {
  const sep = url.includes('?') ? '&' : '?';
  const res = await fetch(`${url}${sep}_=${Date.now()}`);
  if (!res.ok) throw new Error(`dates-index HTTP ${res.status}`);
  const parsed = parseDatesIndex(await res.json());
  if (!parsed) throw new Error('dates-index payload invalid');
  return parsed;
}

async function downloadDatedCore(runDate: string): Promise<CorePayload> {
  const manifest = await fetchManifest(datedManifestUrl(runDate));
  const { core } = await downloadCore(
    manifest.files.core.url,
    manifest.files.core.sha256,
    { fileName: manifest.files.core.name, expectedBytes: manifest.files.core.bytes },
  );
  return core;
}

async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next;
      next += 1;
      out[i] = await fn(items[i]);
    }
  });
  await Promise.all(workers);
  return out;
}

export interface SyncHistoryDailyOpts {
  targetRunDate: string;
  currentCore: CorePayload;
  existing?: HistoryBanksPayload | null;
  cachedDates?: Set<string>;
  maxConcurrent?: number;
}

/**
 * Incrementally download immutable dated core payloads and aggregate section ribbon
 * stats into a chart-ready ``HistoryBanksPayload``.
 */
export async function syncHistoryFromDailyPayloads(
  opts: SyncHistoryDailyOpts,
): Promise<HistoryBanksPayload> {
  const targetRunDate = String(opts.targetRunDate || '').slice(0, 10);
  if (!targetRunDate) throw new Error('syncHistoryFromDailyPayloads: missing targetRunDate');

  const index = await fetchDatesIndexJson();
  const wantedDates = historyDatesUpTo(index, targetRunDate);
  if (!wantedDates.length) throw new Error('dates-index has no history dates');

  const coresByDate = new Map<string, CorePayload>();
  coresByDate.set(targetRunDate, opts.currentCore);

  const skip = opts.cachedDates ?? new Set(opts.existing?.run_dates ?? []);
  const toFetch = wantedDates.filter((d) => d !== targetRunDate && !skip.has(d));

  debugLog.info(
    'historyDaily',
    `sync start target=${targetRunDate} want=${wantedDates.length} fetch=${toFetch.length}`,
  );

  if (toFetch.length) {
    const downloaded = await mapWithConcurrency(toFetch, opts.maxConcurrent ?? 3, async (runDate) => {
      try {
        return { runDate, core: await downloadDatedCore(runDate) };
      } catch (err) {
        debugLog.warn(
          'historyDaily',
          `dated core failed run_date=${runDate}: ${String((err as Error)?.message ?? err)}`,
        );
        return { runDate, core: null as CorePayload | null };
      }
    });
    for (const { runDate, core } of downloaded) {
      if (core) coresByDate.set(runDate, core);
    }
  }

  const cachedPointDates = new Set<string>();
  for (const section of SECTION_KEYS) {
    for (const point of opts.existing?.sections?.[section]?.points ?? []) {
      const date = String(point.date || '').slice(0, 10);
      if (date) cachedPointDates.add(date);
    }
  }
  const availableDates = wantedDates.filter(
    (d) => coresByDate.has(d) || cachedPointDates.has(d),
  );
  const built = mergeHistoryFromCores(opts.existing, coresByDate, availableDates, targetRunDate);
  if (!built || built.run_dates.length < 1) {
    throw new Error('daily history sync produced no section points');
  }
  debugLog.info(
    'historyDaily',
    `sync ok run_date=${built.run_date} slices=${built.run_dates.length}`,
  );
  return built;
}
