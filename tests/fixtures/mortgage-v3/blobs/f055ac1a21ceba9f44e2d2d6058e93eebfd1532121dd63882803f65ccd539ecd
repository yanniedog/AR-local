import { calendarDate, dayNumber } from './calendar';
import { Decimal, decimalZero } from './decimal';
import { evaluateEligibility } from './eligibility';
import { canonical, hashText, money, nonNegative, rate, validateLedger } from './validation';
import { EVALUATOR_VERSION, type CalculationReceipt, type LedgerContract, type LedgerEvent, type LedgerScenario } from './types';
import { dailyInterest } from './interestAccrual';
import { savingsInterest, type SavingsActivityCache } from './savingsAccrual';
import { tdAccountPort } from './tdLedger';
import { ContractFeeLedger } from './feeLedger';
import { loanAccountPort } from './loanLedger';
import { finishAccount, type AccountPort } from './accountPort';
import { dateIndex } from './dateIndex';
import type { AccountAuthority } from './accountAuthority';

function feeAmount(event: Extract<LedgerEvent, { type: 'fee' }>): Decimal {
  if (event.amount.type === 'fixed') return money(event.amount.value);
  const rule = event.amount;
  let amount = Decimal.parse(rule.fraction).mul(money(rule.basis));
  if (rule.minimum !== undefined && amount.compare(money(rule.minimum)) < 0) amount = money(rule.minimum);
  if (rule.maximum !== undefined && amount.compare(money(rule.maximum)) > 0) amount = money(rule.maximum);
  return amount.rounded(2, rule.rounding);
}

/** Pure synchronous evaluator, bounded at fifty years/10k explicit events; performs no I/O. */
export function calculateLedger(contract: LedgerContract, scenario: LedgerScenario): CalculationReceipt {
  const receipt: CalculationReceipt = {
    schemaVersion: 1, evaluatorVersion: EVALUATOR_VERSION, inputSha256: '', contractId: contract?.id ?? '',
    dependencies: [], status: 'unsupported', completeness: 'unsupported', issueDetails: [], claimAvailable: false, issues: [], assumptions: [], eligibility: null, totals: null, ledger: [],
  };
  try {
    return finalizeAccount(finishAccount(prepareAccount(contract, scenario, receipt)));
  } catch (error) {
    receipt.status = 'unsupported'; receipt.claimAvailable = false; receipt.totals = null; receipt.ledger = [];
    receipt.issues.push(error instanceof Error ? error.message : 'invalid_contract');
    return receipt;
  }
}

/** Shared validated state port; portfolio code supplies the same bound receipt. */
export function prepareAccount(contract: LedgerContract, scenario: LedgerScenario, receipt: CalculationReceipt, authority?: AccountAuthority): AccountPort {
  const input = canonical({ evaluatorVersion: EVALUATOR_VERSION, contract, scenario });
  if (input.length > 4_000_000) throw new Error('input_size_exceeded');
  receipt.inputSha256 = hashText(input); receipt.issueDetails = [];
  receipt.issues = validateLedger(contract, scenario, receipt.issueDetails, authority);
  if (scenario.tdConfirmation) receipt.localTdConfirmation = { ...scenario.tdConfirmation };
  receipt.dependencies = [...contract.dependencyIds]; receipt.assumptions = [...scenario.assumptions];
  receipt.eligibility = evaluateEligibility(contract.eligibility, scenario.facts);
  if (receipt.eligibility.status !== 'meets') receipt.issues.push(`eligibility:${receipt.eligibility.status}`);
  if (contract.loanContract && !contract.loanContract.opening.components) return (function* (): AccountPort { return receipt; })();
  return contract.loanContract ? loanAccountPort(contract, scenario, receipt, authority) : contract.tdLifecycle ? tdAccountPort(contract, scenario, receipt) : genericAccountPort(contract, scenario, receipt, authority);
}
export function finalizeAccount(receipt: CalculationReceipt): CalculationReceipt {
  const classified = new Set((receipt.issueDetails ?? []).filter(d => receipt.issues[d.index] === d.code).map(d => d.index));
  receipt.completeness = !receipt.issues.length ? 'factual_complete' : receipt.issues.every((_, index) => classified.has(index)) ? 'conditional_complete' : 'incomplete';
  receipt.status = receipt.issues.length ? 'incomplete' : 'complete'; receipt.claimAvailable = receipt.status === 'complete';
  const whollyClassified = new Map<string, boolean>();
  receipt.issues.forEach((code, index) => whollyClassified.set(code, (whollyClassified.get(code) ?? true) && classified.has(index)));
  receipt.issues = [...new Set(receipt.issues)];
  receipt.issueDetails = (receipt.issueDetails ?? []).filter(d => whollyClassified.get(d.code)).map(d => ({ ...d, index: receipt.issues.indexOf(d.code) }));
  return receipt;
}

export function* genericAccountPort(contract: LedgerContract, scenario: LedgerScenario, receipt: CalculationReceipt, authority?: AccountAuthority): AccountPort {
  let balance = money(scenario.openingBalance), offset = money(scenario.initialOffset), annualRate = rate(contract.initialAnnualRate);
  let accrued = decimalZero(), unposted = decimalZero(), posted = decimalZero(), fees = decimalZero();
  let inflows = decimalZero(), outflows = decimalZero();
  const events = [...scenario.events].sort((a, b) => a.date.localeCompare(b.date) || a.order - b.order);
  const eventsByDate = dateIndex(events, e => e.date);
  const postingDates = new Set(contract.interest.postingDates);
  const activityCache: SavingsActivityCache = new Map();
  const contractFees = new ContractFeeLedger(contract, scenario, receipt);
  for (let day = dayNumber(scenario.startDate); day < dayNumber(scenario.endDateExclusive); day++) {
    const date = calendarDate(day);
    const dayOpen = balance;
    const incoming = yield { phase: 'start', date, balance: balance.fixed(12), receipt };
    const movementStatus = new Map(incoming.map(m => [m.id, m.status]));
    if (authority?.balanceUncertain) contractFees.tainted = true;
    const today: LedgerEvent[] = [...(eventsByDate.get(date) ?? []), ...incoming.map(m => ({ id: m.id, date, order: m.order, type: 'cashflow' as const, delta: m.delta, label: 'Portfolio-owned transfer leg.', evidenceIds: m.evidenceIds }))].sort((a, b) => a.order - b.order);
    if (new Set(today.map(e => e.order)).size !== today.length) throw new Error('portfolio_event_order_collision');
    if (contract.feeSchedule?.ordering !== 'after_scenario_events') balance = contractFees.apply(date, balance, dayOpen);
    for (const event of today) {
      let amount: Decimal | null = decimalZero(), note: string | undefined;
      if (event.type === 'cashflow') {
        amount = money(event.delta); balance = balance.add(amount);
        if (contract.direction === 'liability' && amount.compare(decimalZero()) < 0) receipt.issues.push('repayment_principal_allocation_unsupported');
        if (amount.compare(decimalZero()) >= 0) inflows = inflows.add(amount); else outflows = outflows.sub(amount);
      } else if (event.type === 'rate') { annualRate = rate(event.annualRate); amount = null; }
      else if (event.type === 'offset') { offset = nonNegative(event.balance); amount = null; }
      else {
        const waiver = event.waiver ? evaluateEligibility(event.waiver, scenario.facts) : null;
        if (waiver?.status === 'needs_information') {
          receipt.issues.push(`fee_waiver_unknown:${event.id}`); amount = null; note = 'Unpriced waiver; downstream amounts are evaluated known components only.';
        } else if (waiver?.status === 'meets') { amount = decimalZero(); note = 'Waived by supplied criterion.'; }
        else {
          amount = feeAmount(event); fees = fees.add(amount);
          balance = contract.direction === 'asset' ? balance.sub(amount) : balance.add(amount);
        }
      }
      if (balance.compare(decimalZero()) < 0) throw new Error('negative_balance_unsupported');
      receipt.ledger.push({ date, id: event.id, type: event.type, amount: amount?.fixed() ?? null, balance: balance.fixed(), evidenceIds: 'evidenceIds' in event ? event.evidenceIds : [], ...(movementStatus.has(event.id) ? { settlementStatus: movementStatus.get(event.id) } : {}), ...(note ? { note } : {}) });
    }
    if (contract.feeSchedule?.ordering === 'after_scenario_events') balance = contractFees.apply(date, balance, dayOpen);
    let basis = balance.sub(offset);
    if (basis.compare(decimalZero()) < 0) basis = decimalZero();
    const savings = contract.savingsSchedule ? savingsInterest(basis, date, contract.interest, contract.savingsSchedule, scenario.savingsAssessments ?? [], activityCache) : null;
    const interest = authority?.balanceUncertain ? decimalZero() : savings?.amount ?? dailyInterest(basis, annualRate, date, contract.interest);
    if (savings) receipt.issues.push(...savings.issues);
    accrued = accrued.add(interest); unposted = unposted.add(interest);
    receipt.ledger.push({ date, id: `accrue:${date}`, type: 'interest_accrual', amount: authority?.balanceUncertain ? null : interest.fixed(12), balance: balance.fixed(), evidenceIds: contract.interest.evidenceIds,
      ...(contractFees.tainted ? { note: 'Balance and interest depend on unresolved fees; known-component arithmetic only.' } : {}),
      ...(savings ? { savingsContributions: contractFees.tainted ? savings.contributions.map(c => c.status === 'applied' ? { ...c, status: 'needs_information' as const } : c) : savings.contributions } : {}) });
    if (postingDates.has(date)) {
      const payment = unposted.rounded(2, contract.interest.postingRounding);
      // The remainder is disclosed in accrued totals; no invented penny carry after posting.
      unposted = decimalZero(); posted = posted.add(payment); balance = balance.add(payment);
      if (balance.compare(decimalZero()) < 0) throw new Error('negative_balance_unsupported');
      receipt.ledger.push({ date, id: `post:${date}`, type: 'interest_posting', amount: payment.fixed(), balance: balance.fixed(), evidenceIds: contract.interest.evidenceIds,
        ...(contractFees.tainted ? { note: 'Known-component posting; unresolved fee dependencies remain.' } : {}) });
    }
    yield { phase: 'end', date, balance: balance.fixed(12), receipt };
  }
  if (contractFees.tainted) receipt.issues.push('balance_interest_fee_dependency_unknown');
  receipt.totals = {
    openingBalance: money(scenario.openingBalance).fixed(), externalCashflowNet: inflows.sub(outflows).fixed(), principalRepaid: null,
    externalInflows: inflows.fixed(), externalOutflows: outflows.fixed(), interestAccrued: accrued.fixed(12),
    interestPosted: posted.fixed(), interestUnposted: unposted.fixed(12), feesCharged: fees.add(contractFees.charged).fixed(), closingBalance: balance.fixed(),
    feesDebitedBalance: fees.add(contractFees.debitedBalance).fixed(), feesPaidExternal: contractFees.paidExternal.fixed(),
    interestRoundingAdjustment: posted.add(unposted).sub(accrued).fixed(12),
  };
  return receipt;
}
