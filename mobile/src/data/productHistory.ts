import { SECTIONS } from '../constants';
import { debugLog } from '../lib/debugLog';
import type { CorePayload } from '../types';
import { SECTION_KEYS } from '../types';
import { normalizeTimelineDates } from './bankHistoryTransform';
import { toFraction } from './format';
import {
  downloadDatedCore,
  fetchDatesIndexJson,
  historyDatesUpTo,
  mapWithConcurrency,
} from './historyDaily';

const YMD = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Compact per-product rate history, derived on-device from the immutable dated `core`
 * payloads. Each product's representative (section-best) rate is stored per run_date,
 * aligned to `run_dates`; missing days are `null`. Restricted to the current catalog
 * (keys present in the latest core) to bound size.
 */
export interface ProductHistoryPayload {
  schema_version: number;
  run_date: string;
  run_dates: string[];
  products: Record<string, (number | null)[]>;
}

/** Best (section-aware) rate per product_key for one core; current-catalog keys only. */
function bestRatesForCore(core: CorePayload, keys: Set<string>): Map<string, number> {
  const best = new Map<string, number>();
  for (const section of SECTION_KEYS) {
    const lowerIsBetter = SECTIONS[section].lowerIsBetter;
    for (const row of core.sections?.[section]?.rates ?? []) {
      const key = row.product_key;
      if (!key || !keys.has(key)) continue;
      const rate = toFraction(row.rate);
      if (rate == null || rate <= 0) continue;
      const prev = best.get(key);
      if (prev == null) best.set(key, rate);
      else best.set(key, lowerIsBetter ? Math.min(prev, rate) : Math.max(prev, rate));
    }
  }
  return best;
}

/**
 * Build a `ProductHistoryPayload` from dated cores. Dates without a downloaded core fall
 * back to `existing` (so an incremental sync only needs to fetch new days).
 */
export function buildProductHistoryFromCores(
  coresByDate: Map<string, CorePayload>,
  orderedDates: string[],
  latestRunDate: string,
  existing?: ProductHistoryPayload | null,
): ProductHistoryPayload {
  const run_dates = normalizeTimelineDates(orderedDates);
  const target = String(latestRunDate || '').slice(0, 10);
  const latestCore = coresByDate.get(target) ?? coresByDate.get(run_dates.at(-1) ?? '');

  // Current catalog = the keys a product page can actually open today.
  const keys = new Set<string>();
  if (latestCore) {
    for (const section of SECTION_KEYS) {
      for (const row of latestCore.sections?.[section]?.rates ?? []) {
        if (row.product_key) keys.add(row.product_key);
      }
    }
  }

  // Reuse already-computed rates for days we didn't re-download.
  const existingByKey = new Map<string, Map<string, number | null>>();
  if (existing) {
    for (const [key, arr] of Object.entries(existing.products)) {
      const m = new Map<string, number | null>();
      existing.run_dates.forEach((d, i) => m.set(d, arr[i] ?? null));
      existingByKey.set(key, m);
    }
  }

  const coreBestByDate = new Map<string, Map<string, number>>();
  for (const date of run_dates) {
    const core = coresByDate.get(date);
    if (core) coreBestByDate.set(date, bestRatesForCore(core, keys));
  }

  const products: Record<string, (number | null)[]> = {};
  for (const key of keys) {
    const series = run_dates.map((d) => {
      const fromCore = coreBestByDate.get(d)?.get(key);
      if (fromCore != null) return fromCore;
      const fromExisting = existingByKey.get(key)?.get(d);
      return fromExisting != null ? fromExisting : null;
    });
    if (series.some((v) => v != null)) products[key] = series;
  }

  return { schema_version: 1, run_date: target, run_dates, products };
}

/** A product's series aligned to an arbitrary `dates` axis (e.g. the chart's sliced dates). */
export function extractProductSeries(
  payload: ProductHistoryPayload | null | undefined,
  productKey: string,
  dates: string[],
): (number | null)[] {
  const series = payload?.products?.[productKey];
  if (!payload || !series) return dates.map(() => null);
  const byDate = new Map<string, number | null>();
  payload.run_dates.forEach((d, i) => byDate.set(d, series[i] ?? null));
  return dates.map((d) => byDate.get(d) ?? null);
}

/** Date→value record for `BankHistoryChart`'s `highlightSeries.values`. */
export function productSeriesRecord(
  payload: ProductHistoryPayload | null | undefined,
  productKey: string,
): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  const series = payload?.products?.[productKey];
  if (!payload || !series) return out;
  payload.run_dates.forEach((d, i) => {
    out[d] = series[i] ?? null;
  });
  return out;
}

export function hasProductSeries(
  payload: ProductHistoryPayload | null | undefined,
  productKey: string,
): boolean {
  const series = payload?.products?.[productKey];
  return !!series && series.some((v) => v != null);
}

/** Validate a cached/parsed payload before it reaches chart code. */
export function normalizeProductHistoryPayload(raw: unknown): ProductHistoryPayload | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  const run_date = typeof obj.run_date === 'string' ? obj.run_date.slice(0, 10) : '';
  if (!run_date) return null;
  const run_dates = Array.isArray(obj.run_dates) ? obj.run_dates.map((d) => String(d).slice(0, 10)) : [];
  // Strict: every date valid so `products` arrays stay index-aligned to `run_dates`.
  if (!run_dates.length || !run_dates.every((d) => YMD.test(d))) return null;
  const productsRaw = obj.products;
  if (!productsRaw || typeof productsRaw !== 'object') return null;

  const products: Record<string, (number | null)[]> = {};
  for (const [key, value] of Object.entries(productsRaw as Record<string, unknown>)) {
    if (!Array.isArray(value)) continue;
    const aligned = run_dates.map((_, i) => {
      const n = Number(value[i]);
      return Number.isFinite(n) && n > 0 ? n : null;
    });
    if (aligned.some((v) => v != null)) products[key] = aligned;
  }
  if (!Object.keys(products).length) return null;

  return {
    schema_version: typeof obj.schema_version === 'number' ? obj.schema_version : 1,
    run_date,
    run_dates,
    products,
  };
}

export interface SyncProductHistoryOpts {
  targetRunDate: string;
  currentCore: CorePayload;
  existing?: ProductHistoryPayload | null;
  maxConcurrent?: number;
}

/**
 * Incrementally download the dated cores missing from `existing` and (re)build the
 * per-product history. The current day is always recomputed from `currentCore`.
 */
export async function syncProductHistoryFromDailyPayloads(
  opts: SyncProductHistoryOpts,
): Promise<ProductHistoryPayload> {
  const targetRunDate = String(opts.targetRunDate || '').slice(0, 10);
  if (!targetRunDate) throw new Error('syncProductHistoryFromDailyPayloads: missing targetRunDate');

  const index = await fetchDatesIndexJson();
  const wantedDates = historyDatesUpTo(index, targetRunDate);
  if (!wantedDates.length) throw new Error('dates-index has no history dates');

  const coresByDate = new Map<string, CorePayload>();
  coresByDate.set(targetRunDate, opts.currentCore);

  const have = new Set(opts.existing?.run_dates ?? []);
  const toFetch = wantedDates.filter((d) => d !== targetRunDate && !have.has(d));

  debugLog.info(
    'productHistory',
    `sync start target=${targetRunDate} want=${wantedDates.length} fetch=${toFetch.length}`,
  );

  if (toFetch.length) {
    const downloaded = await mapWithConcurrency(toFetch, opts.maxConcurrent ?? 3, async (runDate) => {
      try {
        return { runDate, core: await downloadDatedCore(runDate) };
      } catch (err) {
        debugLog.warn(
          'productHistory',
          `dated core failed run_date=${runDate}: ${String((err as Error)?.message ?? err)}`,
        );
        return { runDate, core: null as CorePayload | null };
      }
    });
    for (const { runDate, core } of downloaded) {
      if (core) coresByDate.set(runDate, core);
    }
  }

  const built = buildProductHistoryFromCores(coresByDate, wantedDates, targetRunDate, opts.existing);
  if (!Object.keys(built.products).length) {
    throw new Error('product history sync produced no series');
  }
  debugLog.info(
    'productHistory',
    `sync ok run_date=${built.run_date} slices=${built.run_dates.length} products=${Object.keys(built.products).length}`,
  );
  return built;
}
