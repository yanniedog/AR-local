import type { EligibilityResult, Facts, Rule } from './types';
import type { SavingsActivityData, SavingsActivityMetric, SavingsActivityResult } from './savingsActivityTypes';

export interface SavingsTier {
  id: string;
  /** Implicit lower edge is previous upper edge; first starts at zero. Final edge must be null. */
  upperInclusive: string | null;
  annualRate: string;
  evidenceIds: string[];
}
export interface SavingsRateComponent {
  id: string;
  kind: 'base' | 'bonus' | 'intro';
  allocation: 'marginal' | 'whole_balance';
  /** Rates are additive components, never an ambiguous headline total plus a bonus. */
  rateMeaning: 'additive';
  tiers: SavingsTier[];
  qualification: { assessmentKey: string; accountId: string; rule: Rule; windows: SavingsAssessmentWindow[]; activityMetrics?: SavingsActivityMetric[] } | null;
  evidenceIds: string[];
}
export interface SavingsAssessmentWindow {
  from: string; toExclusive: string;
  appliesFrom: string; appliesToExclusive: string;
  evidenceIds: string[];
}
export interface SavingsRateInterval {
  id: string;
  from: string;
  toExclusive: string;
  components: SavingsRateComponent[];
  evidenceIds: string[];
}
export interface SavingsRateSchedule {
  schemaVersion: 1;
  dailyAccrualRounding: 'aggregate' | 'per_tier';
  intervals: SavingsRateInterval[];
}
/** Explicit assessment-to-interest mapping; dates/cutoffs are not inferred from a month label. */
export interface SavingsAssessment {
  id: string;
  assessmentKey: string;
  accountId: string;
  from: string;
  toExclusive: string;
  appliesFrom: string;
  appliesToExclusive: string;
  coverage: 'complete' | 'unknown';
  facts: Facts;
  evidenceIds: string[];
  activity?: SavingsActivityData;
}
export interface SavingsContribution {
  intervalId: string;
  componentId: string;
  kind: SavingsRateComponent['kind'];
  allocation: SavingsRateComponent['allocation'];
  status: 'applied' | 'does_not_meet' | 'needs_information';
  assessmentId: string | null;
  qualification: EligibilityResult | null;
  activityResults?: SavingsActivityResult[];
  tiers: { id: string; basis: string; annualRate: string; accrual: string; evidenceIds: string[] }[];
  evidenceIds: string[];
}
