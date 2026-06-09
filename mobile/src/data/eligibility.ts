import type { DetailItem, ProductDetail, RateRow } from '../types';
import { sortByDisplayLabel } from './format';

/** CDR eligibilityType code from a details payload eligibility row (label or name). */
export function eligibilityTypeKey(item: DetailItem): string {
  return (item.label ?? item.name ?? '').trim();
}

export function productEligibilityTypes(detail: ProductDetail | null | undefined): Set<string> {
  const out = new Set<string>();
  for (const it of detail?.eligibility ?? []) {
    const key = eligibilityTypeKey(it);
    if (key) out.add(key);
  }
  return out;
}

/** True when the product lists every selected eligibilityType in details.eligibility. */
export function productHasAllEligibilityCriteria(
  productKey: string,
  required: string[],
  lookup: Record<string, ProductDetail> | null | undefined,
): boolean {
  if (required.length === 0) return true;
  if (!lookup) return false;
  const types = productEligibilityTypes(lookup[productKey]);
  return required.every((c) => types.has(c));
}

/** Distinct eligibilityType codes for products in rows, sorted alphabetically by display label. */
export function distinctEligibilityCriteria(
  rows: RateRow[],
  lookup: Record<string, ProductDetail> | null | undefined,
): string[] {
  if (!lookup) return [];
  const keys = new Set<string>();
  const seen = new Set<string>();
  for (const row of rows) {
    if (seen.has(row.product_key)) continue;
    seen.add(row.product_key);
    for (const key of productEligibilityTypes(lookup[row.product_key])) {
      keys.add(key);
    }
  }
  return sortByDisplayLabel(Array.from(keys));
}
