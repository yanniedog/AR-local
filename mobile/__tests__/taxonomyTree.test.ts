import {
  childKeysAt,
  flattenTreeVisible,
  nodeKey,
  treeRootStats,
} from '../src/data/taxonomyTree';
import type { RateRow } from '../src/types';

const mk = (over: Partial<RateRow>): RateRow => ({
  provider: 'Bank A',
  product_key: 'k',
  product_name: 'Product',
  rate: '0.05',
  ...over,
});

/** Minimal mortgage slice mirroring bundled sample taxonomy_path shapes. */
const sampleMortgageRows: RateRow[] = [
  mk({
    provider: 'AMP - My AMP',
    product_key: 'A|1',
    rate: '0.0634',
    taxonomy_path: 'HOME_LOAN.OO.PI.VARIABLE.LVR_LE60',
  }),
  mk({
    provider: 'Bank B',
    product_key: 'B|1',
    rate: '0.0612',
    taxonomy_path: 'HOME_LOAN.OO.PI.FIXED.36M.LVR_70_80',
  }),
  mk({
    provider: 'Bank C',
    product_key: 'C|1',
    rate: '0.0650',
    taxonomy_path: 'HOME_LOAN.INV.PI.VARIABLE.LVR_70_80',
  }),
  mk({
    provider: 'Bank D',
    product_key: 'D|1',
    rate: '0.0580',
    taxonomy_path: 'HOME_LOAN.OO.PI.VARIABLE.LVR_70_80',
  }),
];

describe('taxonomyTree', () => {
  test('nodeKey joins path segments', () => {
    expect(nodeKey(['OO', 'PI'])).toBe('OO.PI');
    expect(nodeKey([])).toBe('');
  });

  test('childKeysAt returns next-level segments from sample rows', () => {
    expect(childKeysAt(sampleMortgageRows, 'Mortgage', [])).toEqual(['OO', 'INV']);
    expect(childKeysAt(sampleMortgageRows, 'Mortgage', ['OO'])).toEqual(['PI']);
    expect(childKeysAt(sampleMortgageRows, 'Mortgage', ['OO', 'PI'])).toEqual(['VARIABLE', 'FIXED']);
  });

  test('flattenTreeVisible lists top level when nothing expanded', () => {
    const flat = flattenTreeVisible(sampleMortgageRows, 'Mortgage', new Set());
    expect(flat.map((r) => r.seg)).toEqual(['OO', 'INV']);
    expect(flat.every((r) => r.depth === 0)).toBe(true);
    expect(flat.find((r) => r.seg === 'OO')!.stats.products).toBe(3);
    expect(flat.find((r) => r.seg === 'INV')!.stats.products).toBe(1);
  });

  test('flattenTreeVisible nests children when parent keys are expanded', () => {
    const expanded = new Set(['OO', 'OO.PI', 'OO.PI.VARIABLE']);
    const flat = flattenTreeVisible(sampleMortgageRows, 'Mortgage', expanded);
    expect(flat.map((r) => `${r.depth}:${r.seg}`)).toEqual([
      '0:OO',
      '1:PI',
      '2:VARIABLE',
      '3:LVR_LE60',
      '3:LVR_70_80',
      '2:FIXED',
      '0:INV',
    ]);
    const lvr70 = flat.find((r) => r.seg === 'LVR_70_80' && r.depth === 3)!;
    expect(lvr70.hasChildren).toBe(false);
    expect(lvr70.stats.products).toBe(1);
  });

  test('treeRootStats aggregates section-scoped rows', () => {
    const s = treeRootStats(sampleMortgageRows, 'Mortgage');
    expect(s.products).toBe(4);
    expect(s.providers).toBe(4);
    expect(s.count).toBe(4);
  });

  test('flattenTreeVisible respects includeNonStandard', () => {
    const withNs = [
      ...sampleMortgageRows,
      mk({
        product_key: 'E|1',
        rate: '0.04',
        account_class: 'non_standard',
        taxonomy_path: 'HOME_LOAN.OTHER.PI.VARIABLE.LVR_LE60',
      }),
    ];
    expect(flattenTreeVisible(withNs, 'Mortgage', new Set()).map((r) => r.seg)).toEqual(['OO', 'INV']);
    expect(flattenTreeVisible(withNs, 'Mortgage', new Set(), true).map((r) => r.seg)).toEqual([
      'OO',
      'INV',
      'OTHER',
    ]);
  });
});
