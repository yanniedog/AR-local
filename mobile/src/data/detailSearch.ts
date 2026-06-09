import type { ProductDetail } from '../types';

export interface SearchIndexPayload {
  schema_version: number;
  run_date: string;
  products: Record<string, string>;
}

type DetailIndex = Map<string, string>;
let runtimeCache: { ref: Record<string, ProductDetail> | null | undefined; index: DetailIndex } | null = null;
const queryMemo = new Map<string, Set<string>>();

function normalizeBlob(text: string): string {
  return text.trim().toLowerCase().replace(/\s+/g, ' ');
}

function detailItemsText(items: ProductDetail['fees']): string[] {
  if (!items?.length) return [];
  const parts: string[] = [];
  for (const item of items) {
    if (item.label) parts.push(String(item.label));
    if (item.name) parts.push(String(item.name));
    if (item.value != null && item.value !== '') parts.push(String(item.value));
    if (item.info) parts.push(String(item.info));
  }
  return parts;
}

export function productDetailSearchText(detail: ProductDetail | null | undefined): string {
  if (!detail) return '';
  const chunks: string[] = [];
  if (detail.description) chunks.push(detail.description);
  chunks.push(...detailItemsText(detail.fees));
  chunks.push(...detailItemsText(detail.features));
  chunks.push(...detailItemsText(detail.eligibility));
  chunks.push(...detailItemsText(detail.constraints));
  return normalizeBlob(chunks.join(' '));
}

export function detailSearchIndex(detailsProducts?: Record<string, ProductDetail> | null): DetailIndex {
  if (runtimeCache && runtimeCache.ref === detailsProducts) return runtimeCache.index;
  const index: DetailIndex = new Map();
  if (detailsProducts) {
    for (const [key, detail] of Object.entries(detailsProducts)) {
      const text = productDetailSearchText(detail);
      if (text) index.set(key, text);
    }
  }
  runtimeCache = { ref: detailsProducts, index };
  return index;
}

export function resetDetailSearchIndexCache(): void {
  runtimeCache = null;
  queryMemo.clear();
}

export function productKeysMatchingIndex(index: SearchIndexPayload | null | undefined, query: string): Set<string> | null {
  const q = query.trim().toLowerCase();
  if (!q || !index?.products) return null;
  const memo = `${index.run_date}:${q}`;
  if (queryMemo.has(memo)) return queryMemo.get(memo)!;
  const tokens = q.split(/\s+/).filter(Boolean);
  const hits = new Set<string>();
  for (const [key, blob] of Object.entries(index.products)) {
    if (tokens.every((t) => blob.includes(t))) hits.add(key);
  }
  queryMemo.set(memo, hits);
  return hits;
}

export function rowMatchesSearchQuery(
  row: { provider: string; product_name: string; product_key: string },
  query: string,
  payloadIndex?: SearchIndexPayload | null,
  runtimeDetailText?: string,
): boolean {
  const q = query.trim();
  if (!q) return true;
  const needle = q.toLowerCase();
  const hits = productKeysMatchingIndex(payloadIndex ?? null, q);
  if (hits) return hits.has(row.product_key);
  if (row.provider.toLowerCase().includes(needle) || row.product_name.toLowerCase().includes(needle)) return true;
  return runtimeDetailText ? runtimeDetailText.includes(needle) : false;
}
