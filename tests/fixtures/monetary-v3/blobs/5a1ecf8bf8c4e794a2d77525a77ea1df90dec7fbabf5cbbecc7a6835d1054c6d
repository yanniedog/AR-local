import { dayNumber } from './calendar';
import { decimalZero } from './decimal';
import { feeOccurrences } from './feeSchedule';
import { LOAN_COMPONENTS } from './loanTypes';
import type { LedgerContract, LedgerScenario } from './types';
import { canonical, hashText, nonNegative, rate } from './validation';
import { nonNegativeComponent } from './loanComponents';
import type { AccountAuthority } from './accountAuthority';
import { feeDebitsAccount } from './feeSchedule';

const id = (s: unknown): s is string => typeof s === 'string' && /^[A-Za-z0-9_.:-]{1,180}$/.test(s);
export function validateLoan(c: LedgerContract, s: LedgerScenario, refs: (ids: string[]) => void, assumed?: (code: string, id: string) => void, authority?: AccountAuthority): string[] {
  const l = c.loanContract, input = s.loan;
  if (!l) { if (input) throw new Error('loan_contract_missing'); return []; }
  if (!input || l.schemaVersion !== 1 || !id(l.accountId) || l.accountId !== s.accountId || l.cohortKey !== s.cohortKey ||
      !id(l.offerId) || !id(l.sourceVersion) || input.offerId !== l.offerId || input.sourceVersion !== l.sourceVersion || input.openingSnapshotId !== l.opening.snapshotId ||
      c.direction !== 'liability' || c.savingsSchedule || c.tdLifecycle) throw new Error('loan_scope_mismatch');
  if (s.events.length || s.initialOffset !== '0') throw new Error('loan_generic_events_rejected');
  refs(l.evidenceIds); refs(l.opening.evidenceIds); refs(l.extraPayments.evidenceIds); refs(l.redraw.evidenceIds);
  if (dayNumber(l.from) > dayNumber(s.startDate) || dayNumber(l.toExclusive) < dayNumber(s.endDateExclusive) || l.opening.effectiveDate !== s.startDate || !id(l.opening.snapshotId) ||
      nonNegativeComponent(l.opening.outstanding).compare(nonNegativeComponent(s.openingBalance)) !== 0) throw new Error('loan_opening_scope_mismatch');
  nonNegative(l.opening.redrawAvailable);
  const issues: string[] = [];
  if (!l.opening.components) issues.push('loan_opening_components_unknown');
  else {
    let total = decimalZero();
    for (const component of LOAN_COMPONENTS) total = total.add(component === 'accruedInterest' ? nonNegativeComponent(l.opening.components[component]) : nonNegative(l.opening.components[component]));
    if (total.compare(nonNegativeComponent(l.opening.outstanding)) !== 0) throw new Error('loan_opening_components_mismatch');
  }
  for (const key of ['allocation', 'interestBearing'] as const) {
    const list = l[key];
    if (list === 'unknown') issues.push(`loan_${key}_unknown`);
    else if (!Array.isArray(list) || !list.length || new Set(list).size !== list.length || list.some(k => !LOAN_COMPONENTS.includes(k)) ||
        (key === 'allocation' && list.length !== LOAN_COMPONENTS.length)) throw new Error('loan_component_policy_invalid');
  }
  if (!['before_accrual', 'after_accrual', 'unknown'].includes(l.paymentTiming) || !['reject', 'unknown'].includes(l.overpayment) ||
      !['half_up', 'half_even', 'toward_zero', 'unknown'].includes(l.paymentRounding) || !['reviewed_complete', 'unknown'].includes(l.scheduleCoverage)) throw new Error('loan_payment_policy_invalid');
  if (l.paymentTiming === 'unknown') issues.push('loan_payment_timing_unknown');
  if (l.overpayment === 'unknown') issues.push('loan_overpayment_unknown');
  if (l.paymentRounding === 'unknown') issues.push('loan_payment_rounding_unknown');
  if (!['round_before_each_payment', 'unknown'].includes(l.accruedSettlement) || l.advancesTiming !== 'start_of_day_before_fees' || l.feeBalanceBasis !== 'outstanding_including_unposted' || l.obligationMeasurement !== 'before_payment_phase') throw new Error('loan_settlement_order_unsupported');
  if (l.accruedSettlement === 'unknown') issues.push('loan_accrued_settlement_unknown');
  if (!['restore_components_no_interest_recalculation', 'unknown'].includes(l.reversalPolicy)) throw new Error('loan_reversal_policy_invalid');
  if (l.scheduleCoverage !== 'reviewed_complete') issues.push('loan_obligation_coverage_unknown');
  if (!['cleared', 'projected'].includes(input.mode)) throw new Error('loan_execution_mode_invalid');
  if (input.mode === 'projected') {
    const a = s.executionAssumption;
    if (a && id(a.id) && a.acknowledged === true && a.accountId === l.accountId && a.from === s.startDate && a.toExclusive === s.endDateExclusive &&
        a.executionSha256 === hashText(canonical({ executions: input.executions, advances: l.advances, obligations: l.obligations })) && assumed) assumed('loan_projected_executions_assumption', a.id);
    else if (authority?.projectionAssumptionId && !input.executions.length && !l.advances.some(a => a.status === 'projected') && assumed) assumed('loan_projected_executions_assumption', authority.projectionAssumptionId);
    else issues.push('loan_projected_executions_assumption');
  } else if (s.executionAssumption) throw new Error('loan_execution_assumption_mode_mismatch');
  const inHorizon = (date: string) => { if (dayNumber(date) < dayNumber(s.startDate) || dayNumber(date) >= dayNumber(s.endDateExclusive)) throw new Error('loan_date_outside_horizon'); };
  const identities = new Set<string>();
  const identify = (key: string) => { if (!id(key) || identities.has(key)) throw new Error('loan_identity_duplicate'); identities.add(key); };
  if (!Array.isArray(l.obligations) || l.obligations.length > 10000 || !Array.isArray(l.advances) || l.advances.length > 1000 || !Array.isArray(l.rates) || l.rates.length > 1000 || !Array.isArray(input.executions) || input.executions.length > 10000) throw new Error('loan_event_limit');
  for (const o of l.obligations) {
    identify(o.id); inHorizon(o.dueDate); refs(o.evidenceIds);
    if (o.accountId !== l.accountId) throw new Error('loan_obligation_account_mismatch');
    if (o.amount.type === 'fixed') nonNegative(o.amount.value); else if (o.amount.type !== 'interest_due') throw new Error('loan_obligation_amount_unsupported');
  }
  for (const a of l.advances) { identify(a.id); inHorizon(a.date); nonNegative(a.amount); refs(a.evidenceIds); if (!['cleared', 'projected'].includes(a.status)) throw new Error('loan_advance_status_invalid'); }
  const dates = new Set<string>();
  for (const r of l.rates) { inHorizon(r.date); refs(r.evidenceIds); if (dates.has(r.date)) throw new Error('loan_rate_date_duplicate'); dates.add(r.date); if (r.annualRate !== null) rate(r.annualRate); }
  for (const p of [l.extraPayments, l.redraw]) {
    if (![true, false, 'unknown'].includes(p.allowed) || (p.totalCap !== null && nonNegative(p.totalCap).compare(decimalZero()) < 0)) throw new Error('loan_movement_policy_invalid');
  }
  if (![true, false, 'unknown'].includes(l.extraPayments.increasesRedraw)) throw new Error('loan_redraw_credit_policy_invalid');
  const orders = new Set<string>(), executions = new Map(input.executions.map(e => [e.id, e]));
  const reversed = new Set<string>();
  for (const e of input.executions) {
    identify(e.id); inHorizon(e.date); nonNegative(e.amount); refs(e.evidenceIds);
    const order = `${e.date}:${e.order}`;
    if (e.accountId !== l.accountId || !['cleared', 'projected'].includes(e.status) || !Number.isSafeInteger(e.order) || e.order < 0 || orders.has(order)) throw new Error('loan_execution_scope_invalid');
    orders.add(order);
    if (e.type === 'payment') { if (!l.obligations.some(o => o.id === e.obligationId) || e.reversalOf) throw new Error('loan_obligation_reference_invalid'); }
    else if (e.type === 'reversal') {
      const original = executions.get(e.reversalOf ?? '');
      if (!original || original.type === 'reversal' || original.status !== e.status || original.date > e.date || (original.date === e.date && original.order >= e.order) ||
          original.amount !== e.amount || reversed.has(original.id) || e.obligationId) throw new Error('loan_reversal_invalid');
      reversed.add(original.id);
    } else if (!['extra_payment', 'redraw'].includes(e.type) || e.obligationId || e.reversalOf) throw new Error('loan_execution_type_invalid');
  }
  if (!Array.isArray(l.feeFunding) || l.feeFunding.length > 10000) throw new Error('loan_fee_funding_invalid');
  const fees = c.feeSchedule ? feeOccurrences(c.feeSchedule).filter(o => o.dueDate >= s.startDate && o.dueDate < s.endDateExclusive) : [];
  const funded = new Set<string>();
  for (const f of l.feeFunding) {
    const occurrence = fees.find(o => o.id === f.occurrenceId);
    if (!occurrence || occurrence.fee.debit.type !== 'product_balance' || funded.has(f.occurrenceId) || !['capitalize', 'redraw'].includes(f.method)) throw new Error('loan_fee_funding_invalid');
    funded.add(f.occurrenceId); refs(f.evidenceIds);
  }
  if (fees.some(o => o.fee.scope.type === 'package' && !authority?.packageInstances.has(o.fee.scope.packageInstanceId))) issues.push('loan_package_funding_unsupported');
  if (fees.some(o => o.fee.debit.type === 'product_balance' && feeDebitsAccount(o.fee, l.accountId) && !funded.has(o.id))) throw new Error('loan_fee_funding_missing');
  const fundedRedrawDates = new Set(fees.filter(o => l.feeFunding.some(f => f.occurrenceId === o.id && f.method === 'redraw')).map(o => o.dueDate));
  if (input.executions.some(e => e.type === 'redraw' && fundedRedrawDates.has(e.date))) throw new Error('loan_same_day_fee_and_independent_redraw_unsupported');
  if (l.closure) { inHorizon(l.closure.date); refs(l.closure.evidenceIds); if (typeof l.closure.requireSettled !== 'boolean' || dayNumber(l.closure.date) !== dayNumber(s.endDateExclusive) - 1) throw new Error('loan_closure_scope_invalid'); }
  validateOffset(c, s, refs, issues);
  return issues;
}

function validateOffset(c: LedgerContract, s: LedgerScenario, refs: (ids: string[]) => void, issues: string[]) {
  const l = c.loanContract!, o = l.offset;
  if (!o) { if (c.interest.offset !== 'none') throw new Error('loan_offset_contract_missing'); return; }
  if (c.interest.offset !== 'capped_at_balance' || !['complete', 'unknown'].includes(o.coverage) || dayNumber(o.from) > dayNumber(s.startDate) || dayNumber(o.toExclusive) < dayNumber(s.endDateExclusive)) throw new Error('loan_offset_scope_invalid');
  for (const list of [o.accountIds, o.loanIds]) if (!Array.isArray(list) || !list.length || list.length > 128 || list.some(k => !id(k)) || new Set(list).size !== list.length) throw new Error('loan_offset_inventory_invalid');
  if (!o.loanIds.includes(l.accountId) || o.accountIds.some(a => o.loanIds.includes(a)) || !Array.isArray(o.snapshots) || o.snapshots.length > 10000) throw new Error('loan_offset_inventory_invalid');
  if (o.coverage !== 'complete') issues.push('loan_offset_global_ownership_unverified');
  if (!['complete_step_schedule', 'observations_only'].includes(o.balanceHistory)) throw new Error('loan_offset_balance_history_invalid');
  if (o.balanceHistory !== 'complete_step_schedule') issues.push('loan_offset_balance_history_unverified');
  const keys = new Set<string>();
  for (const p of o.snapshots) {
    const key = `${p.accountId}:${p.date}`;
    if (!o.accountIds.includes(p.accountId) || keys.has(key) || dayNumber(p.date) < dayNumber(o.from) || dayNumber(p.date) >= dayNumber(o.toExclusive) || !Array.isArray(p.allocations) || p.allocations.length !== o.loanIds.length) throw new Error('loan_offset_snapshot_invalid');
    keys.add(key); refs(p.evidenceIds); const loans = new Set<string>(); let allocated = decimalZero();
    for (const a of p.allocations) { if (!o.loanIds.includes(a.loanId) || loans.has(a.loanId)) throw new Error('loan_offset_allocation_duplicate'); loans.add(a.loanId); allocated = allocated.add(nonNegative(a.amount)); }
    if (allocated.compare(nonNegative(p.clearedBalance)) > 0) throw new Error('loan_offset_overallocated');
  }
  for (const account of o.accountIds) if (!o.snapshots.some(p => p.accountId === account && p.date === s.startDate)) issues.push('loan_offset_opening_unknown');
}
