import {
  distinctAccountFeatures,
  featureTypeKey,
  productFeatureTypes,
  productHasAllFeatures,
} from '../src/data/features';
import type { ProductDetail } from '../src/types';

describe('features', () => {
  test('featureTypeKey prefers label over name', () => {
    expect(featureTypeKey({ label: 'OFFSET', name: '100% offset' })).toBe('OFFSET');
    expect(featureTypeKey({ name: 'REDRAW' })).toBe('REDRAW');
  });

  test('productHasAllFeatures requires every selected featureType', () => {
    const lookup: Record<string, ProductDetail> = {
      'A|1': {
        features: [{ label: 'OFFSET' }, { label: 'REDRAW' }],
      },
      'B|1': {
        features: [{ label: 'OFFSET' }],
      },
    };
    expect(productHasAllFeatures('A|1', [], lookup)).toBe(true);
    expect(productHasAllFeatures('A|1', ['OFFSET'], lookup)).toBe(true);
    expect(productHasAllFeatures('A|1', ['OFFSET', 'REDRAW'], lookup)).toBe(true);
    expect(productHasAllFeatures('B|1', ['OFFSET', 'REDRAW'], lookup)).toBe(false);
    expect(productHasAllFeatures('A|1', ['OFFSET'], null)).toBe(false);
  });

  test('distinctAccountFeatures counts unique products and sorts by frequency', () => {
    const lookup: Record<string, ProductDetail> = {
      'A|1': { features: [{ label: 'OFFSET' }, { label: 'REDRAW' }] },
      'B|1': { features: [{ label: 'OFFSET' }] },
      'C|1': { features: [{ label: 'DIGITAL_BANKING' }] },
    };
    const rows = [
      { product_key: 'A|1', provider: 'X', product_name: 'A', rate: '0.05' },
      { product_key: 'A|1', provider: 'X', product_name: 'A', rate: '0.06' },
      { product_key: 'B|1', provider: 'Y', product_name: 'B', rate: '0.05' },
      { product_key: 'C|1', provider: 'Z', product_name: 'C', rate: '0.05' },
    ];
    expect(distinctAccountFeatures(rows, lookup)).toEqual(['OFFSET', 'DIGITAL_BANKING', 'REDRAW']);
    expect(productFeatureTypes(lookup['A|1'])).toEqual(new Set(['OFFSET', 'REDRAW']));
  });
});
