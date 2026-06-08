import { childrenOf, rowsUnder, segLabel, statsFor } from '../src/data/taxonomy';
import type { RateRow } from '../src/types';

const mk = (over: Partial<RateRow>): RateRow => ({
  provider: 'Bank A',
  product_key: 'k',
  product_name: 'Product',
  rate: '0.05',
  ...over,
});

const rows: RateRow[] = [
  mk({ provider: 'A', product_key: 'A|1', rate: '0.0574', taxonomy_path: 'HOME_LOAN.OO.PI.VARIABLE.LVR_LE60' }),
  mk({ provider: 'B', product_key: 'B|1', rate: '0.0612', taxonomy_path: 'HOME_LOAN.OO.PI.FIXED.36M.LVR_70_80' }),
  mk({ provider: 'C', product_key: 'C|1', rate: '0.0650', taxonomy_path: 'HOME_LOAN.INV.PI.VARIABLE.LVR_70_80' }),
];

describe('taxonomy', () => {
  test('segLabel maps codes to human labels', () => {
    expect(segLabel('OO')).toBe('Owner-occupied');
    expect(segLabel('INV')).toBe('Investor');
    expect(segLabel('VARIABLE')).toBe('Variable rate');
    expect(segLabel('LVR_LE60')).toBe('≤60% LVR');
    expect(segLabel('LVR_70_80')).toBe('70–80% LVR');
    expect(segLabel('36M')).toBe('3 years');
    expect(segLabel('6M')).toBe('6 months');
  });

  test('segLabel handles LVR edge cases and generic fallback', () => {
    expect(segLabel('LVR_UNSPECIFIED')).toBe('LVR n/a');
    expect(segLabel('LVR_NA')).toBe('LVR n/a');
    expect(segLabel('LVR_GT95')).toBe('95%+ LVR');
    expect(segLabel('LVR_GT80')).toBe('80%+ LVR');
    expect(segLabel('LVR_90')).toBe('≤90% LVR');
    expect(segLabel('')).toBe('Other');
    expect(segLabel('OTHER_TERM_TYPE')).toBe('Other term type');
  });

  test('childrenOf sorts LVR tiers numerically even with GT/LE prefixes', () => {
    const r = [
      mk({ product_key: 'a', rate: '0.06', taxonomy_path: 'HOME_LOAN.OO.PI.VARIABLE.LVR_GT95' }),
      mk({ product_key: 'b', rate: '0.05', taxonomy_path: 'HOME_LOAN.OO.PI.VARIABLE.LVR_LE60' }),
      mk({ product_key: 'c', rate: '0.055', taxonomy_path: 'HOME_LOAN.OO.PI.VARIABLE.LVR_70_80' }),
    ];
    expect(childrenOf(r, 'Mortgage', ['OO', 'PI', 'VARIABLE']).map((n) => n.seg)).toEqual([
      'LVR_LE60',
      'LVR_70_80',
      'LVR_GT95',
    ]);
  });

  test('childrenOf groups by the next taxonomy segment, ordered canonically', () => {
    expect(childrenOf(rows, 'Mortgage', []).map((n) => n.seg)).toEqual(['OO', 'INV']);
    expect(childrenOf(rows, 'Mortgage', ['OO']).map((n) => n.seg)).toEqual(['PI']);
    expect(childrenOf(rows, 'Mortgage', ['OO', 'PI']).map((n) => n.seg)).toEqual(['VARIABLE', 'FIXED']);
  });

  test('childrenOf reports counts and hasChildren', () => {
    const top = childrenOf(rows, 'Mortgage', []);
    const oo = top.find((n) => n.seg === 'OO')!;
    expect(oo.stats.count).toBe(2);
    expect(oo.hasChildren).toBe(true);
    const lvr = childrenOf(rows, 'Mortgage', ['OO', 'PI', 'VARIABLE']);
    expect(lvr.map((n) => n.seg)).toEqual(['LVR_LE60']);
    expect(lvr[0].hasChildren).toBe(false); // leaf
  });

  test('rowsUnder filters by path prefix', () => {
    expect(rowsUnder(rows, 'Mortgage', ['INV']).map((r) => r.product_key)).toEqual(['C|1']);
    expect(rowsUnder(rows, 'Mortgage', ['OO']).map((r) => r.product_key)).toEqual(['A|1', 'B|1']);
    expect(rowsUnder(rows, 'Mortgage', []).length).toBe(3);
  });

  test('statsFor computes the distribution', () => {
    const s = statsFor(rows);
    expect(s.count).toBe(3);
    expect(s.min).toBeCloseTo(0.0574);
    expect(s.max).toBeCloseTo(0.065);
    expect(s.median).toBeCloseTo(0.0612);
    expect(s.providers).toBe(3);
  });

  test('statsFor excludes non-standard by default', () => {
    const withNs = [...rows, mk({ product_key: 'D|1', rate: '0.0400', account_class: 'non_standard', taxonomy_path: 'HOME_LOAN.OO.PI.VARIABLE.LVR_LE60' })];
    expect(statsFor(withNs).min).toBeCloseTo(0.0574);
    expect(statsFor(withNs, true).min).toBeCloseTo(0.04);
  });
});
