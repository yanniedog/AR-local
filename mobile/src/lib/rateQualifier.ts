import { formatRate, isoDurationMonths } from '../data/format';
import type { RateRow, SectionKey } from '../types';

/**
 * Format a published ongoing rate, preserving a legitimate 0% (some bonus/intro
 * accounts pay 0% ongoing). `toFraction` rejects values <= 0 as missing, which
 * would falsely tell the user the bank publishes no base rate. Returns null only
 * when the field is genuinely absent.
 */
function formatOngoingRate(raw: string | number | null | undefined): string | null {
  if (raw === undefined || raw === null || raw === '') return null;
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n) || n < 0) return null;
  return n === 0 ? '0.00%' : formatRate(raw);
}

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
  /**
   * The published ongoing (base) rate the headline reverts to, formatted (e.g.
   * "1.00%"), or null when the bank does not publish a separate base tier.
   */
  ongoingRate: string | null;
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
  ongoingRate: null,
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

  // The Pi joins the product's published unconditional base tier onto bonus/intro
  // rows as `ongoing_rate`; surface it so the disclosure says what the customer
  // actually earns once the bonus/intro ends, not just "may be lower". When the
  // bank publishes no separate base tier we say so rather than guess (the same
  // honesty that motivates the whole module).
  const ongoingRate = formatOngoingRate(row.ongoing_rate);
  const hasOngoing = ongoingRate !== null;
  const ongoingTail = hasOngoing ? ongoingRate : 'an ongoing rate the bank has not published';

  if (kind === 'bonus') {
    // Bonus conditions vary widely and are not provable from the flat row:
    // savings bonuses can hinge on eligibility (new/selected customer, age) or
    // activating a feature — not only a monthly deposit — and term-deposit
    // bonuses can be auto-rollover or eligibility based. Keep the *conditions*
    // wording generic, but name the ongoing rate when the bank publishes it.
    return {
      kind: 'bonus',
      conditional: true,
      introMonths: null,
      ongoingRate: hasOngoing ? ongoingRate : null,
      shortLabel: 'Bonus',
      label: 'Bonus rate',
      note: hasOngoing
        ? `Bonus rate — paid only when the bonus conditions are met; the ongoing rate is ${ongoingRate}.`
        : 'Bonus rate — paid only when the bonus conditions are met; the ongoing rate is lower (the bank does not publish a separate base rate).',
    };
  }
  // intro
  const months = isoDurationMonths(typeof row.term === 'string' ? row.term : undefined);
  return {
    kind: 'intro',
    conditional: true,
    introMonths: months,
    ongoingRate: hasOngoing ? ongoingRate : null,
    shortLabel: months ? `Intro ${months}mo` : 'Intro',
    // Keep the reversion term AND target in the label so the a11y string (which
    // replaces the card's visible descendants) still exposes both to screen readers.
    label: months
      ? `Introductory rate (${months} month${months === 1 ? '' : 's'}${hasOngoing ? `, then ${ongoingRate}` : ''})`
      : `Introductory rate${hasOngoing ? ` (then ${ongoingRate})` : ''}`,
    note: months
      ? `Introductory rate — applies for ${months} month${months === 1 ? '' : 's'}, then reverts to ${ongoingTail}.`
      : `Introductory rate — applies for a limited period, then reverts to ${ongoingTail}.`,
  };
}

/** Conditional caveat for a best-rate claim, or '' when the rate is unconditional. */
export function conditionalNote(row: RateRow | null | undefined, section: SectionKey): string {
  if (!row) return '';
  const q = rateQualifier(row, section);
  return q.conditional ? q.note : '';
}

/**
 * Compact one-sentence ongoing-rate caveat for notification bodies, naming the
 * rate the headline reverts to (and the intro term, when known). '' when the
 * rate is unconditional.
 */
export function ongoingRateCaveat(row: RateRow | null | undefined, section: SectionKey): string {
  if (!row) return '';
  const q = rateQualifier(row, section);
  if (!q.conditional) return '';
  if (q.kind === 'intro') {
    const term = q.introMonths ? ` after ${q.introMonths} month${q.introMonths === 1 ? '' : 's'}` : ' after the intro period';
    return q.ongoingRate
      ? `Reverts to ${q.ongoingRate}${term}.`
      : `Reverts to a lower ongoing rate${term} (not published).`;
  }
  return q.ongoingRate
    ? `Ongoing rate ${q.ongoingRate} when bonus conditions aren't met.`
    : "Ongoing rate is lower when bonus conditions aren't met (not published).";
}
