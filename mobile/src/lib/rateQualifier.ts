import { isoDurationMonths } from '../data/format';
import type { RateRow, SectionKey } from '../types';

/**
 * Conditionality class of a row's headline rate.
 *
 * The headline savings/TD `rate` can be a *conditional* number — a bonus rate
 * that is only paid when monthly account conditions are met, or an introductory
 * rate that reverts after a fixed window. Ranking these next to unconditional
 * base rates without a flag (the old behaviour) overstates the rate a typical
 * customer actually earns, which is the fastest way a rate comparison loses
 * trust. This module classifies the row so every "best rate" claim can disclose
 * the catch.
 */
export type RateConditionality = 'base' | 'bonus' | 'intro' | 'none';

export interface RateQualifier {
  kind: RateConditionality;
  /** True when the headline rate is NOT the unconditional ongoing rate. */
  conditional: boolean;
  /** Length of an introductory window in months, when known. */
  introMonths: number | null;
  /** Compact badge label, e.g. "Bonus" or "Intro 6mo". */
  shortLabel: string;
  /** Full badge / screen-reader label, e.g. "Bonus rate". */
  label: string;
  /** One-line plain-language caveat for the best-rate claim. */
  note: string;
}

// Frozen so the shared no-op result can never be mutated by a caller.
const NONE: RateQualifier = Object.freeze({
  kind: 'none',
  conditional: false,
  introMonths: null,
  shortLabel: '',
  label: '',
  note: '',
});

function classifyKind(row: RateRow, section: SectionKey): RateConditionality {
  // Savings carry it on ribbon_deposit_kind (base | bonus | introductory);
  // term deposits on ribbon_rate_structure (base | bonus). For mortgages that
  // field encodes variable/fixed — a rate TYPE, not conditionality — so there is
  // no bonus/intro concept to surface.
  if (section === 'Mortgage') return 'none';
  const raw = (section === 'Savings' ? row.ribbon_deposit_kind : row.ribbon_rate_structure)
    ?.toLowerCase()
    .trim();
  if (raw === 'bonus') return 'bonus';
  if (raw === 'introductory' || raw === 'intro') return 'intro';
  if (raw === 'base') return 'base';
  // Fall back to the dot-delimited taxonomy path when the flat field is absent
  // (e.g. SAVINGS.SAVINGS_ACCT.BONUS.TIERED).
  const path = (row.taxonomy_path ?? '').toUpperCase();
  if (path.includes('.BONUS.')) return 'bonus';
  // Match both '.INTRO.' and '.INTRODUCTORY.' tokens.
  if (path.includes('.INTRO')) return 'intro';
  if (path.includes('.BASE.')) return 'base';
  return 'none';
}

export function rateQualifier(row: RateRow, section: SectionKey): RateQualifier {
  const kind = classifyKind(row, section);
  if (kind === 'base') return { ...NONE, kind: 'base' };
  if (kind === 'none') return NONE;
  if (kind === 'bonus') {
    // Savings bonuses are the familiar "meet monthly conditions or drop to the
    // base rate" structure. Term-deposit bonuses are not necessarily monthly and
    // may not revert to a base rate (e.g. auto-rollover or eligibility bonuses),
    // so keep the TD wording generic rather than claiming monthly conditions.
    const note =
      section === 'Savings'
        ? 'Bonus rate — paid only when the monthly account conditions are met; the lower base rate applies otherwise.'
        : 'Bonus rate — applies only when specific conditions are met (e.g. auto-rollover or eligibility).';
    return {
      kind: 'bonus',
      conditional: true,
      introMonths: null,
      shortLabel: 'Bonus',
      label: 'Bonus rate',
      note,
    };
  }
  // intro
  const months = isoDurationMonths(typeof row.term === 'string' ? row.term : undefined);
  return {
    kind: 'intro',
    conditional: true,
    introMonths: months,
    shortLabel: months ? `Intro ${months}mo` : 'Intro',
    label: 'Introductory rate',
    note: months
      ? `Introductory rate — applies for ${months} month${months === 1 ? '' : 's'}, then reverts to the ongoing rate.`
      : 'Introductory rate — applies for a limited period, then reverts to the ongoing rate.',
  };
}

/** Conditional caveat for a best-rate claim, or '' when the rate is unconditional. */
export function conditionalNote(row: RateRow | null | undefined, section: SectionKey): string {
  if (!row) return '';
  const q = rateQualifier(row, section);
  return q.conditional ? q.note : '';
}
