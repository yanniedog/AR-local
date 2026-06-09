import type { DetailItem, ProductDetail, RateRow } from '../types';

/** CDR featureType code from a details payload feature row (label or name). */
export function featureTypeKey(item: DetailItem): string {
  return (item.label ?? item.name ?? '').trim();
}

export function productFeatureTypes(detail: ProductDetail | null | undefined): Set<string> {
  const out = new Set<string>();
  for (const it of detail?.features ?? []) {
    const key = featureTypeKey(it);
    if (key) out.add(key);
  }
  return out;
}

/** True when the product lists every selected featureType in details.features. */
export function productHasAllFeatures(
  productKey: string,
  required: string[],
  lookup: Record<string, ProductDetail> | null | undefined,
): boolean {
  if (required.length === 0) return true;
  if (!lookup) return false;
  const types = productFeatureTypes(lookup[productKey]);
  return required.every((f) => types.has(f));
}

/** Distinct featureType codes for products in rows, sorted by frequency then label. */
export function distinctAccountFeatures(
  rows: RateRow[],
  lookup: Record<string, ProductDetail> | null | undefined,
): string[] {
  if (!lookup) return [];
  const counts = new Map<string, number>();
  const seen = new Set<string>();
  for (const row of rows) {
    if (seen.has(row.product_key)) continue;
    seen.add(row.product_key);
    for (const key of productFeatureTypes(lookup[row.product_key])) {
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([k]) => k);
}
