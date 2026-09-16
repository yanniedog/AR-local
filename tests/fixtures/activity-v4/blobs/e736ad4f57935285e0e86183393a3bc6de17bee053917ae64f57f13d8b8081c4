import { Decimal, decimalZero } from './decimal';
import { feeDebitsAccount, feeOccurrences } from './feeSchedule';
import { priceFee } from './feePricing';
import type { FeeOccurrence } from './feeTypes';
import type { CalculationReceipt, LedgerContract, LedgerScenario, RuleTrace } from './types';

function traceEvidence(trace: RuleTrace): string[] { return [...trace.evidenceIds, ...(trace.children ?? []).flatMap(traceEvidence)]; }

export class ContractFeeLedger {
  charged = decimalZero();
  debitedBalance = decimalZero();
  paidExternal = decimalZero();
  tainted: boolean;
  private byDate = new Map<string, FeeOccurrence[]>();
  constructor(private contract: LedgerContract, private scenario: LedgerScenario, private receipt: CalculationReceipt) {
    this.tainted = receipt.issues.some(issue => /fee_(inventory|deferred_obligations|schedule_horizon|category_unknown|trigger_coverage|recurrence_coverage|timing_unknown|ordering_unknown)/.test(issue));
    if (contract.feeSchedule) for (const occurrence of feeOccurrences(contract.feeSchedule)) {
      if (occurrence.dueDate >= scenario.startDate && occurrence.dueDate < scenario.endDateExclusive) {
        const list = this.byDate.get(occurrence.dueDate) ?? []; list.push(occurrence); this.byDate.set(occurrence.dueDate, list);
      }
    }
  }
  apply(date: string, balance: Decimal, dayOpen: Decimal): Decimal {
    const schedule = this.contract.feeSchedule;
    if (!schedule) return balance;
    for (const occurrence of this.byDate.get(date) ?? []) {
      const fee = occurrence.fee;
      const result = !feeDebitsAccount(fee, schedule.accountId) ? { amount: decimalZero(), reason: 'Different designated package debtor.' } :
        schedule.ordering === 'unknown' ? { amount: null, reason: 'fee_ordering_unknown' } :
          fee.debit.type === 'unknown' ? { amount: null, reason: 'fee_debit_location_unknown' } :
            priceFee(fee, date, this.scenario, dayOpen, balance, this.tainted, occurrence.triggerId);
      if (result.amount === null) {
        this.receipt.issues.push(`${result.reason}:${occurrence.id}`);
        if (fee.debit.type !== 'external_account') this.tainted = true;
      } else {
        this.charged = this.charged.add(result.amount);
        if (fee.debit.type === 'external_account') this.paidExternal = this.paidExternal.add(result.amount);
        else {
          this.debitedBalance = this.debitedBalance.add(result.amount);
          balance = this.contract.direction === 'asset' ? balance.sub(result.amount) : balance.add(result.amount);
        }
      }
      if (balance.compare(decimalZero()) < 0) throw new Error('negative_balance_unsupported');
      this.receipt.ledger.push({ date, id: occurrence.id, type: 'fee', amount: result.amount?.fixed() ?? null, balance: balance.fixed(),
        evidenceIds: [...new Set([...fee.evidenceIds, ...('evidenceIds' in result ? result.evidenceIds ?? [] : []), ...('ruleTraces' in result ? result.ruleTraces.flatMap(traceEvidence) : [])])],
        ...('ruleTraces' in result ? { feeRuleTraces: result.ruleTraces } : {}),
        ...(fee.debit.type === 'unknown' ? {} : { feeDebitAccountId: fee.debit.type === 'external_account' ? fee.debit.accountId : fee.scope.type === 'package' ? fee.scope.debtorAccountId : schedule.accountId }),
        note: result.reason ?? (fee.debit.type === 'external_account' ? 'Paid from the separately nominated account; product balance unchanged.' : 'Contract-owned charge.') });
    }
    return balance;
  }
}
