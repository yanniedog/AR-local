import { isLeapYear } from './calendar';
import { Decimal } from './decimal';
import type { InterestPolicy } from './types';

/** Shared flat/tier arithmetic; rounding stage is selected explicitly by the caller. */
export function dailyInterest(balance: Decimal, annualRate: Decimal, date: string, policy: InterestPolicy): Decimal {
  const divisor = policy.dayCount === 'actual_actual' && isLeapYear(Number(date.slice(0, 4))) ? '366' : '365';
  let dailyRate = annualRate.div(Decimal.parse(divisor));
  if (policy.dailyRateRounding) {
    const rule = policy.dailyRateRounding, scale = Decimal.parse(rule.unit === 'percent' ? '100' : '1');
    dailyRate = dailyRate.mul(scale).rounded(rule.scale, rule.mode).div(scale);
  }
  const exact = balance.mul(dailyRate);
  return policy.dailyAccrualScale === null ? exact : exact.rounded(policy.dailyAccrualScale, policy.accrualRounding);
}
