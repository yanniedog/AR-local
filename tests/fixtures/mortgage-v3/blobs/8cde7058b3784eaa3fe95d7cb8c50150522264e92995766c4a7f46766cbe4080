import { Decimal, decimalZero } from './decimal';
import { LOAN_COMPONENTS, type LoanComponent, type LoanComponentValues } from './loanTypes';
import type { Rounding } from './types';

export type Components = Record<LoanComponent, Decimal>;
export function nonNegativeComponent(value: string): Decimal {
  const parsed = Decimal.parse(value);
  if (parsed.compare(decimalZero()) < 0 || parsed.compare(parsed.rounded(12, 'toward_zero')) !== 0) throw new Error('loan_component_precision_invalid');
  return parsed;
}
export function components(values?: LoanComponentValues): Components {
  return Object.fromEntries(LOAN_COMPONENTS.map(k => [k, values ? Decimal.parse(values[k]) : decimalZero()])) as Components;
}
export function total(c: Components): Decimal { return LOAN_COMPONENTS.reduce((sum, k) => sum.add(c[k]), decimalZero()); }
export function values(c: Components): LoanComponentValues { return Object.fromEntries(LOAN_COMPONENTS.map(k => [k, c[k].fixed(k === 'accruedInterest' ? 12 : 2)])) as LoanComponentValues; }
export function assertTotal(c: Components, expected: Decimal) {
  if (total(c).compare(expected) !== 0 || LOAN_COMPONENTS.some(k => c[k].compare(decimalZero()) < 0)) throw new Error('loan_component_conservation_failed');
}
/** A declared settlement rounds unposted interest once, before allocating the payment. */
export function settleAccrued(c: Components, rounding: Rounding): Decimal {
  const previous = c.accruedInterest; c.accruedInterest = previous.rounded(2, rounding);
  return c.accruedInterest.sub(previous);
}
export function allocate(c: Components, amount: Decimal, priority: LoanComponent[]): Components {
  if (amount.compare(total(c)) > 0) throw new Error('loan_overpayment_rejected');
  const before = total(c), result = components(); let remaining = amount;
  for (const key of priority) {
    const take = c[key].compare(remaining) < 0 ? c[key] : remaining;
    c[key] = c[key].sub(take); result[key] = take; remaining = remaining.sub(take);
  }
  assertTotal(c, before.sub(amount)); return result;
}
