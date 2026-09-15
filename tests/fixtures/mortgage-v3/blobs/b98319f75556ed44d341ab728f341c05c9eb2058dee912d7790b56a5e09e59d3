import { Decimal, decimalZero } from './decimal';
import type { SavingsRateComponent, SavingsTier } from './savingsTypes';

/** Shared allocation primitive; the contract validator owns tier order and coverage checks. */
export function allocateSavingsTiers(balance: Decimal, component: SavingsRateComponent): { tier: SavingsTier; basis: Decimal }[] {
  const portions: { tier: SavingsTier; basis: Decimal }[] = [];
  let lower = decimalZero();
  for (const tier of component.tiers) {
    const upper = tier.upperInclusive === null ? null : Decimal.parse(tier.upperInclusive);
    const fits = upper === null || balance.compare(upper) <= 0;
    let basis = balance;
    if (component.allocation === 'marginal') {
      basis = (upper !== null && balance.compare(upper) > 0 ? upper : balance).sub(lower);
      if (basis.compare(decimalZero()) < 0) basis = decimalZero();
    } else if (!fits) { lower = upper!; continue; }
    portions.push({ tier, basis });
    if (component.allocation === 'whole_balance' || fits) break;
    lower = upper!;
  }
  return portions;
}
