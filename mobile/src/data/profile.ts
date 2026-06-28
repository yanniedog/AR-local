import type { Filters } from './selectors';
import type { RateRow, SectionKey } from '../types';

/**
 * Per-section product attributes the user locks in once — e.g. owner-occupied,
 * P&I, variable, LVR 80–90% — applied as default filters across the app so the
 * same choices never have to be re-selected screen by screen.
 */
export interface ProfileFilters {
  loanPurposes: string[];
  rateTypes: string[];
  repaymentTypes: string[];
  lvrTiers: string[];
  depositKinds: string[];
  interestPayments: string[];
}

export const EMPTY_PROFILE: ProfileFilters = {
  loanPurposes: [],
  rateTypes: [],
  repaymentTypes: [],
  lvrTiers: [],
  depositKinds: [],
  interestPayments: [],
};

const stringList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];

export function normalizeProfileFilters(value?: Partial<ProfileFilters> | null): ProfileFilters {
  return {
    loanPurposes: stringList(value?.loanPurposes),
    rateTypes: stringList(value?.rateTypes),
    repaymentTypes: stringList(value?.repaymentTypes),
    lvrTiers: stringList(value?.lvrTiers),
    depositKinds: stringList(value?.depositKinds),
    interestPayments: stringList(value?.interestPayments),
  };
}

export function profileSelectionCount(p: ProfileFilters): number {
  return (
    p.loanPurposes.length +
    p.rateTypes.length +
    p.repaymentTypes.length +
    p.lvrTiers.length +
    p.depositKinds.length +
    p.interestPayments.length
  );
}

/**
 * Seed screen filters from the saved profile — only the dimensions that apply
 * to `section` (a saved Mortgage rate type must not constrain a Savings
 * search); the user can still override per screen.
 */
export function profileToFilters(p: ProfileFilters, section: SectionKey, base: Filters): Filters {
  if (section === 'Mortgage') {
    return {
      ...base,
      loanPurposes: [...p.loanPurposes],
      rateTypes: [...p.rateTypes],
      repaymentTypes: [...p.repaymentTypes],
      lvrTiers: [...p.lvrTiers],
    };
  }
  if (section === 'TD') return { ...base, interestPayments: [...p.interestPayments] };
  return { ...base, depositKinds: [...p.depositKinds] };
}

/**
 * Parse a raw `lvr_tier` value (e.g. "lvr_85-90%", "lvr_=60%", "lvr_unspecified")
 * into a numeric (lo, hi] band, or null when it carries no usable range.
 */
export function parseLvrTier(tier: string): { lo: number; hi: number } | null {
  const v = String(tier || '')
    .toLowerCase()
    .replace(/^lvr_/, '')
    .replace(/%/g, '')
    .trim();
  if (!v || v.includes('unspec') || v.includes('n/a') || v === 'na') return null;
  let m = /^=?(\d+(?:\.\d+)?)$/.exec(v); // "=60" or "60" => ≤60
  if (m) return { lo: 0, hi: Number(m[1]) };
  m = /^(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)$/.exec(v); // "85-90"
  if (m) return { lo: Number(m[1]), hi: Number(m[2]) };
  m = /^>?(\d+(?:\.\d+)?)\+?$/.exec(v); // ">95" or "95+"
  if (m) return { lo: Number(m[1]), hi: Infinity };
  return null;
}

/**
 * Given a computed LVR percentage and the `lvr_tier` values present in the data,
 * pick the band that contains it (smallest matching band; the top band if the LVR
 * exceeds every band). Returns null when no tier carries a usable range.
 */
export function lvrTierForValue(lvr: number, tiers: string[]): string | null {
  if (!Number.isFinite(lvr) || lvr <= 0) return null;
  const ranges = tiers
    .map((tier) => ({ tier, range: parseLvrTier(tier) }))
    .filter((x): x is { tier: string; range: { lo: number; hi: number } } => x.range !== null)
    .sort((a, b) => a.range.hi - b.range.hi || a.range.lo - b.range.lo);
  if (!ranges.length) return null;
  for (const { tier, range } of ranges) {
    if (lvr > range.lo && lvr <= range.hi) return tier;
  }
  return ranges[ranges.length - 1].tier; // above every band → highest available
}

/** Profile dimensions that apply to a section (drives editors and row matching). */
export const PROFILE_GROUPS: {
  section: SectionKey;
  title: string;
  field: keyof RateRow;
  key: keyof ProfileFilters;
}[] = [
  { section: 'Mortgage', title: 'Purpose', field: 'loan_purpose', key: 'loanPurposes' },
  { section: 'Mortgage', title: 'Rate type', field: 'rate_type', key: 'rateTypes' },
  { section: 'Mortgage', title: 'Repayment', field: 'ribbon_repayment_type', key: 'repaymentTypes' },
  { section: 'Mortgage', title: 'LVR tier', field: 'lvr_tier', key: 'lvrTiers' },
  { section: 'Savings', title: 'Account type', field: 'ribbon_deposit_kind', key: 'depositKinds' },
  { section: 'TD', title: 'Interest paid', field: 'interest_payment', key: 'interestPayments' },
];

const matches = (value: string | undefined, list: string[]): boolean =>
  list.length === 0 || (value !== undefined && list.includes(value));

/** Rows matching the profile within one section (empty dimensions match all). */
export function profileFilterRows(rows: RateRow[], p: ProfileFilters, section: SectionKey): RateRow[] {
  if (section === 'Mortgage') {
    if (!p.loanPurposes.length && !p.rateTypes.length && !p.repaymentTypes.length && !p.lvrTiers.length) return rows;
    return rows.filter(
      (r) =>
        matches(r.loan_purpose ?? r.security_purpose, p.loanPurposes) &&
        matches(r.rate_type, p.rateTypes) &&
        matches(r.ribbon_repayment_type ?? r.repayment_type, p.repaymentTypes) &&
        matches(r.lvr_tier, p.lvrTiers),
    );
  }
  if (section === 'TD') {
    if (!p.interestPayments.length) return rows;
    return rows.filter((r) => matches(r.interest_payment, p.interestPayments));
  }
  if (!p.depositKinds.length) return rows;
  return rows.filter((r) => matches(r.ribbon_deposit_kind, p.depositKinds));
}

/** Selections that affect a given section (badge counts, "profile applied" hints). */
export function profileSectionCount(p: ProfileFilters, section: SectionKey): number {
  if (section === 'Mortgage') {
    return p.loanPurposes.length + p.rateTypes.length + p.repaymentTypes.length + p.lvrTiers.length;
  }
  if (section === 'TD') return p.interestPayments.length;
  return p.depositKinds.length;
}
