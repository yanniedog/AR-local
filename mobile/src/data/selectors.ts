import { SECTIONS } from '../constants';
import type { ProductDetail, RateRow, SectionKey } from '../types';
import {
  detailSearchIndex,
  rowMatchesSearchQuery,
  type SearchIndexPayload,
} from './detailSearch';
import { productHasAllEligibilityCriteria } from './eligibility';
import { productHasAllFeatures } from './features';
import {
  effectiveFraction,
  isBroadlyAvailable,
  sortByDisplayLabel,
  toFraction,
  visibleAccountRows,
} from './format';
import { rateQualifier } from '../lib/rateQualifier';

export type SortKey = 'rate' | 'comparison' | 'bank';

export function normalizeSortKey(value?: string): SortKey {
  return value === 'comparison' || value === 'bank' ? value : 'rate';
}

export interface Filters {
  query: string;
  providers: string[];
  rateTypes: string[];
  lvrTiers: string[];
  repaymentTypes: string[];
  /** Owner-occupier vs investment (CDR loan_purpose codes). */
  loanPurposes: string[];
  depositKinds: string[];
  interestPayments: string[];
  /** CDR featureType codes from details.features (AND when multiple selected). */
  accountFeatures: string[];
  /** CDR eligibilityType codes from details.eligibility (AND when multiple selected). */
  eligibilityCriteria: string[];
  includeNonStandard: boolean;
}

export const EMPTY_FILTERS: Filters = {
  query: '',
  providers: [],
  rateTypes: [],
  lvrTiers: [],
  repaymentTypes: [],
  loanPurposes: [],
  depositKinds: [],
  interestPayments: [],
  accountFeatures: [],
  eligibilityCriteria: [],
  includeNonStandard: false,
};

export function activeFilterCount(f: Filters): number {
  return (
    f.providers.length +
    f.rateTypes.length +
    f.lvrTiers.length +
    f.repaymentTypes.length +
    f.loanPurposes.length +
    f.depositKinds.length +
    f.interestPayments.length +
    f.accountFeatures.length +
    f.eligibilityCriteria.length
  );
}

/** How savings & term-deposit lists are ranked. `base` = the unconditional
 *  ongoing rate a typical customer keeps (a bonus/intro row ranks on the base
 *  rate it reverts to), so conditional promo rates never top the list; `max` =
 *  the headline/maximum achievable rate. Mortgages are unaffected — they carry
 *  no bonus/intro concept (rateQualifier returns 'none'). */
export type RankMetric = 'base' | 'max';

/** The fraction a row should be ranked/compared by, honouring the deposit rank
 *  metric. For `base` (default), a bonus/intro deposit row ranks on the base
 *  ongoing rate it reverts to (`null` when the bank publishes none, so it can't
 *  masquerade as a broadly-earned rate); everything else uses the effective
 *  (comparison-or-headline) rate. This is the single ranking metric every
 *  best/sort/compare surface shares. */
export function rankFraction(
  row: RateRow,
  section: SectionKey,
  metric: RankMetric = 'base',
): number | null {
  if (metric === 'base') {
    const q = rateQualifier(row, section);
    if (q.kind === 'bonus' || q.kind === 'intro') return toFraction(row.ongoing_rate);
  }
  return effectiveFraction(row);
}

/** The "best" rate in a list, honouring lower-is-better for loans. */
export function bestRow(
  rows: RateRow[],
  section: SectionKey,
  includeNonStandard = false,
  metric: RankMetric = 'base',
): RateRow | null {
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;
  let best: RateRow | null = null;
  let bestVal: number | null = null;
  for (const row of visibleAccountRows(rows, includeNonStandard)) {
    const v = rankFraction(row, section, metric);
    if (v === null) continue;
    if (bestVal === null || (lowerIsBetter ? v < bestVal : v > bestVal)) {
      bestVal = v;
      best = row;
    }
  }
  return best;
}

export function sortRows(
  rows: RateRow[],
  sortKey: SortKey,
  section: SectionKey,
  metric: RankMetric = 'base',
): RateRow[] {
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;
  const copy = rows.slice();
  copy.sort((a, b) => {
    if (sortKey === 'bank') {
      return a.provider.localeCompare(b.provider) || a.product_name.localeCompare(b.product_name);
    }
    // Default ("rate") ranks by the deposit rank metric — base ongoing rate by
    // default, so conditional bonus/intro rates don't top the list; otherwise the
    // effective comparison/headline rate. The explicit "comparison" key stays
    // comparison-rate for backward-compatible loan deep links.
    const va = sortKey === 'comparison' ? toFraction(a.comparison_rate ?? a.rate) : rankFraction(a, section, metric);
    const vb = sortKey === 'comparison' ? toFraction(b.comparison_rate ?? b.rate) : rankFraction(b, section, metric);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    // "Best first": ascending for loans, descending for deposits.
    return lowerIsBetter ? va - vb : vb - va;
  });
  return copy;
}

function inList(value: string | undefined, list: string[] | undefined): boolean {
  // Persisted filter snapshots predating a dimension restore without it.
  return !list || list.length === 0 || (value !== undefined && list.includes(value));
}

export function filterRows(
  rows: RateRow[],
  filters: Filters,
  detailsProducts?: Record<string, ProductDetail> | null,
  searchIndex?: SearchIndexPayload | null,
): RateRow[] {
  const runtimeDetailIndex = searchIndex ? null : detailSearchIndex(detailsProducts);
  return rows.filter((row) => {
    if (!row) return false;
    if (!filters.includeNonStandard && !isBroadlyAvailable(row)) return false;
    if (
      !rowMatchesSearchQuery(
        row,
        filters.query,
        searchIndex,
        runtimeDetailIndex?.get(row.product_key),
      )
    ) {
      return false;
    }
    if (!inList(row.provider, filters.providers)) return false;
    if (!inList(row.rate_type, filters.rateTypes)) return false;
    if (!inList(row.lvr_tier, filters.lvrTiers)) return false;
    if (!inList(row.ribbon_repayment_type ?? row.repayment_type, filters.repaymentTypes)) return false;
    if (!inList(row.loan_purpose ?? row.security_purpose, filters.loanPurposes)) return false;
    if (!inList(row.ribbon_deposit_kind, filters.depositKinds)) return false;
    if (!inList(row.interest_payment, filters.interestPayments)) return false;
    if (
      filters.accountFeatures.length > 0 &&
      !productHasAllFeatures(row.product_key, filters.accountFeatures, detailsProducts)
    ) {
      return false;
    }
    if (
      filters.eligibilityCriteria.length > 0 &&
      !productHasAllEligibilityCriteria(row.product_key, filters.eligibilityCriteria, detailsProducts)
    ) {
      return false;
    }
    return true;
  });
}

export function queryAndSort(
  rows: RateRow[],
  filters: Filters,
  sortKey: SortKey,
  section: SectionKey,
  detailsProducts?: Record<string, ProductDetail> | null,
  searchIndex?: SearchIndexPayload | null,
  metric: RankMetric = 'base',
): RateRow[] {
  return sortRows(filterRows(rows, filters, detailsProducts, searchIndex), sortKey, section, metric);
}

/** Distinct non-empty values for a field, sorted by frequency then label. */
export function distinctValues(rows: RateRow[], field: keyof RateRow): string[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const raw = row[field];
    if (raw === undefined || raw === null || raw === '') continue;
    const key = String(raw);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([k]) => k);
}

/** Distinct provider names for filter UI, sorted A-Z (case-insensitive). */
export function distinctProviders(rows: RateRow[]): string[] {
  const names = new Set<string>();
  for (const row of rows) {
    const prov = row.provider;
    if (prov === undefined || prov === null || prov === '') continue;
    names.add(prov);
  }
  return sortByDisplayLabel(Array.from(names), (name) => name);
}

export interface ProviderGroup {
  provider: string;
  rows: RateRow[];
  bestBySection: Partial<Record<SectionKey, RateRow>>;
}

/** Group every row across all sections by provider (for the Banks screen). */
export function groupByProvider(
  sections: Record<SectionKey, { rates: RateRow[] }>,
): ProviderGroup[] {
  // Bucket rows per provider AND per section in a single pass. The previous
  // implementation re-scanned every section's full row array (Array.includes)
  // for every provider, which is O(providers × rows) — the Banks A–Z screen's
  // main lag source. This is O(rows).
  interface Acc extends ProviderGroup {
    bySection: Partial<Record<SectionKey, RateRow[]>>;
  }
  const map = new Map<string, Acc>();
  const keys = Object.keys(sections) as SectionKey[];
  for (const section of keys) {
    for (const row of sections[section].rates) {
      let group = map.get(row.provider);
      if (!group) {
        group = { provider: row.provider, rows: [], bestBySection: {}, bySection: {} };
        map.set(row.provider, group);
      }
      group.rows.push(row);
      (group.bySection[section] ??= []).push(row);
    }
  }
  const out: ProviderGroup[] = [];
  for (const { bySection, ...group } of map.values()) {
    for (const section of keys) {
      const inSection = bySection[section];
      if (!inSection?.length) continue;
      const best = bestRow(inSection, section);
      if (best) group.bestBySection[section] = best;
    }
    out.push(group);
  }
  return out.sort((a, b) => a.provider.localeCompare(b.provider));
}

/** Find a single rate row by product_key across all sections. */
export function findByKey(
  sections: Record<SectionKey, { rates: RateRow[] }>,
  productKey: string,
): { row: RateRow; section: SectionKey; siblings: RateRow[] } | null {
  for (const section of Object.keys(sections) as SectionKey[]) {
    const matches = sections[section].rates.filter((r) => r.product_key === productKey);
    if (matches.length) {
      return { row: matches[0], section, siblings: matches };
    }
  }
  return null;
}
