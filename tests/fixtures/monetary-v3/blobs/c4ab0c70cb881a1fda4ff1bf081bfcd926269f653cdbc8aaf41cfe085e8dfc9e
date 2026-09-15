import { Decimal, decimalZero } from './decimal';
import { evaluateEligibility } from './eligibility';
import type { FeeDefinition } from './feeTypes';
import type { Facts, LedgerScenario, RuleTrace } from './types';
import { nonNegative } from './validation';

export interface FeePriceResult { amount: Decimal | null; reason?: string; evidenceIds?: string[]; ruleTraces: RuleTrace[] }
export function priceFee(fee: FeeDefinition, date: string, scenario: LedgerScenario, dayOpen: Decimal, beforeFee: Decimal, balanceTainted: boolean, triggerId?: string): FeePriceResult {
  const ruleTraces: RuleTrace[] = [];
  const unknown = (reason: string): FeePriceResult => ({ amount: null, reason, ruleTraces });
  const assessment = fee.ruleAssessments?.find(a => a.dueDate === date && (a.triggerId === undefined || a.triggerId === triggerId));
  const facts: Facts = Object.create(null);
  for (const name of assessment?.factNames ?? []) {
    const matches = scenario.feeFacts?.filter(f => f.name === name && f.accountId === assessment!.accountId && f.from === assessment!.from && f.toExclusive === assessment!.toExclusive) ?? [];
    if (matches.length === 1) facts[name] = matches[0].value;
  }
  const status = (rule: NonNullable<FeeDefinition['waiver']>) => { const result = evaluateEligibility(rule, facts); result.trace.evidenceIds = [...new Set([...result.trace.evidenceIds, ...(assessment?.evidenceIds ?? [])])]; ruleTraces.push(result.trace); return result.status; };
  if (fee.applicability) {
    const applicable = status(fee.applicability);
    if (applicable === 'does_not_meet') return { amount: decimalZero(), reason: 'Not applicable by reviewed criterion.', ruleTraces };
    if (applicable !== 'meets') return unknown('fee_applicability_unknown');
  }
  if (fee.waiver) {
    const waived = status(fee.waiver);
    if (waived === 'meets') return { amount: decimalZero(), reason: 'Waived by reviewed criterion.', ruleTraces };
    if (waived !== 'does_not_meet') return unknown('fee_waiver_unknown');
  }
  let amount: Decimal, evidenceIds: string[] | undefined;
  const p = fee.price;
  if (p.type === 'unknown') return unknown(`fee_price_unknown:${p.reason}`);
  if (p.type === 'fixed') amount = nonNegative(p.value);
  else if (p.type === 'indexed') {
    const observation = p.observations.find(o => o.from <= date && date < o.toExclusive);
    if (!observation) return unknown('fee_index_observation_missing');
    amount = nonNegative(observation.value); evidenceIds = observation.evidenceIds;
  } else {
    let basis: Decimal;
    if (p.basis.type === 'balance') {
      if (balanceTainted) return unknown('fee_balance_basis_tainted');
      basis = p.basis.point === 'day_open' ? dayOpen : beforeFee;
    } else {
      const b = p.basis;
      const matches = scenario.feeFacts?.filter(f => f.accountId === b.accountId && f.name === b.name && f.from === b.from && f.toExclusive === b.toExclusive) ?? [];
      if (date < b.from || date >= b.toExclusive || matches.length !== 1 || matches[0].value.type !== 'decimal' || matches[0].value.unit !== b.unit) return unknown('fee_fact_basis_unknown');
      try { basis = nonNegative(matches[0].value.value); } catch { return unknown('fee_fact_basis_invalid'); }
    }
    amount = basis.mul(Decimal.parse(p.fraction));
    if (p.minimum !== undefined && amount.compare(nonNegative(p.minimum)) < 0) amount = nonNegative(p.minimum);
    if (p.maximum !== undefined && amount.compare(nonNegative(p.maximum)) > 0) amount = nonNegative(p.maximum);
    amount = amount.rounded(2, p.rounding);
  }
  if (!fee.discounts.length || amount.compare(decimalZero()) === 0) return { amount, evidenceIds, ruleTraces };
  if (fee.discountPrecedence === 'unknown') return unknown('fee_discount_precedence_unknown');
  const applicable: FeeDefinition['discounts'] = [];
  for (const discount of fee.discounts) {
    const applies = status(discount.rule);
    if (applies === 'needs_information') return unknown('fee_discount_condition_unknown');
    if (applies === 'meets') { applicable.push(discount); if (fee.discountPrecedence === 'first_match') break; }
  }
  if (fee.discountPrecedence === 'exclusive' && applicable.length > 1) return unknown('fee_discount_conflict');
  if (!applicable.length) return { amount, evidenceIds, ruleTraces };
  let reduction = decimalZero();
  for (const d of applicable) reduction = reduction.add(d.type === 'fixed' ? nonNegative(d.value) : amount.mul(Decimal.parse(d.value)));
  const discounted = amount.sub(reduction);
  if (discounted.compare(decimalZero()) <= 0) return { amount: decimalZero(), evidenceIds, ruleTraces };
  if (fee.discountRounding === 'unknown') return unknown('fee_discount_rounding_unknown');
  return { amount: discounted.rounded(2, fee.discountRounding), evidenceIds, ruleTraces };
}
