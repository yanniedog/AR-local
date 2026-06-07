import { computeChanges } from '../src/data/notifications';
import type { CorePayload, RateRow } from '../src/types';

const mk = (over: Partial<RateRow>): RateRow => ({
  provider: 'Bank A',
  product_key: 'k',
  product_name: 'Product',
  rate: '0.05',
  ...over,
});

function core(rate: string, rbaRate = 4.35, rbaDate = '2026-05-06'): CorePayload {
  return {
    schema_version: 1,
    run_date: '2026-05-19',
    sections: {
      Mortgage: { rates: [mk({ product_key: 'A|1', rate })], ribbon: emptyRibbon() },
      Savings: { rates: [], ribbon: emptyRibbon() },
      TD: { rates: [], ribbon: emptyRibbon() },
    },
    brands: {},
    rba: [
      { date: '2026-03-18', rate: 4.1 },
      { date: rbaDate, rate: rbaRate },
    ],
  };
}

function emptyRibbon() {
  return {
    counts: { rates: 0, products: 0, providers: 0 },
    range: { min: null, max: null, mean: null, median: null },
    providers: [],
  };
}

describe('computeChanges', () => {
  test('no previous payload -> no messages', () => {
    expect(computeChanges(null, core('0.05'), [], 5)).toEqual([]);
  });

  test('best-rate move beyond threshold notifies', () => {
    const msgs = computeChanges(core('0.0579'), core('0.0574'), [], 5);
    expect(msgs.length).toBeGreaterThanOrEqual(1);
    expect(msgs[0].title).toContain('Home loans');
  });

  test('move below threshold is ignored', () => {
    expect(computeChanges(core('0.0576'), core('0.0574'), [], 5)).toEqual([]);
  });

  test('RBA change notifies', () => {
    const before = core('0.05', 4.35, '2026-05-06');
    const after = core('0.05', 4.6, '2026-06-10');
    const msgs = computeChanges(before, after, [], 5);
    expect(msgs.some((m) => m.title.includes('RBA'))).toBe(true);
  });

  test('RBA date-only change (same rate) is ignored', () => {
    const before = core('0.05', 4.35, '2026-05-06');
    const after = core('0.05', 4.35, '2026-06-10');
    const msgs = computeChanges(before, after, [], 5);
    expect(msgs.some((m) => m.title.includes('RBA'))).toBe(false);
  });

  test('watchlisted product change notifies', () => {
    const msgs = computeChanges(core('0.0579'), core('0.0574'), ['A|1'], 5);
    expect(msgs.some((m) => m.body.includes('→'))).toBe(true);
  });

  function multiRowCore(rates: { rate_index: number; rate: string }[]): CorePayload {
    return {
      schema_version: 1,
      run_date: '2026-05-19',
      sections: {
        Mortgage: { rates: rates.map((r) => mk({ product_key: 'M|1', ...r })), ribbon: emptyRibbon() },
        Savings: { rates: [], ribbon: emptyRibbon() },
        TD: { rates: [], ribbon: emptyRibbon() },
      },
      brands: {},
      rba: [{ date: '2026-05-06', rate: 4.35 }],
    };
  }

  test('watchlist matches rows by rate_index (catches non-first row change)', () => {
    const before = multiRowCore([
      { rate_index: 1, rate: '0.0600' },
      { rate_index: 2, rate: '0.0700' },
    ]);
    const after = multiRowCore([
      { rate_index: 1, rate: '0.0600' },
      { rate_index: 2, rate: '0.0650' }, // 2nd row moved 50bps
    ]);
    expect(computeChanges(before, after, ['M|1'], 5).some((m) => m.body.includes('→'))).toBe(true);
  });

  test('watchlist ignores pure row-order changes', () => {
    const before = multiRowCore([
      { rate_index: 1, rate: '0.0600' },
      { rate_index: 2, rate: '0.0700' },
    ]);
    const after = multiRowCore([
      { rate_index: 2, rate: '0.0700' },
      { rate_index: 1, rate: '0.0600' }, // same rates, swapped order
    ]);
    expect(computeChanges(before, after, ['M|1'], 5)).toEqual([]);
  });
});
