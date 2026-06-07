import {
  bpsBetween,
  formatBalanceRange,
  formatRate,
  formatTerm,
  humanizeEnum,
  isNonStandard,
  toFraction,
} from '../src/data/format';
import type { RateRow } from '../src/types';

describe('format', () => {
  test('toFraction normalizes fractions and percents', () => {
    expect(toFraction('0.0634')).toBeCloseTo(0.0634);
    expect(toFraction('6.34')).toBeCloseTo(0.0634);
    expect(toFraction('')).toBeNull();
    expect(toFraction('0')).toBeNull();
    expect(toFraction(undefined)).toBeNull();
  });

  test('formatRate renders a percentage', () => {
    expect(formatRate('0.0634')).toBe('6.34%');
    expect(formatRate('0.045', 2)).toBe('4.50%');
    expect(formatRate(null)).toBe('—');
  });

  test('bpsBetween', () => {
    expect(bpsBetween(0.0579, 0.0574)).toBe(5);
    expect(bpsBetween(null, 0.05)).toBeNull();
  });

  test('humanizeEnum', () => {
    expect(humanizeEnum('PRINCIPAL_AND_INTEREST')).toBe('Principal & interest');
    expect(humanizeEnum('OWNER_OCCUPIED')).toBe('Owner occupied');
    expect(humanizeEnum('')).toBe('');
  });

  test('formatBalanceRange', () => {
    expect(formatBalanceRange('0', '50000')).toBe('$0–$50k');
    expect(formatBalanceRange('250000', '')).toBe('$250k+');
    expect(formatBalanceRange('', '')).toBe('');
  });

  test('formatTerm', () => {
    expect(formatTerm({ term_months: 12 } as RateRow)).toBe('1 yr');
    expect(formatTerm({ term_months: 6 } as RateRow)).toBe('6 mo');
    expect(formatTerm({} as RateRow)).toBe('');
  });

  test('isNonStandard', () => {
    expect(isNonStandard({ account_class: 'non_standard' } as RateRow)).toBe(true);
    expect(isNonStandard({ account_class: 'standard' } as RateRow)).toBe(false);
    expect(isNonStandard({} as RateRow)).toBe(false);
  });
});
