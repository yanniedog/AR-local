import type { AppHealthDataSnapshot } from './types';

const REASONS = new Set(['unsupported_section', 'out_of_section_category', 'no_rate',
  'discount_not_absolute_rate', 'inapplicable_rate_family']);
const SECTIONS = ['Mortgage', 'Savings', 'TD', 'Other'];
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const object = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;

export interface AccountingResult {
  present: boolean;
  valid: boolean;
  excludedRates: number;
  productsWithoutRates: number;
  sourceProducts: number;
  sourceRates: number;
  publishedRates: number;
  publishedProducts: number;
  providersWithRates: number;
}

/** Accept only a complete accounting equation, never an arbitrary missing-row allowance. */
export function validatePayloadAccounting(snapshot: AppHealthDataSnapshot): AccountingResult {
  const raw = snapshot.core?.coverage?.payload_accounting;
  const result: AccountingResult = { present: raw != null, valid: false, excludedRates: 0,
    productsWithoutRates: 0, sourceProducts: 0, sourceRates: 0, publishedRates: 0,
    publishedProducts: 0, providersWithRates: 0 };
  const a = object(raw);
  const sections = object(a?.sections);
  const exclusions = object(a?.exclusions);
  if (!a || a.schema_version !== 1 || !sections || !exclusions ||
      Object.keys(sections).length !== SECTIONS.length) return result;
  const fields = ['source_products', 'source_rates', 'published_rates', 'excluded_rates',
    'published_products', 'products_without_published_rates', 'providers_with_products', 'providers_with_published_rates'];
  if (fields.some((key) => !count(a[key]))) return result;
  const combined: Record<string, number> = {};
  let sourceRates = 0, publishedRates = 0, excludedRates = 0;
  for (const section of SECTIONS) {
    const s = object(sections[section]);
    const reasons = object(s?.exclusions);
    if (!s || !reasons || ['source_rates', 'published_rates', 'excluded_rates', 'published_products', 'published_providers']
      .some((key) => !count(s[key]))) return result;
    let excluded = 0;
    for (const [reason, value] of Object.entries(reasons)) {
      if (!REASONS.has(reason) || !count(value)) return result;
      excluded += value;
      combined[reason] = (combined[reason] ?? 0) + value;
    }
    if (s.excluded_rates !== excluded || s.source_rates !== Number(s.published_rates) + excluded ||
        Number(s.published_products) > Number(s.published_rates) ||
        Number(s.published_providers) > Number(s.published_products)) return result;
    sourceRates += Number(s.source_rates);
    publishedRates += Number(s.published_rates);
    excludedRates += excluded;
  }
  if (Object.keys(exclusions).length !== Object.keys(combined).length ||
      Object.entries(exclusions).some(([reason, value]) => !count(value) || combined[reason] !== value) ||
      a.source_rates !== sourceRates || a.published_rates !== publishedRates || a.excluded_rates !== excludedRates ||
      a.source_products !== Number(a.published_products) + Number(a.products_without_published_rates) ||
      Number(a.providers_with_published_rates) > Number(a.providers_with_products)) return result;
  const rows = Object.values(snapshot.core?.sections ?? {}).flatMap((s) => s.rates);
  const impacts = snapshot.quarantine?.countImpacts;
  if (publishedRates !== rows.length + (impacts?.rates ?? 0) ||
      a.published_products !== new Set(rows.map((r) => r.product_key).filter(Boolean)).size + (impacts?.products ?? 0) ||
      a.providers_with_published_rates !== new Set(rows.map((r) => r.provider).filter(Boolean)).size + (impacts?.providers ?? 0)) return result;
  return { present: true, valid: true, excludedRates, productsWithoutRates: Number(a.products_without_published_rates),
    sourceProducts: Number(a.source_products), sourceRates, publishedRates,
    publishedProducts: Number(a.published_products), providersWithRates: Number(a.providers_with_published_rates) };
}
