import { Decimal, decimalZero } from '../../lib/productTermsEngine/decimal';
import { nonNegative, canonical, hashText } from '../../lib/productTermsEngine/validation';
import { nonNegativeComponent } from '../../lib/productTermsEngine/loanComponents';
import { LOAN_COMPONENTS } from '../../lib/productTermsEngine/loanTypes';
import { safeId } from '../customerProfile';
import { assertMortgageInputs } from './schemaValidation';
import { mortgageDueDates, mortgageObligationId } from './calendar';
import { mortgageCoverage } from './validation';
import type { MortgageInputs, MortgageSubject } from './types';
export function admitMortgageInputs(s: MortgageSubject, i: MortgageInputs) {
 assertMortgageInputs(i);
 if (![i.accountId,i.offerId,i.sourceVersion,i.snapshotId].every(safeId) || i.from !== s.scope.from || i.toExclusive !== s.scope.toExclusive || i.noCarriedArrearsOrDefault !== true || i.noExcludedMovements !== true || i.executionCoverage !== 'complete') throw new Error('Mortgage account period or confirmations unavailable');
 if (Decimal.parse(i.confirmedAnnualRate).compare(Decimal.parse(s.policy.annualRate)) !== 0) throw new Error('Confirmed mortgage rate differs');
 const sum = LOAN_COMPONENTS.reduce((n,k) => n.add(k === 'accruedInterest' ? nonNegativeComponent(i.openingComponents[k]) : nonNegative(i.openingComponents[k])),decimalZero());
 if (sum.compare(nonNegativeComponent(i.openingOutstanding)) !== 0) throw new Error('Mortgage opening components do not reconcile');
 const amount = nonNegative(i.obligationAmount); if (amount.compare(decimalZero()) <= 0) throw new Error('Mortgage obligation must be positive');
 const due = mortgageDueDates(s,i.originalAnchor), obligations = due.map(date => ({id:mortgageObligationId(s,i.accountId,date),dueDate:date,accountId:i.accountId,amount:{type:'fixed' as const,value:amount.fixed()},evidenceIds:s.policy.fieldEvidenceIds.obligationCalendar}));
 mortgageCoverage(s,{obligationCalendar:due,paymentPhase:due,paymentRounding:due,accruedSettlement:due});
 const paid = new Map<string,Decimal>(), orders = new Set<string>(), ids = new Set<string>();
 for (const e of i.payments) {
  const obligation = obligations.find(o => o.id === e.obligationId), key = `${e.date}:${e.order}`, value = nonNegative(e.amount);
  if (!safeId(e.id) || ids.has(e.id) || orders.has(key) || e.accountId !== i.accountId || !obligation) throw new Error('Mortgage payment identity invalid'); ids.add(e.id); orders.add(key);
  if (e.date !== obligation.dueDate || e.phase !== s.policy.paymentPhase) throw new Error('Mortgage payment timing unsupported');
  if (value.compare(decimalZero()) <= 0) throw new Error('Mortgage payment must be positive');
  const total = (paid.get(e.obligationId) ?? decimalZero()).add(value); if (total.compare(amount) > 0) throw new Error('Mortgage payment exceeds obligation'); paid.set(e.obligationId,total);
 }
 const positive = s.policy.fees.occurrences.filter(f => nonNegative(f.amount).compare(decimalZero()) > 0);
 if (i.feeSettlements.length !== positive.length || new Set(i.feeSettlements.map(f => f.occurrenceId)).size !== positive.length || new Set(i.externalAccounts.map(a => a.role)).size !== i.externalAccounts.length || i.externalAccounts.some(a => !safeId(a.accountId) || a.accountId === i.accountId)) throw new Error('Mortgage fee settlement inventory invalid');
 for (const fee of positive) { const x = i.feeSettlements.find(x => x.occurrenceId === fee.id), account = i.externalAccounts.find(a => a.role === fee.externalAccountRole); if (!x || !account || x.externalAccountId !== account.accountId || x.date !== fee.dueDate || nonNegative(x.amount).compare(nonNegative(fee.amount)) !== 0) throw new Error('Mortgage external fee settlement differs'); }
 const definitions = new Map(s.policy.inputDefinitions.map(d => [d.field,d])); if (new Set(i.customerFacts.map(f => f.field)).size !== i.customerFacts.length || i.customerFacts.some(f => definitions.get(f.field)?.binding !== 'customer_fact' || f.state === 'known' && !f.value || f.state !== 'known' && f.value !== null)) throw new Error('Mortgage customer fact binding invalid');
 return {obligations,feeOrders:new Map([...s.policy.fees.occurrences].sort((a,b) => a.dueDate.localeCompare(b.dueDate) || a.order-b.order).map((f,n) => [f.id,n])),technicalFeeAccount:`mortfee_${hashText(canonical([s.id,i.accountId])).slice(0,24)}`};
}
