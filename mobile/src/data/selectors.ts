import { SECTIONS } from '../constants';
import type { RateRow, SectionKey } from '../types';
import { isNonStandard, toFraction, visibleAccountRows } from './format';

export type SortKey = 'rate' | 'comparison' | 'bank';

export interface Filters {
  query: string;
  providers: string[];
  rateTypes: string[];
  lvrTiers: string[];
  repaymentTypes: string[];
  depositKinds: string[];
  interestPayments: string[];
  includeNonStandard: boolean;
}

export const EMPTY_FILTERS: Filters = {
  query: '',
  providers: [],
  rateTypes: [],
  lvrTiers: [],
  repaymentTypes: [],
  depositKinds: [],
  interestPayments: [],
  includeNonStandard: false,
};

export function activeFilterCount(f: Filters): number {
  return (
    f.providers.length +
    f.rateTypes.length +
    f.lvrTiers.length +
    f.repaymentTypes.length +
    f.depositKinds.length +
    f.interestPayments.length +
    (f.includeNonStandard ? 1 : 0)
  );
}

/** The "best" rate in a list, honouring lower-is-better for loans. */
export function bestRow(
  rows: RateRow[],
  section: SectionKey,
  includeNonStandard = false,
): RateRow | null {
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;
  let best: RateRow | null = null;
  let bestVal: number | null = null;
  for (const row of visibleAccountRows(rows, includeNonStandard)) {
    const v = toFraction(row.rate);
    if (v === null) continue;
    if (bestVal === null || (lowerIsBetter ? v < bestVal : v > bestVal)) {
      bestVal = v;
      best = row;
    }
  }
  return best;
}

export function sortRows(rows: RateRow[], sortKey: SortKey, section: SectionKey): RateRow[] {
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;
  const copy = rows.slice();
  copy.sort((a, b) => {
    if (sortKey === 'bank') {
      return a.provider.localeCompare(b.provider) || a.product_name.localeCompare(b.product_name);
    }
    const field = sortKey === 'comparison' ? a.comparison_rate ?? a.rate : a.rate;
    const fieldB = sortKey === 'comparison' ? b.comparison_rate ?? b.rate : b.rate;
    const va = toFraction(field);
    const vb = toFraction(fieldB);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    // "Best first": ascending for loans, descending for deposits.
    return lowerIsBetter ? va - vb : vb - va;
  });
  return copy;
}

function matchesQuery(row: RateRow, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  return (
    row.provider.toLowerCase().includes(needle) ||
    row.product_name.toLowerCase().includes(needle)
  );
}

function inList(value: string | undefined, list: string[]): boolean {
  return list.length === 0 || (value !== undefined && list.includes(value));
}

export function filterRows(rows: RateRow[], filters: Filters): RateRow[] {
  return rows.filter((row) => {
    if (!filters.includeNonStandard && isNonStandard(row)) return false;
    if (!matchesQuery(row, filters.query)) return false;
    if (!inList(row.provider, filters.providers)) return false;
    if (!inList(row.rate_type, filters.rateTypes)) return false;
    if (!inList(row.lvr_tier, filters.lvrTiers)) return false;
    if (!inList(row.ribbon_repayment_type ?? row.repayment_type, filters.repaymentTypes)) return false;
    if (!inList(row.ribbon_deposit_kind, filters.depositKinds)) return false;
    if (!inList(row.interest_payment, filters.interestPayments)) return false;
    return true;
  });
}

export function queryAndSort(
  rows: RateRow[],
  filters: Filters,
  sortKey: SortKey,
  section: SectionKey,
): RateRow[] {
  return sortRows(filterRows(rows, filters), sortKey, section);
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

export interface ProviderGroup {
  provider: string;
  rows: RateRow[];
  bestBySection: Partial<Record<SectionKey, RateRow>>;
}

/** Group every row across all sections by provider (for the Banks screen). */
export function groupByProvider(
  sections: Record<SectionKey, { rates: RateRow[] }>,
): ProviderGroup[] {
  const map = new Map<string, ProviderGroup>();
  (Object.keys(sections) as SectionKey[]).forEach((section) => {
    for (const row of sections[section].rates) {
      let group = map.get(row.provider);
      if (!group) {
        group = { provider: row.provider, rows: [], bestBySection: {} };
        map.set(row.provider, group);
      }
      group.rows.push(row);
    }
  });
  (Object.keys(sections) as SectionKey[]).forEach((section) => {
    for (const group of map.values()) {
      const inSection = group.rows.filter((r) => sections[section].rates.includes(r));
      const best = bestRow(inSection, section);
      if (best) group.bestBySection[section] = best;
    }
  });
  return Array.from(map.values()).sort((a, b) => a.provider.localeCompare(b.provider));
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
