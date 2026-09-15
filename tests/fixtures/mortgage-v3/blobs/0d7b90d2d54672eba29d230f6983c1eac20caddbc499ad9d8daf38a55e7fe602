import type { EvidenceReference, Fact, Rule } from '../../lib/productTermsEngine/types';
import type { SectionKey } from '../../types';
export const ELIGIBILITY_ADAPTER_VERSION = 'scoped-eligibility-v1' as const;
export const ELIGIBILITY_EVALUATOR_VERSION = 'product-terms-engine-v8' as const;
export type InputBinding = 'customer_fact' | 'assessment_date' | 'scenario_amount' | 'scenario_purpose' | 'scenario_security_value' | 'scenario_security_type' | 'scenario_ownership';
export interface EligibilityInput { key: string; label: string; type: Fact['type']; unit: string | null; clauseIds: string[]; binding: InputBinding }
export interface EligibilityScope { productKey: string; family: SectionKey; cohortKey: string; tierKey: string; packageKey: string; effectiveFrom: string; effectiveToExclusive: string; effectiveScope: 'assessment_date'; intervalBasis: 'reviewed_assessment_coverage'; coverage: 'product' | 'rate_variants'; rateIndexes: number[] }
export interface EligibilitySubject {
  schemaVersion: 2; kind: 'scoped_eligibility_v1'; capability: 'eligibility_only'; adapterVersion: typeof ELIGIBILITY_ADAPTER_VERSION; evaluatorVersion: typeof ELIGIBILITY_EVALUATOR_VERSION;
  id: string; scopeId: string; scope: EligibilityScope;
  source: { observationId: string; sourceSha256: string; generationId: string; exportContractSha256: string; runDate: string; provenanceManifestSha256: string; coreAssetSha256: string; detailsAssetSha256: string; productRecordSha256: string; rateRows: { coreRowIndex: number; rateIndex: number; rowSha256: string }[]; documentVersionIds: string[]; termRevisionIds: string[] };
  inputDefinitions: EligibilityInput[]; eligibility: Rule; fieldClauseIds: Record<'product' | 'family' | 'cohort' | 'tier' | 'package' | 'effectiveInterval' | 'effectiveScope' | 'coverage' | 'eligibility', string[]>; evidence: (EvidenceReference & { documentVersionId: string })[];
}
export interface EligibilityApproval { subjectId: string; capability: 'eligibility_only'; reviewId: string; reviewEvidenceSha256: string; benchmarkResultSha256: string; sourceSnapshotSha256: string; reviewedAt: string; checks: Record<'source_alignment' | 'scope_coverage' | 'input_bindings' | 'rule_semantics' | 'variant_binding', 'verified'> }
export interface EligibilityAsset { schemaVersion: 2; productKey: string; sourceObservationId: string; sourceGenerationId: string; runDate: string; coreAssetSha256: string; detailsAssetSha256: string; approvalPolicy: 'as_of_adopted_edition'; subjects: { subject: EligibilitySubject; approval: EligibilityApproval }[]; identitySha256: string }
