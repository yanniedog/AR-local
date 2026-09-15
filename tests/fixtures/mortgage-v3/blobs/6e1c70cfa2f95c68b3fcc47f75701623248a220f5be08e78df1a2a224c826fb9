import type { Fact, Rule, Rounding } from '../../lib/productTermsEngine/types';
import type { LoanComponent, LoanComponentValues } from '../../lib/productTermsEngine/loanTypes';
import type { AuthorityGraph, MonetaryRouting, SavingsApproval, SavingsSubject } from '../monetaryContracts/types';
export const MORTGAGE_ADAPTER = 'aud-mortgage-confirmed-obligations-v1' as const;
export type MortgageBinding = 'customer_fact' | 'opening_principal' | 'obligation_amount' | 'from_date' | 'to_exclusive_date' | 'confirmed_annual_rate' | 'offer_purpose' | 'offer_security' | 'repayment_type';
export interface MortgageDefinition { field: string; label: string; type: Fact['type']; unit: string | null; binding: MortgageBinding; evidenceIds: string[] }
export interface MortgageFee { id: string; incurredDate: string; dueDate: string; order: number; amount: string; debit: 'external_account'; settlement: 'exact_cleared_due_date_amount_and_account'; externalAccountRole: string; evidenceIds: string[] }
export interface MortgagePolicy {
 kind: 'aud_mortgage_confirmed_obligations_v1'; currency: 'AUD'; mode: 'historical_confirmed_obligations'; maxHorizonDays: 366; authorityIds: string[]; annualRate: string;
 interestBearing: LoanComponent[]; allocation: LoanComponent[]; paymentPhase: 'before_accrual' | 'after_accrual'; paymentRounding: Rounding; accruedSettlement: 'round_before_each_payment';
 dayCount: 'actual_365_fixed'; dailyRateRounding: { scale: number; unit: 'fraction' | 'percent'; mode: Rounding } | null; dailyAccrualScale: number | null; accrualRounding: Rounding; postingRounding: Rounding; postingResidue: 'round_component_then_transfer_all_to_posted_debt';
 postingInventory: { rule: 'calendar_month_end'; boundary: 'from_inclusive_to_exclusive'; calendarAdjustment: 'none_source_declared'; dueDates: string[]; coverage: 'all_source_due_dates' };
 obligationCalendar: { cadence: 'monthly'; monthConvention: 'clamp' | 'preserve_month_end'; anchorBinding: 'private_original_anchor'; amountBinding: 'private_confirmed_fixed_amount'; calendarAdjustment: 'none_source_declared'; paymentAdmission: 'exact_due_date_and_phase_no_cumulative_excess' };
 openingState: 'confirm_no_carried_overdue_obligations_or_default'; excludedPeriodEffects: string;
 fees: { coverage: 'complete_source_inventory'; ordering: 'before_scenario_events' | 'after_scenario_events'; occurrences: MortgageFee[] };
 eligibility: Rule; inputDefinitions: MortgageDefinition[]; fieldEvidenceIds: Record<string, string[]>;
}
export interface MortgageSubject extends Omit<SavingsSubject, 'capability' | 'kind' | 'adapterVersion' | 'scope' | 'policy'> {
 capability: 'mortgage_calculation'; kind: MortgagePolicy['kind']; adapterVersion: typeof MORTGAGE_ADAPTER;
 scope: Omit<SavingsSubject['scope'], 'family'> & { family: 'Mortgage' }; policy: MortgagePolicy;
 target: { kind: 'product'; productCategory: 'RESIDENTIAL_MORTGAGES' } | { kind: 'rate_variant'; section: 'Mortgage'; coreRowIndex: number; rateIndex: number; rowSha256: string; rateUnit: 'fraction'; annualRate: string };
}
export type MortgageApproval = Omit<SavingsApproval, 'capability'> & { capability: 'mortgage_calculation' };
export interface MortgageAsset { schemaVersion: 3; capability: 'mortgage_calculation'; productKey: string; routing: MonetaryRouting; approvalPolicy: 'as_of_adopted_edition'; identitySha256: string; subjects: { subject: MortgageSubject; approval: MortgageApproval }[] }
export interface MortgageInputs {
 accountId: string; offerId: string; sourceVersion: string; snapshotId: string; from: string; toExclusive: string; confirmedAt: string; provenance: 'user_reported_bank_offer_and_statement'; confirmedAnnualRate: string;
 openingOutstanding: string; openingComponents: LoanComponentValues; noCarriedArrearsOrDefault: boolean | null; noExcludedMovements: boolean | null; obligationAmount: string; originalAnchor: string; executionCoverage: 'complete' | 'unknown';
 payments: { id: string; accountId: string; obligationId: string; date: string; phase: MortgagePolicy['paymentPhase']; order: number; amount: string; status: 'cleared' }[];
 feeSettlements: { occurrenceId: string; externalAccountId: string; amount: string; date: string; status: 'cleared' }[]; externalAccounts: { role: string; accountId: string }[];
 confirmedOfferFacts: { purpose?: string; security?: string; repaymentType?: string };
 customerFacts: { field: string; state: 'known' | 'unknown' | 'unavailable' | 'not_applicable'; value: Fact | null }[];
}
export type MortgageAuthority = AuthorityGraph['authorities'][number];
