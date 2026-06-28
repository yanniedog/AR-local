import { computeLvr, depositToReachLvr, EMPTY_CALC, normalizeCalcInputs } from '../src/data/calc';

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
});
