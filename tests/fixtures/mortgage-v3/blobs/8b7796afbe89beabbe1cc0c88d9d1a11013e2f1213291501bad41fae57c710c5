import type { Fact, Rule, Rounding } from './types';

export type FeeBasis = { type: 'balance'; accountId: string; point: 'day_open' | 'before_fee' } |
  { type: 'fact'; accountId: string; name: string; unit: 'AUD'; from: string; toExclusive: string };
export type FeePrice = { type: 'fixed'; value: string } |
  { type: 'percentage'; fraction: string; basis: FeeBasis; rounding: Rounding; minimum?: string; maximum?: string } |
  { type: 'indexed'; indexId: string; observations: { from: string; toExclusive: string; value: string; evidenceIds: string[] }[] } |
  { type: 'unknown'; reason: string };
export interface FeeDefinition {
  id: string;
  /** One source-defined obligation, independent of display IDs and occurrence IDs. */
  chargeIdentity: string;
  categoryId: string;
  evidenceIds: string[];
  scope: { type: 'account'; accountId: string } | { type: 'package'; packageInstanceId: string; memberAccountIds: string[]; debtorAccountId: string };
  timing: { type: 'dated'; from: string; toExclusive: string; triggerCoverage: 'reviewed_complete' | 'unknown'; occurrences: { incurredDate: string; dueDate: string; triggerId: string }[] } |
    { type: 'recurring'; anchor: string; unit: 'days' | 'months'; step: number; monthConvention: 'clamp' | 'preserve_month_end';
      from: string; toExclusive: string; calendarAdjustment: 'none' | 'unknown'; settlement: 'same_day' | 'unknown' };
  order: number;
  debit: { type: 'product_balance' } | { type: 'external_account'; accountId: string } | { type: 'unknown' };
  price: FeePrice;
  applicability: Rule | null;
  waiver: Rule | null;
  /** Source-owned assessment periods for each payable occurrence; global facts never waive fees. */
  ruleAssessments?: { triggerId?: string; dueDate: string; accountId: string; from: string; toExclusive: string; factNames: string[]; evidenceIds: string[] }[];
  discounts: { id: string; rule: Rule; type: 'fraction' | 'fixed'; value: string }[];
  discountPrecedence: 'exclusive' | 'first_match' | 'additive' | 'unknown';
  discountRounding: Rounding | 'unknown';
}
export interface FeeSchedule {
  schemaVersion: 1;
  accountId: string;
  from: string;
  toExclusive: string;
  inventoryCoverage: 'reviewed_complete' | 'unknown';
  /** Covers incurred obligations too; payable-after-horizon obligations remain unsettled. */
  deferredObligations: 'none_confirmed' | 'listed' | 'unknown';
  evidenceIds: string[];
  inventory: { categoryId: string; state: 'scheduled' | 'none_applicable' | 'unknown' | 'lifecycle_owned'; lifecycleOccurrenceId?: 'td:break-fee'; feeIds: string[]; evidenceIds: string[] }[];
  ordering: 'before_scenario_events' | 'after_scenario_events' | 'unknown';
  fees: FeeDefinition[];
}
export interface FeeFact { name: string; accountId: string; from: string; toExclusive: string; value: Fact }
export interface FeeOccurrence { id: string; fee: FeeDefinition; incurredDate: string; dueDate: string; triggerId: string }
