import { computeChanges } from '../src/data/notifications';
import {
  addSubscription,
  buildSearchLabel,
  computeSubscriptionChanges,
  isProductSubscribed,
  makeProductSubscription,
  makeSearchSubscription,
  normalizeFilterSnapshot,
  removeSubscription,
  rowsForSearchSubscription,
} from '../src/data/subscriptions';
import type { CorePayload, RateRow } from '../src/types';

const mk = (over: Partial<RateRow>): RateRow => ({
  provider: 'Bank A',
  product_key: 'A|1',
  product_name: 'Home loan',
  rate: '0.05',
  rate_index: 1,
  rate_type: 'VARIABLE',
  taxonomy_path: 'HOME_LOAN.OO.PI.VARIABLE.LVR_70_80',
  ...over,
});

function emptyRibbon() {
  return {
    counts: { rates: 0, products: 0, providers: 0 },
    range: { min: null, max: null, mean: null, median: null },
    providers: [],
  };
}

function core(rows: RateRow[]): CorePayload {
  return {
    schema_version: 1,
    run_date: '2026-05-19',
    sections: {
      Mortgage: { rates: rows, ribbon: emptyRibbon() },
      Savings: { rates: [], ribbon: emptyRibbon() },
      TD: { rates: [], ribbon: emptyRibbon() },
    },
    brands: {},
    rba: [{ date: '2026-05-06', rate: 4.35 }],
  };
}

describe('subscription CRUD', () => {
  test('add dedupes by id', () => {
    const sub = makeProductSubscription(mk({}), 1);
    expect(addSubscription(addSubscription([], sub), sub)).toHaveLength(1);
  });

  test('product subscribed checks rate_index', () => {
    const row = mk({ product_key: 'P|1', rate_index: 2 });
    const list = addSubscription([], makeProductSubscription(row, 2));
    expect(isProductSubscribed(list, 'P|1', 2)).toBe(true);
  });
  test('product subscribed handles null rateIndex independently per product', () => {
    const row1 = mk({ product_key: 'P|1' });
    const list = addSubscription([], makeProductSubscription(row1, null));
    expect(isProductSubscribed(list, 'P|1', null)).toBe(true);
    expect(isProductSubscribed(list, 'P|2', null)).toBe(false);
    expect(isProductSubscribed(list, 'P|1', 0)).toBe(false);
  });

  test('removeSubscription removes product subscription', () => {
    const row = mk({ product_key: 'P|1', rate_index: 2 });
    const sub = makeProductSubscription(row, 2);
    const withSub = addSubscription([], sub);
    const withoutSub = removeSubscription(withSub, sub.id);
    expect(isProductSubscribed(withoutSub, 'P|1', 2)).toBe(false);
    expect(withoutSub).toHaveLength(0);
  });

  test('computeSubscriptionChanges silent when rate unchanged', () => {
    const row = mk({ product_key: 'P|1', rate_index: 0, rate: '0.05' });
    const before = core([row]);
    const after = core([{ ...row, rate: '0.05' }]);
    const subs = addSubscription([], makeProductSubscription(row, 0));
    expect(computeSubscriptionChanges(before, after, subs, 5)).toEqual([]);
  });

});

describe('filter matching helpers', () => {
  test('rowsForSearchSubscription applies filters', () => {
    const rows = [mk({ product_key: 'A|1', provider: 'Bank A', rate_type: 'VARIABLE' })];
    const sub = makeSearchSubscription({
      section: 'Mortgage',
      path: ['OO'],
      hierarchyScoped: true,
      query: '',
      filters: normalizeFilterSnapshot({
        providers: ['Bank A'],
        rateTypes: ['VARIABLE'],
        lvrTiers: [],
        repaymentTypes: [],
        loanPurposes: [],
        depositKinds: [],
        interestPayments: [],
        accountFeatures: [],
        eligibilityCriteria: [],
        includeNonStandard: false,
      }),
    });
    expect(rowsForSearchSubscription(core(rows), sub)).toHaveLength(1);
  });

  test('buildSearchLabel is compact', () => {
    const label = buildSearchLabel('Mortgage', ['OO'], 'bonus', {
      providers: [],
      rateTypes: [],
      lvrTiers: [],
      repaymentTypes: [],
      loanPurposes: [],
      depositKinds: [],
      interestPayments: [],
      accountFeatures: [],
      eligibilityCriteria: [],
      includeNonStandard: false,
    });
    expect(label).toContain('Home loans');
    expect(label).toContain('bonus');
  });
});

describe('computeSubscriptionChanges', () => {
  test('product subscription notifies on row rate move', () => {
    const before = core([mk({ rate: '0.0600', rate_index: 1 })]);
    const after = core([mk({ rate: '0.0550', rate_index: 1 })]);
    const sub = makeProductSubscription(mk({}), 1);
    expect(computeSubscriptionChanges(before, after, [sub], 5)[0].body).toContain('→');
  });

  test('computeChanges includes subscription messages', () => {
    const before = core([mk({ rate: '0.0600', rate_index: 1 })]);
    const after = core([mk({ rate: '0.0550', rate_index: 1 })]);
    const sub = makeProductSubscription(mk({}), 1);
    expect(computeChanges(before, after, [], 5, [sub]).some((m) => m.body.includes('→'))).toBe(true);
  });
});
