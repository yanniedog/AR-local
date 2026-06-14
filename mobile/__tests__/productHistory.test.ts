import {
  buildProductHistoryFromCores,
  extractProductSeries,
  hasProductSeries,
  normalizeProductHistoryPayload,
  productSeriesRecord,
  type ProductHistoryPayload,
} from '../src/data/productHistory';
import type { CorePayload, RateRow, SectionKey } from '../src/types';

const EMPTY_RIBBON = {
  counts: { rates: 0, products: 0, providers: 0 },
  range: { min: null, max: null, mean: null, median: null },
  providers: [],
};

function rateRow(productKey: string, rate: string): RateRow {
  return { provider: 'Bank', product_key: productKey, product_name: productKey, rate };
}

function core(runDate: string, rowsBySection: Partial<Record<SectionKey, RateRow[]>>): CorePayload {
  return {
    schema_version: 1,
    run_date: runDate,
    sections: {
      Mortgage: { rates: rowsBySection.Mortgage ?? [], ribbon: EMPTY_RIBBON },
      Savings: { rates: rowsBySection.Savings ?? [], ribbon: EMPTY_RIBBON },
      TD: { rates: rowsBySection.TD ?? [], ribbon: EMPTY_RIBBON },
    },
    brands: {},
    rba: [],
  };
}

describe('buildProductHistoryFromCores', () => {
  it('tracks the section-best (min for loans) rate per product per day, aligned to run_dates', () => {
    const cores = new Map<string, CorePayload>([
      ['2026-05-13', core('2026-05-13', { Mortgage: [rateRow('P|1', '0.0610'), rateRow('P|1', '0.0590')] })],
      ['2026-06-10', core('2026-06-10', { Mortgage: [rateRow('P|1', '0.0555'), rateRow('P|1', '0.0570')] })],
    ]);
    const built = buildProductHistoryFromCores(cores, ['2026-05-13', '2026-06-10'], '2026-06-10');
    expect(built.run_dates).toEqual(['2026-05-13', '2026-06-10']);
    // Mortgage lowerIsBetter → min of the product's tiers each day.
    expect(built.products['P|1']).toEqual([0.059, 0.0555]);
  });

  it('uses max for deposit sections (higher is better)', () => {
    const cores = new Map<string, CorePayload>([
      ['2026-05-13', core('2026-05-13', { Savings: [rateRow('S|1', '0.045'), rateRow('S|1', '0.050')] })],
    ]);
    const built = buildProductHistoryFromCores(cores, ['2026-05-13'], '2026-05-13');
    expect(built.products['S|1']).toEqual([0.05]);
  });

  it('restricts to the current catalog and leaves missing days null', () => {
    const cores = new Map<string, CorePayload>([
      // Old day has a delisted product Q plus current product P.
      ['2026-05-13', core('2026-05-13', { Mortgage: [rateRow('P|1', '0.061'), rateRow('Q|9', '0.07')] })],
      // Latest day (current catalog) has only P.
      ['2026-06-10', core('2026-06-10', { Mortgage: [rateRow('P|1', '0.055')] })],
    ]);
    const built = buildProductHistoryFromCores(cores, ['2026-05-13', '2026-06-10'], '2026-06-10');
    expect(built.products['P|1']).toEqual([0.061, 0.055]);
    expect(built.products['Q|9']).toBeUndefined(); // delisted → not in current catalog
  });

  it('fills days without a downloaded core from the existing payload (incremental sync)', () => {
    const existing: ProductHistoryPayload = {
      schema_version: 1,
      run_date: '2026-05-13',
      run_dates: ['2026-05-13'],
      products: { 'P|1': [0.061] },
    };
    // Only the new day's core is provided; the old day must come from `existing`.
    const cores = new Map<string, CorePayload>([
      ['2026-06-10', core('2026-06-10', { Mortgage: [rateRow('P|1', '0.055')] })],
    ]);
    const built = buildProductHistoryFromCores(cores, ['2026-05-13', '2026-06-10'], '2026-06-10', existing);
    expect(built.products['P|1']).toEqual([0.061, 0.055]);
  });
});

describe('extractProductSeries / productSeriesRecord / hasProductSeries', () => {
  const payload: ProductHistoryPayload = {
    schema_version: 1,
    run_date: '2026-06-10',
    run_dates: ['2026-05-13', '2026-05-19', '2026-06-10'],
    products: { 'P|1': [0.061, null, 0.055] },
  };

  it('aligns a product series onto an arbitrary date axis', () => {
    expect(extractProductSeries(payload, 'P|1', ['2026-05-13', '2026-06-10'])).toEqual([0.061, 0.055]);
    // Unknown date → null; unknown product → all nulls.
    expect(extractProductSeries(payload, 'P|1', ['2026-01-01'])).toEqual([null]);
    expect(extractProductSeries(payload, 'X|9', ['2026-05-13'])).toEqual([null]);
  });

  it('builds a date→value record for the chart highlight series', () => {
    expect(productSeriesRecord(payload, 'P|1')).toEqual({
      '2026-05-13': 0.061,
      '2026-05-19': null,
      '2026-06-10': 0.055,
    });
    expect(productSeriesRecord(payload, 'X|9')).toEqual({});
  });

  it('hasProductSeries reflects whether any finite value exists', () => {
    expect(hasProductSeries(payload, 'P|1')).toBe(true);
    expect(hasProductSeries(payload, 'X|9')).toBe(false);
    expect(hasProductSeries(null, 'P|1')).toBe(false);
  });
});

describe('normalizeProductHistoryPayload', () => {
  it('accepts a well-formed payload and coerces non-positive/non-finite to null', () => {
    const out = normalizeProductHistoryPayload({
      schema_version: 1,
      run_date: '2026-06-10',
      core_sha: 'sha-current',
      run_dates: ['2026-05-13', '2026-06-10'],
      products: { 'P|1': [0.06, 0], 'Z|0': ['x', null] },
    });
    expect(out?.run_dates).toEqual(['2026-05-13', '2026-06-10']);
    expect(out?.core_sha).toBe('sha-current');
    expect(out?.products['P|1']).toEqual([0.06, null]); // 0 → null
    expect(out?.products['Z|0']).toBeUndefined(); // no finite values → dropped
  });

  it('rejects payloads with no run_date, invalid dates, or no products', () => {
    expect(normalizeProductHistoryPayload(null)).toBeNull();
    expect(normalizeProductHistoryPayload({ run_dates: ['2026-05-13'], products: {} })).toBeNull();
    expect(
      normalizeProductHistoryPayload({ run_date: '2026-06-10', run_dates: ['not-a-date'], products: { a: [1] } }),
    ).toBeNull();
    expect(
      normalizeProductHistoryPayload({ run_date: '2026-06-10', run_dates: ['2026-06-10'], products: {} }),
    ).toBeNull();
  });
});
