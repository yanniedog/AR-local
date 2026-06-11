import { SECTIONS } from '../constants';
import { SECTION_KEYS } from '../types';
import type { SectionKey } from '../types';
import type { BankMoveDir } from '../data/bankInsights';

/**
 * Customer-perspective semantics for rate moves.
 *
 * Loans (lowerIsBetter): a rise hurts borrowers → "hike" (red); a fall is a "cut" (green).
 * Deposits (savings/TD): hike/cut is misleading — a rise helps savers → "increase" (green);
 * a fall is a "decrease" (red).
 */
export function isLoanSection(section: SectionKey): boolean {
  return SECTIONS[section].lowerIsBetter;
}

export const LOAN_SECTIONS: readonly SectionKey[] = SECTION_KEYS.filter(isLoanSection);
export const DEPOSIT_SECTIONS: readonly SectionKey[] = SECTION_KEYS.filter(
  (key) => !isLoanSection(key),
);

export type MoveTone = 'success' | 'danger' | 'muted';

/** Good news for the section's customer → success (green); bad news → danger (red). */
export function moveTone(section: SectionKey, bps: number): MoveTone {
  if (bps === 0) return 'muted';
  const goodForCustomer = isLoanSection(section) ? bps < 0 : bps > 0;
  return goodForCustomer ? 'success' : 'danger';
}

/** Past-tense verb for a provider move row ("CBA cut…", "ING increased…"). */
export function moveVerb(section: SectionKey, dir: BankMoveDir): string {
  if (dir === 'mixed') return 'repriced';
  if (isLoanSection(section)) return dir === 'cut' ? 'cut' : 'hiked';
  return dir === 'cut' ? 'decreased' : 'increased';
}
