import { dayNumber } from './calendar';
import { Decimal } from './decimal';
import { feeOccurrences } from './feeSchedule';
import { nonNegative, rate } from './validation';
import type { FeeDefinition } from './feeTypes';
import type { LedgerContract, LedgerScenario, Rule } from './types';
import { EVALUATOR_VERSION, FIXED_MATURITY_EVALUATOR_VERSION, PORTFOLIO_EVALUATOR_VERSION } from './types';
import type { AccountAuthority } from './accountAuthority';

const id = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9_.:-]{1,180}$/.test(v);
function validFact(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const f = value as Record<string, unknown>;
  if (f.type === 'boolean') return typeof f.value === 'boolean';
  if (f.type === 'text') return typeof f.value === 'string' && f.value.length <= 16384;
  if (f.type === 'date') { if (typeof f.value !== 'string') return false; dayNumber(f.value); return true; }
  if (f.type === 'decimal') { if (typeof f.value !== 'string' || typeof f.unit !== 'string' || !f.unit || f.unit.length > 100) return false; Decimal.parse(f.value); return true; }
  return false;
}
function priceAndDiscounts(fee: FeeDefinition, account: string, refs: (ids: string[]) => void, ruleRefs: (r: Rule) => void) {
  const p = fee.price;
  if (p.type === 'fixed') nonNegative(p.value);
  else if (p.type === 'percentage') {
    if (rate(p.fraction).compare(Decimal.parse('0')) < 0 || !['half_up', 'half_even', 'toward_zero'].includes(p.rounding)) throw new Error('fee_percentage_invalid');
    if (p.minimum !== undefined) nonNegative(p.minimum); if (p.maximum !== undefined) nonNegative(p.maximum);
    if (p.minimum !== undefined && p.maximum !== undefined && nonNegative(p.minimum).compare(nonNegative(p.maximum)) > 0) throw new Error('fee_cap_range_invalid');
    const b = p.basis;
    if (b.accountId !== account) throw new Error('fee_basis_account_mismatch');
    if (b.type === 'balance') { if (!['day_open', 'before_fee'].includes(b.point)) throw new Error('fee_balance_point_invalid'); }
    else if (b.type === 'fact') { if (!id(b.name) || b.unit !== 'AUD' || dayNumber(b.toExclusive) <= dayNumber(b.from)) throw new Error('fee_fact_scope_invalid'); }
    else throw new Error('fee_basis_unsupported');
  } else if (p.type === 'indexed') {
    if (!id(p.indexId) || !Array.isArray(p.observations) || p.observations.length > 1000) throw new Error('fee_index_invalid');
    let until = '';
    for (const o of p.observations) {
      if (dayNumber(o.toExclusive) <= dayNumber(o.from) || o.from < until) throw new Error('fee_index_overlap');
      until = o.toExclusive; nonNegative(o.value); refs(o.evidenceIds);
    }
  } else if (p.type !== 'unknown' || typeof p.reason !== 'string' || !p.reason || p.reason.length > 500) throw new Error('fee_price_invalid');
  if (fee.applicability !== null) ruleRefs(fee.applicability); if (fee.waiver !== null) ruleRefs(fee.waiver);
  if (!['half_up', 'half_even', 'toward_zero', 'unknown'].includes(fee.discountRounding)) throw new Error('fee_discount_rounding_invalid');
  if (!Array.isArray(fee.discounts) || fee.discounts.length > 30 || !['exclusive', 'first_match', 'additive', 'unknown'].includes(fee.discountPrecedence)) throw new Error('fee_discounts_invalid');
  const seen = new Set<string>();
  for (const d of fee.discounts) {
    if (!id(d.id) || seen.has(d.id) || !['fixed', 'fraction'].includes(d.type)) throw new Error('fee_discount_identity_invalid');
    seen.add(d.id); ruleRefs(d.rule);
    if (d.type === 'fixed') nonNegative(d.value); else if (rate(d.value).compare(Decimal.parse('0')) < 0) throw new Error('fee_discount_fraction_invalid');
  }
}

export function validateFees(c: LedgerContract, s: LedgerScenario, refs: (ids: string[]) => void, ruleRefs: (r: Rule) => void, authority?: AccountAuthority): string[] {
  const f = c.feeSchedule;
  if (!f) return ['fee_inventory_not_proven'];
  if (c.tdLifecycle && !authority?.tdExternalFees && !(c.tdLifecycle.mode === 'fixed_maturity' && f.fees.length === 0 && f.inventory.every(i => i.state === 'none_applicable'))) throw new Error('general_fees_with_td_unsupported');
  if (c.tdLifecycle && f.fees.some(fee => fee.debit.type !== 'external_account')) throw new Error('td_general_principal_fee_policy_unsupported');
  if (f.schemaVersion !== 1 || !id(f.accountId) || s.accountId !== f.accountId || dayNumber(f.toExclusive) <= dayNumber(f.from) || dayNumber(f.toExclusive) - dayNumber(f.from) > 18300) throw new Error('fee_scope_invalid');
  if (s.feeFacts !== undefined && (!Array.isArray(s.feeFacts) || s.feeFacts.length > 512)) throw new Error('fee_fact_limit');
  for (const fact of s.feeFacts ?? []) if (!fact || !id(fact.name) || !id(fact.accountId) || dayNumber(fact.toExclusive) <= dayNumber(fact.from) || !validFact(fact.value)) throw new Error('fee_fact_scope_invalid');
  if (s.events.some(e => e.type === 'fee')) throw new Error('scenario_fee_override_rejected');
  refs(f.evidenceIds);
  const issues: string[] = [];
  if (f.from > s.startDate || f.toExclusive < s.endDateExclusive) issues.push('fee_schedule_horizon_uncovered');
  if (!['reviewed_complete', 'unknown'].includes(f.inventoryCoverage) || !['none_confirmed', 'listed', 'unknown'].includes(f.deferredObligations) ||
      !['before_scenario_events', 'after_scenario_events', 'unknown'].includes(f.ordering)) throw new Error('fee_coverage_invalid');
  if (f.inventoryCoverage !== 'reviewed_complete') issues.push('fee_inventory_not_proven');
  if (f.deferredObligations === 'unknown') issues.push('fee_deferred_obligations_unknown');
  if (f.ordering === 'unknown') issues.push('fee_ordering_unknown');
  if (!Array.isArray(f.fees) || f.fees.length > 128 || !Array.isArray(f.inventory) || !f.inventory.length || f.inventory.length > 128) throw new Error('fee_inventory_invalid');
  const fees = new Map<string, FeeDefinition>(), charges = new Set<string>(), orders = new Set<number>();
  for (const fee of f.fees) {
    if (!id(fee.id) || !id(fee.chargeIdentity) || fees.has(fee.id) || charges.has(fee.chargeIdentity) || !Number.isSafeInteger(fee.order) || fee.order < 0 || orders.has(fee.order)) throw new Error('fee_identity_order_collision');
    fees.set(fee.id, fee); charges.add(fee.chargeIdentity); orders.add(fee.order); refs(fee.evidenceIds);
    if (fee.scope.type === 'account') { if (fee.scope.accountId !== f.accountId) throw new Error('fee_account_mismatch'); }
    else if (fee.scope.type === 'package') {
      const p = fee.scope;
      if (!id(p.packageInstanceId) || !Array.isArray(p.memberAccountIds) || !p.memberAccountIds.length || p.memberAccountIds.length > 128 ||
          p.memberAccountIds.some(a => !id(a)) || new Set(p.memberAccountIds).size !== p.memberAccountIds.length || !p.memberAccountIds.includes(f.accountId) || !p.memberAccountIds.includes(p.debtorAccountId)) throw new Error('fee_package_members_invalid');
      if (!authority?.packageInstances.has(p.packageInstanceId)) issues.push('package_portfolio_coverage_unsupported');
    } else throw new Error('fee_scope_unsupported');
    if (!['product_balance', 'external_account', 'unknown'].includes(fee.debit.type) ||
        (fee.debit.type === 'external_account' && (!id(fee.debit.accountId) || fee.debit.accountId === f.accountId))) throw new Error('fee_debit_account_invalid');
    const t = fee.timing;
    if (t.type === 'dated') {
      if (!Array.isArray(t.occurrences) || t.occurrences.length > 1000 || dayNumber(t.toExclusive) <= dayNumber(t.from) || !['reviewed_complete', 'unknown'].includes(t.triggerCoverage)) throw new Error('fee_occurrence_limit');
      if (t.from > f.from || t.toExclusive < f.toExclusive || t.triggerCoverage !== 'reviewed_complete') issues.push(`fee_trigger_coverage_unknown:${fee.id}`);
      const triggers = new Set<string>();
      for (const o of t.occurrences) {
        if (!id(o.triggerId) || triggers.has(o.triggerId) || dayNumber(o.dueDate) < dayNumber(o.incurredDate) || o.incurredDate < t.from || o.incurredDate >= t.toExclusive) throw new Error('fee_trigger_invalid');
        triggers.add(o.triggerId);
      }
    } else if (t.type === 'recurring') {
      if (!['days', 'months'].includes(t.unit) || !Number.isInteger(t.step) || t.step < 1 || t.step > 365 ||
          dayNumber(t.toExclusive) <= dayNumber(t.from) || dayNumber(t.toExclusive) - dayNumber(t.from) > 18300 || dayNumber(t.anchor) > dayNumber(t.toExclusive) || dayNumber(t.from) - dayNumber(t.anchor) > 366 ||
          !['clamp', 'preserve_month_end'].includes(t.monthConvention) || !['none', 'unknown'].includes(t.calendarAdjustment) || !['same_day', 'unknown'].includes(t.settlement)) throw new Error('fee_cadence_invalid');
      if (t.from > f.from || t.toExclusive < f.toExclusive) issues.push(`fee_recurrence_coverage_unknown:${fee.id}`);
      if (t.calendarAdjustment === 'unknown' || t.settlement === 'unknown') issues.push(`fee_timing_unknown:${fee.id}`);
    } else throw new Error('fee_timing_unsupported');
    const pricingAccount = fee.scope.type === 'package' ? fee.scope.debtorAccountId : f.accountId;
    priceAndDiscounts(fee, pricingAccount, refs, ruleRefs);
    if (fee.ruleAssessments !== undefined) {
      if (!Array.isArray(fee.ruleAssessments) || fee.ruleAssessments.length > 1000) throw new Error('fee_assessment_limit');
      const dates = new Set<string>();
      for (const a of fee.ruleAssessments) {
        dayNumber(a.dueDate);
        const key = `${a.dueDate}:${a.triggerId ?? ''}`;
        if ((a.triggerId !== undefined && (![EVALUATOR_VERSION, FIXED_MATURITY_EVALUATOR_VERSION, PORTFOLIO_EVALUATOR_VERSION].includes(c.evaluatorVersion as typeof EVALUATOR_VERSION) || !id(a.triggerId))) || dates.has(key) || a.accountId !== pricingAccount || dayNumber(a.toExclusive) <= dayNumber(a.from) || !Array.isArray(a.factNames) || !a.factNames.length || a.factNames.length > 128 || a.factNames.some(n => !id(n)) || new Set(a.factNames).size !== a.factNames.length) throw new Error('fee_assessment_scope_invalid');
        dates.add(key); refs(a.evidenceIds);
      }
    }
  }
  const categories = new Set<string>(), covered = new Set<string>();
  for (const item of f.inventory) {
    if (!id(item.categoryId) || categories.has(item.categoryId) || !['scheduled', 'none_applicable', 'unknown', 'lifecycle_owned'].includes(item.state) || !Array.isArray(item.feeIds) || item.feeIds.length > 128) throw new Error('fee_category_invalid');
    if (item.state === 'lifecycle_owned' && (![EVALUATOR_VERSION, FIXED_MATURITY_EVALUATOR_VERSION, PORTFOLIO_EVALUATOR_VERSION].includes(c.evaluatorVersion as typeof EVALUATOR_VERSION) || !authority?.tdExternalFees || item.lifecycleOccurrenceId !== 'td:break-fee')) throw new Error('fee_lifecycle_owner_unproven');
    if (item.state !== 'lifecycle_owned' && item.lifecycleOccurrenceId !== undefined) throw new Error('fee_lifecycle_scope_invalid');
    categories.add(item.categoryId); refs(item.evidenceIds);
    if (item.state === 'unknown') issues.push(`fee_category_unknown:${item.categoryId}`);
    if ((item.state === 'scheduled') !== (item.feeIds.length > 0)) throw new Error('fee_category_schedule_mismatch');
    for (const feeId of item.feeIds) { if (covered.has(feeId) || fees.get(feeId)?.categoryId !== item.categoryId) throw new Error('fee_inventory_mapping_invalid'); covered.add(feeId); }
  }
  if (covered.size !== fees.size) throw new Error('fee_inventory_incomplete');
  const occurrences = feeOccurrences(f), seen = new Set<string>();
  for (const o of occurrences) {
    if (seen.has(o.id)) throw new Error('fee_occurrence_collision'); seen.add(o.id);
    if (o.incurredDate >= s.startDate && o.incurredDate < s.endDateExclusive && o.dueDate >= s.endDateExclusive) issues.push(`fee_payable_after_horizon:${o.id}`);
  }
  for (const fee of f.fees) {
    for (const a of fee.ruleAssessments ?? []) {
      if (a.triggerId !== undefined && !occurrences.some(o => o.fee === fee && o.dueDate === a.dueDate && o.triggerId === a.triggerId)) throw new Error('fee_assessment_trigger_missing');
      if (a.triggerId !== undefined && fee.ruleAssessments!.some(b => b.dueDate === a.dueDate && b.triggerId === undefined)) throw new Error('fee_assessment_scope_ambiguous');
    }
    if (!fee.applicability && !fee.waiver && !fee.discounts.length) continue;
    const dueDates = new Set<string>();
    for (const occurrence of occurrences.filter(o => o.fee === fee)) {
      if (dueDates.has(occurrence.dueDate) && (![EVALUATOR_VERSION, FIXED_MATURITY_EVALUATOR_VERSION, PORTFOLIO_EVALUATOR_VERSION].includes(c.evaluatorVersion as typeof EVALUATOR_VERSION) || !fee.ruleAssessments?.length || fee.ruleAssessments.some(a => a.dueDate === occurrence.dueDate && a.triggerId === undefined))) throw new Error('fee_same_day_conditional_triggers_unsupported');
      dueDates.add(occurrence.dueDate);
    }
  }
  if (c.savingsSchedule && s.savingsAssessments?.some(a => a.activity && !authority?.savingsAssessments?.has(a.id))) issues.push('fee_activity_reconciliation_unsupported');
  return issues;
}
