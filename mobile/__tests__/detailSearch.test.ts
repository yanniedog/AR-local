import core from '../assets/sample/core.json';
import details from '../assets/sample/details.json';
import {
  detailSearchIndex,
  productDetailSearchText,
  productKeysMatchingIndex,
  resetDetailSearchIndexCache,
  rowMatchesSearchQuery,
  type SearchIndexPayload,
} from '../src/data/detailSearch';
import type { CorePayload, DetailsPayload, ProductDetail } from '../src/types';

const WESTPAC_KEY =
  'Westpac|HLSustainableUpgradesInvestment|RESIDENTIAL_MORTGAGES|Sustainable Upgrades Investment Loan';

describe('detailSearch', () => {
  afterEach(() => resetDetailSearchIndexCache());

  test('productDetailSearchText includes description and detail item fields', () => {
    const detail: ProductDetail = {
      description: 'Finance renewable energy upgrades.',
      features: [{ label: 'OFFSET', name: 'Offset account', info: '100% offset' }],
      fees: [{ label: 'UPFRONT', name: 'Application fee', value: 600 }],
      eligibility: [{ label: 'MIN_AGE', name: 'Minimum age', value: 18 }],
      constraints: [{ label: 'MAX_BALANCE', name: 'Maximum balance', info: 'Up to $2m' }],
    };
    const text = productDetailSearchText(detail);
    expect(text).toContain('renewable energy');
    expect(text).toContain('offset account');
    expect(text).toContain('application fee');
  });

  test('payload index matches energy for Westpac sustainable product', () => {
    const sampleDetails = details as DetailsPayload;
    const blob = sampleDetails.products[WESTPAC_KEY]
      ? `westpac sustainable ${sampleDetails.products[WESTPAC_KEY].description ?? ''}`
      : 'westpac sustainable energy efficiency';
    const index: SearchIndexPayload = {
      schema_version: 1,
      run_date: '2026-05-19',
      products: { [WESTPAC_KEY]: blob.toLowerCase() },
    };
    const row = (core as CorePayload).sections.Mortgage.rates.find((r) => r.product_key === WESTPAC_KEY);
    expect(row).toBeTruthy();
    expect(rowMatchesSearchQuery(row!, 'energy', index)).toBe(true);
    expect(productKeysMatchingIndex(index, 'energy')?.has(WESTPAC_KEY)).toBe(true);
  });

  test('prefers payload index over runtime detail blob building', () => {
    const index: SearchIndexPayload = {
      schema_version: 1,
      run_date: '2026-05-19',
      products: { 'Z|1': 'acme solar panel finance' },
    };
    const row = { provider: 'Acme', product_name: 'Loan', product_key: 'Z|1' };
    expect(rowMatchesSearchQuery(row, 'solar', index, undefined)).toBe(true);
    expect(detailSearchIndex(null).size).toBe(0);
  });
});
