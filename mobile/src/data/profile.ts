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

/** Seed screen filters from the saved profile; the user can still override per screen. */
export function profileToFilters(p: ProfileFilters, base: Filters): Filters {
  return {
    ...base,
    loanPurposes: [...p.loanPurposes],
    rateTypes: [...p.rateTypes],
    repaymentTypes: [...p.repaymentTypes],
    lvrTiers: [...p.lvrTiers],
    depositKinds: [...p.depositKinds],
    interestPayments: [...p.interestPayments],
  };
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
