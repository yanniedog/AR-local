import type { EvidenceReference, Fact, InterestPolicy, Rule } from '../../lib/productTermsEngine/types';
import type { SavingsTier } from '../../lib/productTermsEngine/savingsTypes';
export const SAVINGS_ADAPTER = 'aud-savings-base-v1' as const;
export type MonetaryCapability = 'savings_calculation' | 'mortgage_calculation' | 'portfolio_calculation';
export interface MonetaryDescriptor { name: string; bytes: number; sha256: string }
export interface MonetaryNamespace { schema_version: 3; capabilities: Partial<Record<MonetaryCapability, { index: MonetaryDescriptor; shards: Record<string, MonetaryDescriptor> }>> }
export interface SavingsScope { productKey: string; family: 'Savings'; cohortKey: string; tierKey: string; packageKey: string; from: string; toExclusive: string; coverage: 'whole_calculation_horizon' }
export interface MonetaryRouting { productKey: string; sourceGenerationId: string; exportContractSha256: string; runDate: string; coreAssetSha256: string; detailsAssetSha256: string; productRecordSha256: string }
export interface FieldCoverage { field: string; from: string; toExclusive: string; postingEventDates: string[]; evidenceIds: string[] }
export interface HistoricalObservation { observationId: string; generationId: string; exportContractSha256: string; manifestSha256: string; coreAssetSha256: string; detailsAssetSha256: string; rawSourceSha256: string; productRecordSha256: string; observedAt: string; rateRows: { coreRowIndex: number; rateIndex: number; rowSha256: string }[] }
export type HistoricalScope = Omit<SavingsScope, 'family'> & { family: 'Savings' | 'Mortgage' };
interface AuthorityBase { id: string; scope: HistoricalScope; from: string; toExclusive: string; evidenceIds: string[]; fieldCoverage: FieldCoverage[] }
export type HistoricalAuthority = AuthorityBase & ({ kind: 'retained_observation'; observations: HistoricalObservation[]; coverageProof: { basis: 'dated_source_policy' | 'complete_daily_observations'; from: string; toExclusive: string; evidenceIds: string[] } } | { kind: 'dated_official_clause'; documentVersionIds: string[]; documentSha256s: string[]; datedRateAndPolicyClauseIds: string[]; observedRateRows: false });
export interface AuthorityGraph {
  schemaVersion: 1; identitySha256: string;
  members: { sha256: string; bytes: number; decodedBytes: number; encoding: 'identity' | 'gzip'; kind: 'source_document' | 'observation_manifest' | 'core' | 'details' | 'raw_source' | 'coverage_proof' }[];
  authorities: HistoricalAuthority[];
  supersessions: { supersededAuthorityId: string; selectedAuthorityId: string; from: string; toExclusive: string; evidenceIds: string[] }[];
  completedPeriod: { asOf: string; completedThroughExclusive: string; timezone: 'Australia/Sydney' | 'Australia/Hobart'; basis: 'reviewed_data_completeness'; sourceSnapshotSha256: string; evidenceIds: string[] };
}
export interface SavingsInterest extends Omit<InterestPolicy, 'offset'> {
  dailyAccrualRounding: 'aggregate' | 'per_tier'; postingResidue: 'discard_with_rounding_adjustment'; postingDestination: 'same_account'; postingCalendar: 'explicit_calendar_dates_no_business_adjustment'; depositSettlementBasis: 'cleared_only' | 'cleared_and_uncleared';
}
export interface SavingsInterval { id: string; from: string; toExclusive: string; authorityId: string; kind: 'base'; rateMeaning: 'additive'; allocation: 'marginal' | 'whole_balance'; tiers: SavingsTier[]; interest: SavingsInterest; fieldEvidenceIds: Record<string, string[]> }
export interface SavingsDefinition { key: string; label: string; type: Fact['type']; unit: string | null; binding: 'customer_fact' | 'opening_balance' | 'calculation_start_date' | 'calculation_end_date'; evidenceIds: string[] }
export interface SavingsPolicy {
  kind: 'aud_savings_base_period_v1'; currency: 'AUD'; maxHorizonDays: number; calculationMode: 'historical_holding_period'; initialUnpostedAccrual: 'zero_user_confirmed'; openingClearedFunds: 'confirm_all_cleared_when_any_interval_uses_cleared_only';
  postingInventory: { from: string; toExclusive: string; coverage: 'all_source_due_dates'; boundary: 'from_inclusive_to_exclusive'; calendarAdjustment: 'none_source_declared'; dueDates: string[]; evidenceIds: string[]; rule: { kind: 'calendar_month_end'; evidenceIds: string[] } | { kind: 'explicit_dated_source_schedule'; sourceFrom: string; sourceToExclusive: string; sourceDueDates: string[]; completenessEvidenceIds: string[] } };
  externalMovements: 'none_user_confirmed'; withholding: 'none_user_confirmed_before_tax'; bonus: 'none_source_declared'; intro: 'none_source_declared'; offset: 'none_source_declared'; linkedAccounts: 'none_source_declared';
  fees: { coverage: 'reviewed_complete_no_fees'; deferredObligations: 'none_source_declared'; inventory: { categoryId: string; state: 'none_applicable'; evidenceIds: string[] }[]; evidenceIds: string[] };
  intervals: SavingsInterval[]; eligibility: Rule; inputDefinitions: SavingsDefinition[];
}
export interface SavingsSubject { schemaVersion: 3; capability: 'savings_calculation'; kind: SavingsPolicy['kind']; adapterVersion: typeof SAVINGS_ADAPTER; evaluatorVersion: 'product-terms-engine-v8'; id: string; scopeId: string; scope: SavingsScope; routing: MonetaryRouting; authorityGraph: AuthorityGraph; policy: SavingsPolicy; documentVersionIds: string[]; termRevisionIds: string[]; evidence: (EvidenceReference & { documentVersionId: string })[] }
export interface SavingsApproval { subjectId: string; capability: 'savings_calculation'; reviewId: string; reviewEvidenceSha256: string; benchmarkResultSha256: string; authorityGraphSha256: string; reviewedAt: string; checks: Record<'source_alignment' | 'historical_coverage' | 'scope_coverage' | 'input_bindings' | 'rule_semantics' | 'rate_schedule' | 'material_terms' | 'fee_coverage' | 'posting_and_residue' | 'benchmark', 'verified'> }
export interface MonetaryAsset { schemaVersion: 3; capability: 'savings_calculation'; productKey: string; routing: MonetaryRouting; approvalPolicy: 'as_of_adopted_edition'; identitySha256: string; subjects: { subject: SavingsSubject; approval: SavingsApproval }[] }
