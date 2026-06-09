import type { RateRow } from '../types';

/**
 * Curated provider + product cohorts treated as non-standard in the app even when
 * the payload `account_class` is absent or wrong. Keys mirror live CDR wire names
 * (e.g. Pi export uses "RACQ Bank", "Westpac").
 */
const NON_STANDARD_PRODUCTS: Readonly<Record<string, readonly string[]>> = {
  racq: ['Green Home Loan', 'Green Home Loan Investment'],
  westpac: ['Sustainable Upgrades Investment', 'Sustainable Upgrades Investment Loan'],
};

function providerKey(provider: string): string | null {
  const p = provider.trim().toLowerCase();
  if (p.includes('racq')) return 'racq';
  if (p.includes('westpac')) return 'westpac';
  return null;
}

/** True when bank + product name match a curated non-standard cohort. */
export function isKnownNonStandardProduct(row: RateRow): boolean {
  const key = providerKey(row.provider ?? '');
  if (!key) return false;
  const product = (row.product_name ?? '').trim().toLowerCase();
  if (!product) return false;
  return (NON_STANDARD_PRODUCTS[key] ?? []).some((name) => name.toLowerCase() === product);
}
