import type { Fact } from './types';

export type SavingsActivityKind = 'deposit' | 'withdrawal' | 'purchase' | 'refund' | 'interest' | 'fee' | 'tax' | 'unknown';
export interface SavingsActivityEvent {
  id: string; accountId: string; date: string;
  dateBasis: 'processed' | 'transaction';
  status: 'settled' | 'pending' | 'unknown';
  kind: SavingsActivityKind;
  /** Positive magnitudes; growth adjustment signs are defined by event kind. */
  amount: string;
  classification: string | null;
  originalPurchaseId?: string;
}
export interface SavingsActivityData {
  events: SavingsActivityEvent[];
  coverage: { accountId: string; from: string; toExclusive: string; status: 'complete' | 'unknown' }[];
  balances: { accountId: string; from: string; toExclusive: string; opening: string; closing: string }[];
}
export interface SavingsActivityMetric {
  id: string; field: string;
  /** Source-defined role and its explicitly bound account set; unlisted accounts never count. */
  accountRole: string; accountIds: string[];
  kind: 'deposit_total' | 'withdrawal_count' | 'purchase_count' | 'balance_growth';
  dateBasis: 'processed' | 'transaction';
  settlement: 'settled_only' | 'include_pending';
  includedClassifications: string[];
  excludedClassifications: string[];
  /** Null explicitly means unresolved; any relevant refund then prevents a result. */
  refundPolicy: 'ignore' | 'exclude_refunded_purchase' | null;
  growthAdjustments: { interest: 'include' | 'exclude'; fee: 'include' | 'exclude'; tax: 'include' | 'exclude' } | null;
  evidenceIds: string[];
}
export interface SavingsActivityResult {
  metricId: string; field: string; status: 'known' | 'unknown';
  fact: Fact | null; reason: string | null; evidenceIds: string[];
}
