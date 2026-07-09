import { countSuitabilityExclusions, nameRestrictsAccess } from '../src/data/access';
import {
  bpsBetween,
  formatBalanceRange,
  formatRate,
  formatRateDigits,
  formatTerm,
  humanizeEnum,
  isBroadlyAvailable,
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
    expect(formatRate(4.35)).toBe('4.35%');
  });

  test('formatRateDigits omits percent suffix', () => {
    expect(formatRateDigits('0.0634')).toBe('6.34');
    expect(formatRateDigits(4.35)).toBe('4.35');
  });

  test('bpsBetween', () => {
    expect(bpsBetween(0.0579, 0.0574)).toBe(5);
    expect(bpsBetween(null, 0.05)).toBeNull();
  });

  test('humanizeEnum', () => {
    expect(humanizeEnum('PRINCIPAL_AND_INTEREST')).toBe('Principal & interest');
    expect(humanizeEnum('OWNER_OCCUPIED')).toBe('Owner occupied');
    expect(humanizeEnum('OFFSET')).toBe('Mortgage offset');
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

  test('formatTerm parses ISO duration in term (month-valued fixed terms)', () => {
    // ribbon_fixed_term mirrors the number regardless of unit, so term is authoritative.
    expect(formatTerm({ term: 'P36M', ribbon_fixed_term: '36' } as RateRow)).toBe('3 yrs');
    expect(formatTerm({ term: 'P3Y', ribbon_fixed_term: '3' } as RateRow)).toBe('3 yrs');
    expect(formatTerm({ term: 'P12M' } as RateRow)).toBe('1 yr');
    expect(formatTerm({ term: 'P18M' } as RateRow)).toBe('18 mo');
  });

  test('isNonStandard', () => {
    expect(isNonStandard({ account_class: 'non_standard' } as RateRow)).toBe(true);
    expect(isNonStandard({ account_class: 'standard' } as RateRow)).toBe(false);
    expect(isNonStandard({} as RateRow)).toBe(false);
  });

  test('isNonStandard matches curated RACQ and Westpac green/sustainable loans', () => {
    const racqGreen = {
      provider: 'RACQ Bank',
      product_name: 'Green Home Loan',
      account_class: 'standard',
    } as RateRow;
    const racqGreenInv = {
      provider: 'RACQ Bank',
      product_name: 'Green Home Loan Investment',
      account_class: '',
    } as RateRow;
    const westpacSustainable = {
      provider: 'Westpac',
      product_name: 'Sustainable Upgrades Investment Loan',
      account_class: 'standard',
    } as RateRow;
    expect(isNonStandard(racqGreen)).toBe(true);
    expect(isNonStandard(racqGreenInv)).toBe(true);
    expect(isNonStandard(westpacSustainable)).toBe(true);
    expect(
      isNonStandard({
        provider: 'Westpac Banking Corporation',
        product_name: 'Sustainable Upgrades Investment',
        account_class: 'standard',
      } as RateRow),
    ).toBe(true);
    expect(
      isNonStandard({
        provider: 'Westpac',
        product_name: 'Sustainable Upgrades Home Loan',
        account_class: 'standard',
      } as RateRow),
    ).toBe(true);
    expect(
      isNonStandard({
        provider: 'Greater Bank',
        product_name: 'Green Home Loan',
        account_class: 'standard',
      } as RateRow),
    ).toBe(false);
  });

  test('nameRestrictsAccess flags narrowly available product names', () => {
    expect(nameRestrictsAccess('Police Bank Staff Home Loan')).toBe(true);
    expect(nameRestrictsAccess('Nurses & Midwives Health Saver')).toBe(true);
    expect(nameRestrictsAccess('Teachers Union Members Saver')).toBe(true);
    expect(nameRestrictsAccess('Business Cash Management Account')).toBe(true);
    expect(nameRestrictsAccess('Student Everyday Account')).toBe(true);
    // Mainstream retail names stay broadly available.
    expect(nameRestrictsAccess('Basic Variable Home Loan')).toBe(false);
    expect(nameRestrictsAccess('Online Saver')).toBe(false);
    // Retail "Education Saver" (a savings product) is not occupation-restricted.
    expect(nameRestrictsAccess('Education Saver')).toBe(false);
    expect(nameRestrictsAccess('Darling Downs Education Saver')).toBe(false);
    // ...but an explicit educator occupation restriction still flags.
    expect(nameRestrictsAccess('Educators Rewards Saver')).toBe(true);
    expect(nameRestrictsAccess('')).toBe(false);
    expect(nameRestrictsAccess(null)).toBe(false);
  });

  test('countSuitabilityExclusions tallies non-standard and access categories', () => {
    const counts = countSuitabilityExclusions([
      { account_class: 'standard', product_name: 'Basic Variable Home Loan' },
      { account_class: 'non_standard', product_name: 'FX Term Deposit' },
      { account_class: 'standard', product_name: 'Staff Home Loan' },
      { account_class: 'standard', product_name: 'Educators Rewards Saver' },
      { account_class: 'standard', product_name: 'Education Saver' },
    ]);
    expect(counts.total).toBe(3);
    expect(counts.nonStandard).toBe(1);
    expect(counts.byAccess.staff).toBe(1);
    expect(counts.byAccess.occupation).toBe(1);
    expect(counts.byAccess.business).toBeUndefined();
  });

  test('isBroadlyAvailable excludes non-standard, curated, and access-restricted rows', () => {
    const mainstream = {
      provider: 'Bank A',
      product_name: 'Basic Variable Home Loan',
      account_class: 'standard',
    } as RateRow;
    const backendNonStandard = {
      provider: 'Bank A',
      product_name: 'FX Term Deposit',
      account_class: 'non_standard',
    } as RateRow;
    const curated = {
      provider: 'RACQ Bank',
      product_name: 'Green Home Loan',
      account_class: 'standard',
    } as RateRow;
    const staffOnly = {
      provider: 'Police Bank',
      product_name: 'Staff Home Loan',
      account_class: 'standard',
    } as RateRow;
    expect(isBroadlyAvailable(mainstream)).toBe(true);
    expect(isBroadlyAvailable(backendNonStandard)).toBe(false);
    expect(isBroadlyAvailable(curated)).toBe(false);
    expect(isBroadlyAvailable(staffOnly)).toBe(false);
    // Defensive: never throws on null/undefined rows.
    expect(isBroadlyAvailable(null)).toBe(false);
    expect(isBroadlyAvailable(undefined)).toBe(false);
  });
});
