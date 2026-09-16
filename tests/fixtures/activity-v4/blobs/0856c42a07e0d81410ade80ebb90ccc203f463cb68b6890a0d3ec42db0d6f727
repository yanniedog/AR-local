import type { Rounding } from './types';

export const LOAN_COMPONENTS = ['principal', 'postedInterest', 'accruedInterest', 'capitalizedCharges', 'otherDebt'] as const;
export type LoanComponent = typeof LOAN_COMPONENTS[number];
export type LoanComponentValues = Record<LoanComponent, string>;
export interface LoanContract {
  schemaVersion: 1;
  accountId: string;
  cohortKey: string;
  offerId: string;
  sourceVersion: string;
  from: string;
  toExclusive: string;
  evidenceIds: string[];
  opening: { effectiveDate: string; snapshotId: string; outstanding: string; components: LoanComponentValues | null; redrawAvailable: string; evidenceIds: string[] };
  interestBearing: LoanComponent[] | 'unknown';
  allocation: LoanComponent[] | 'unknown';
  paymentTiming: 'before_accrual' | 'after_accrual' | 'unknown';
  overpayment: 'reject' | 'unknown';
  paymentRounding: Rounding | 'unknown';
  accruedSettlement: 'round_before_each_payment' | 'unknown';
  advancesTiming: 'start_of_day_before_fees';
  feeBalanceBasis: 'outstanding_including_unposted';
  obligationMeasurement: 'before_payment_phase';
  reversalPolicy: 'restore_components_no_interest_recalculation' | 'unknown';
  scheduleCoverage: 'reviewed_complete' | 'unknown';
  obligations: { id: string; dueDate: string; accountId: string; amount: { type: 'fixed'; value: string } | { type: 'interest_due' }; evidenceIds: string[] }[];
  advances: { id: string; date: string; amount: string; status: 'cleared' | 'projected'; evidenceIds: string[] }[];
  rates: { date: string; annualRate: string | null; evidenceIds: string[] }[];
  extraPayments: { allowed: boolean | 'unknown'; totalCap: string | null; increasesRedraw: boolean | 'unknown'; evidenceIds: string[] };
  redraw: { allowed: boolean | 'unknown'; totalCap: string | null; evidenceIds: string[] };
  feeFunding: { occurrenceId: string; method: 'capitalize' | 'redraw'; evidenceIds: string[] }[];
  offset: null | { coverage: 'complete' | 'unknown'; balanceHistory: 'complete_step_schedule' | 'observations_only'; from: string; toExclusive: string; accountIds: string[]; loanIds: string[];
    snapshots: { date: string; accountId: string; clearedBalance: string; allocations: { loanId: string; amount: string }[]; evidenceIds: string[] }[] };
  closure: null | { date: string; requireSettled: boolean; evidenceIds: string[] };
}
export interface LoanExecution {
  id: string;
  accountId: string;
  date: string;
  order: number;
  status: 'cleared' | 'projected';
  type: 'payment' | 'extra_payment' | 'redraw' | 'reversal';
  amount: string;
  obligationId?: string;
  reversalOf?: string;
  evidenceIds: string[];
}
export interface LoanInputs { offerId: string; sourceVersion: string; openingSnapshotId: string; mode: 'cleared' | 'projected'; executions: LoanExecution[] }
export interface LoanResult {
  componentStatus: 'known' | 'partial';
  outstandingDebt: string | null;
  knownComponentDebt: string;
  opening: LoanComponentValues;
  closing: LoanComponentValues;
  principalAdvanced: string;
  principalRepaid: string | null;
  interestPaid: string;
  chargesPaid: string;
  redrawAvailable: string;
  redrawUsed: string;
  obligations: { id: string; dueDate: string; due: string | null; paid: string; status: 'paid' | 'unpaid' | 'partial' | 'unknown' }[];
  perspective: 'product_account_with_external_fees_separate';
}
