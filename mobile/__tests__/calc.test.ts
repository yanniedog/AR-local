import {
  computeLvr,
  depositToReachLvr,
  EMPTY_CALC,
  monthlyPayment,
  normalizeCalcInputs,
  simulateOffset,
} from '../src/data/calc';

describe('computeLvr (buying)', () => {
  it('derives loan and LVR from price, deposit and costs', () => {
    const r = computeLvr({ ...EMPTY_CALC, mode: 'buy', propertyValue: '650000', deposit: '130000', costs: '30000' });
    // deposit applied = 130k - 30k costs = 100k → loan 550k → LVR 84.6%
    expect(r.depositApplied).toBe(100000);
    expect(r.loan).toBe(550000);
    expect(r.lvr).toBeCloseTo(84.615, 2);
  });

  it('returns nulls until enough is entered', () => {
    expect(computeLvr({ ...EMPTY_CALC, propertyValue: '', deposit: '100000' }).lvr).toBeNull();
  });
});

describe('computeLvr (refinancing)', () => {
  it('uses current loan balance over property value', () => {
    const r = computeLvr({ ...EMPTY_CALC, mode: 'refi', propertyValue: '800000', loanBalance: '600000' });
    expect(r.lvr).toBeCloseTo(75, 5);
    expect(r.loan).toBe(600000);
  });
});

describe('depositToReachLvr', () => {
  it('computes the extra deposit to drop into a lower band', () => {
    // 650k property, 100k applied (LVR 84.6%). To reach ≤80% need 130k → extra 30k.
    expect(depositToReachLvr(650000, 100000, 80)).toBeCloseTo(30000, 2);
    expect(depositToReachLvr(650000, 200000, 80)).toBe(0); // already below
  });
});

describe('normalizeCalcInputs', () => {
  it('coerces partial/garbage input to a safe shape', () => {
    expect(normalizeCalcInputs(null)).toEqual(EMPTY_CALC);
    expect(normalizeCalcInputs({ mode: 'refi', propertyValue: 5 as unknown as string }).mode).toBe('refi');
    expect(normalizeCalcInputs({ mode: 'weird' as never }).mode).toBe('buy');
  });

  it('coerces the offset fields to a safe shape', () => {
    expect(normalizeCalcInputs(null).wantsOffset).toBe(false);
    expect(normalizeCalcInputs({ wantsOffset: true, offsetBalance: '30000' }).offsetBalance).toBe('30000');
    expect(normalizeCalcInputs({ wantsOffset: 'yes' as never }).wantsOffset).toBe(false);
  });
});

describe('monthlyPayment', () => {
  it('amortises with interest and straight-lines at 0%', () => {
    expect(monthlyPayment(1200, 0, 12)).toBeCloseTo(100, 6);
    // 500k @ 6% over 25y ≈ $3,221/mo
    expect(monthlyPayment(500000, 0.06, 300)).toBeCloseTo(3221.51, 0);
  });
});

describe('simulateOffset', () => {
  const loan = 500000;
  const rate = 0.06;
  const months = 300;

  it('saves interest and shortens the term with an offset', () => {
    const r = simulateOffset(loan, rate, months, 50000)!;
    expect(r.offset).toBe(50000);
    expect(r.effectiveBalance).toBe(450000);
    expect(r.interestSaved).toBeGreaterThan(0);
    expect(r.monthsSaved).toBeGreaterThan(0);
    expect(r.monthsToPayoff).toBeLessThan(months);
    // An offset can never make the loan cost more.
    expect(r.interestWith).toBeLessThan(r.interestWithout);
  });

  it('is essentially a no-op with a zero offset', () => {
    const r = simulateOffset(loan, rate, months, 0)!;
    expect(r.monthsSaved).toBeLessThanOrEqual(1);
    expect(r.interestSaved).toBeLessThan(1);
    expect(r.monthsToPayoff).toBeGreaterThanOrEqual(months - 1);
  });

  it('clamps an over-large offset to the loan and clears quickly', () => {
    const r = simulateOffset(loan, rate, months, 999999)!;
    expect(r.offset).toBe(loan);
    expect(r.effectiveBalance).toBe(0);
    expect(r.monthsToPayoff).toBeLessThan(months);
    expect(r.interestWith).toBeCloseTo(0, 2);
  });

  it('returns null for insufficient inputs', () => {
    expect(simulateOffset(0, rate, months, 10000)).toBeNull();
    expect(simulateOffset(loan, 0, months, 10000)).toBeNull();
    expect(simulateOffset(loan, rate, 0, 10000)).toBeNull();
  });
});
