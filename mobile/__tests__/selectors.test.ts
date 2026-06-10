import {
  EMPTY_FILTERS,
  activeFilterCount,
  bestRow,
  distinctProviders,
  distinctValues,
  filterRows,
  findByKey,
  groupByProvider,
  normalizeSortKey,
  queryAndSort,
  sortRows,
} from '../src/data/selectors';
import type { RateRow, SectionKey } from '../src/types';

const mk = (over: Partial<RateRow>): RateRow => ({
  provider: 'Bank A',
  product_key: 'k',
  product_name: 'Product',
  rate: '0.05',
  ...over,
});

const mortgage: RateRow[] = [
  mk({ provider: 'Bank A', product_key: 'A|1', product_name: 'Cheap Loan', rate: '0.0574', rate_type: 'VARIABLE' }),
  mk({ provider: 'Bank B', product_key: 'B|1', product_name: 'Mid Loan', rate: '0.0612', rate_type: 'FIXED' }),
  mk({ provider: 'Bank C', product_key: 'C|1', product_name: 'Green Loan', rate: '0.0489', rate_type: 'VARIABLE', account_class: 'non_standard' }),
];

const savings: RateRow[] = [
  mk({ provider: 'Bank A', product_key: 'A|S', product_name: 'Saver', rate: '0.045' }),
  mk({ provider: 'Bank B', product_key: 'B|S', product_name: 'Bonus', rate: '0.052' }),
];

describe('selectors', () => {
  test('bestRow picks lowest for loans, ignoring non-standard', () => {
    const best = bestRow(mortgage, 'Mortgage');
    expect(best?.product_key).toBe('A|1'); // 5.74% — the green 4.89% is non-standard
    expect(best?.account_class).not.toBe('non_standard');
  });

  test('bestRow returns null when every candidate is non-standard by default', () => {
    expect(bestRow(mortgage.filter((row) => row.account_class === 'non_standard'), 'Mortgage')).toBeNull();
  });

  test('bestRow picks highest for deposits', () => {
    const best = bestRow(savings, 'Savings');
    expect(best?.product_key).toBe('B|S'); // 5.2%
  });

  test('bestRow includes non-standard when requested', () => {
    expect(bestRow(mortgage, 'Mortgage', true)?.product_key).toBe('C|1');
  });

  test('sortRows best-first by section direction', () => {
    const loans = sortRows(mortgage.filter((r) => r.account_class !== 'non_standard'), 'rate', 'Mortgage');
    expect(loans.map((r) => r.product_key)).toEqual(['A|1', 'B|1']);
    const deps = sortRows(savings, 'rate', 'Savings');
    expect(deps.map((r) => r.product_key)).toEqual(['B|S', 'A|S']);
  });

  test('sortRows by bank A-Z', () => {
    const sorted = sortRows(mortgage, 'bank', 'Mortgage');
    expect(sorted.map((r) => r.provider)).toEqual(['Bank A', 'Bank B', 'Bank C']);
  });

  test('normalizeSortKey accepts deep-link presets and defaults invalid values', () => {
    expect(normalizeSortKey('comparison')).toBe('comparison');
    expect(normalizeSortKey('bank')).toBe('bank');
    expect(normalizeSortKey('unexpected')).toBe('rate');
    expect(normalizeSortKey()).toBe('rate');
  });

  test('filterRows excludes non-standard by default and applies facets', () => {
    expect(filterRows(mortgage, EMPTY_FILTERS)).toHaveLength(2);
    expect(filterRows(mortgage, { ...EMPTY_FILTERS, includeNonStandard: true })).toHaveLength(3);
    expect(filterRows(mortgage, { ...EMPTY_FILTERS, rateTypes: ['FIXED'] })).toHaveLength(1);
    expect(filterRows(mortgage, { ...EMPTY_FILTERS, query: 'green', includeNonStandard: true })).toHaveLength(1);
  });

  test('filterRows applies depositKinds for deposit sections', () => {
    const deposits = [
      mk({ provider: 'Bank A', product_key: 'A|S', rate: '0.045', ribbon_deposit_kind: 'at_call' }),
      mk({ provider: 'Bank B', product_key: 'B|S', rate: '0.052', ribbon_deposit_kind: 'bonus' }),
      mk({ provider: 'Bank C', product_key: 'C|S', rate: '0.048', ribbon_deposit_kind: 'bonus' }),
    ];
    expect(filterRows(deposits, EMPTY_FILTERS)).toHaveLength(3);
    const bonus = filterRows(deposits, { ...EMPTY_FILTERS, depositKinds: ['bonus'] });
    expect(bonus.map((r) => r.product_key)).toEqual(['B|S', 'C|S']);
    const byProvider = filterRows(deposits, { ...EMPTY_FILTERS, providers: ['Bank A'] });
    expect(byProvider).toHaveLength(1);
  });

  test('filterRows applies interestPayments (TD facet) against interest_payment', () => {
    const td = [
      mk({ product_key: 'A|TD', rate: '0.05', interest_payment: 'monthly' }),
      mk({ product_key: 'B|TD', rate: '0.051', interest_payment: 'at_maturity' }),
    ];
    const monthly = filterRows(td, { ...EMPTY_FILTERS, interestPayments: ['monthly'] });
    expect(monthly.map((r) => r.product_key)).toEqual(['A|TD']);
  });

  test('filterRows applies accountFeatures from details (AND logic)', () => {
    const rows = [
      mk({ product_key: 'A|1', rate: '0.05' }),
      mk({ product_key: 'B|1', rate: '0.06' }),
      mk({ product_key: 'C|1', rate: '0.07' }),
    ];
    const details = {
      'A|1': { features: [{ label: 'OFFSET' }, { label: 'REDRAW' }] },
      'B|1': { features: [{ label: 'OFFSET' }] },
      'C|1': { features: [{ label: 'REDRAW' }] },
    };
    const offsetOnly = filterRows(rows, { ...EMPTY_FILTERS, accountFeatures: ['OFFSET'] }, details);
    expect(offsetOnly.map((r) => r.product_key)).toEqual(['A|1', 'B|1']);
    const offsetAndRedraw = filterRows(
      rows,
      { ...EMPTY_FILTERS, accountFeatures: ['OFFSET', 'REDRAW'] },
      details,
    );
    expect(offsetAndRedraw.map((r) => r.product_key)).toEqual(['A|1']);
    expect(filterRows(rows, { ...EMPTY_FILTERS, accountFeatures: ['OFFSET'] }, null)).toHaveLength(0);
  });

  test('activeFilterCount includes accountFeatures', () => {
    expect(activeFilterCount({ ...EMPTY_FILTERS, accountFeatures: ['OFFSET', 'REDRAW'] })).toBe(2);
  });

  test('queryAndSort end-to-end', () => {
    const out = queryAndSort(mortgage, { ...EMPTY_FILTERS, query: 'loan' }, 'rate', 'Mortgage');
    expect(out.map((r) => r.product_key)).toEqual(['A|1', 'B|1']);
  });

  test('activeFilterCount', () => {
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0);
    expect(activeFilterCount({ ...EMPTY_FILTERS, providers: ['Bank A'], includeNonStandard: true })).toBe(1);
  });

  test('distinctValues sorts by frequency then label', () => {
    expect(distinctValues(mortgage, 'rate_type')).toEqual(['VARIABLE', 'FIXED']);
  });

  test('distinctProviders empty input and falsey providers', () => {
    expect(distinctProviders([])).toEqual([]);
    const rows = [
      mk({ provider: 'Bank A', product_key: 'A|1' }),
      mk({ provider: '', product_key: 'E|1' }),
      mk({ provider: undefined as unknown as string, product_key: 'U|1' }),
    ];
    expect(distinctProviders(rows)).toEqual(['Bank A']);
  });

  test('distinctProviders sorted A–Z case-insensitive, not by frequency', () => {
    const rows = [
      mk({ provider: 'Zebra Bank', product_key: 'Z|1' }),
      mk({ provider: 'Zebra Bank', product_key: 'Z|2' }),
      mk({ provider: 'alpha credit', product_key: 'a|1' }),
      mk({ provider: 'Mid Bank', product_key: 'M|1' }),
      mk({ provider: 'Beta', product_key: 'B|1' }),
    ];
    expect(distinctProviders(rows)).toEqual(['alpha credit', 'Beta', 'Mid Bank', 'Zebra Bank']);
  });


  test('distinctProviders handles empty input and missing provider', () => {
    expect(distinctProviders([])).toEqual([]);
    const rows = [
      mk({ provider: '', product_key: 'e|1' }),
      mk({ provider: 'Bank A', product_key: 'A|1' }),
    ];
    expect(distinctProviders(rows)).toEqual(['Bank A']);
  });

  test('findByKey across sections', () => {
    const sections = {
      Mortgage: { rates: mortgage },
      Savings: { rates: savings },
      TD: { rates: [] },
    } as Record<SectionKey, { rates: RateRow[] }>;
    expect(findByKey(sections, 'B|S')?.section).toBe('Savings');
    expect(findByKey(sections, 'nope')).toBeNull();
  });

  test('groupByProvider aggregates best per section', () => {
    const sections = {
      Mortgage: { rates: mortgage },
      Savings: { rates: savings },
      TD: { rates: [] },
    } as Record<SectionKey, { rates: RateRow[] }>;
    const groups = groupByProvider(sections);
    const bankA = groups.find((g) => g.provider === 'Bank A');
    expect(bankA?.bestBySection.Mortgage?.product_key).toBe('A|1');
    expect(bankA?.bestBySection.Savings?.product_key).toBe('A|S');
  });
});
