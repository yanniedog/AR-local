import type { SectionKey } from '../types';

export type BankMoveDir = 'cut' | 'hike' | 'mixed';

/** One provider rate-move detected by the Pi between consecutive ingest runs. */
export interface BankRateEvent {
  date: string;
  provider: string;
  section: SectionKey;
  dir: BankMoveDir;
  /** Products whose best advertised rate moved >= 5 bps. */
  moved: number;
  /** Products matched between the two runs. */
  total: number;
  /** Mean delta across moved products, in basis points (negative = cut). */
  avg_bps: number;
}

/** Per-provider daily series, positionally aligned to `run_dates`. */
export interface BankSectionSeries {
  median: (number | null)[];
  best: (number | null)[];
  count: (number | null)[];
}

/** Sample-size confidence for precomputed lender behaviour (AR-local bank_behaviour). */
export type PassThroughConfidence = 'insufficient' | 'early' | 'emerging' | 'established';

export interface BehaviourDirectionSummary {
  n: number;
  days_median: number | null;
  bps_median: number | null;
  ratio_median: number | null;
  confidence: PassThroughConfidence;
}

/** Per-provider hike/cut medians shipped in bank-history `behaviour`. */
export interface BehaviourProviderSummary {
  hike: BehaviourDirectionSummary;
  cut: BehaviourDirectionSummary;
}

export interface BehaviourSectionSummary {
  section: SectionKey;
  window_days: number;
  providers: Record<string, BehaviourProviderSummary>;
}

/** Pre-aggregated per-bank history + events asset (see app_payload_mobile.py). */
export interface BankInsightsPayload {
  schema_version: number;
  run_date: string;
  run_dates: string[];
  banks: Record<string, Partial<Record<SectionKey, BankSectionSeries>>>;
  events: BankRateEvent[];
  /** Optional precomputed pass-through summaries (may be empty early in the ledger). */
  behaviour?: Partial<Record<SectionKey, BehaviourSectionSummary>>;
}

/** Shared constants for bank-history move / pass-through scoring. */
export const MOVE_DIRS: readonly BankMoveDir[] = ['cut', 'hike', 'mixed'];
export const FOLLOW_DIRS: readonly ('cut' | 'hike')[] = ['cut', 'hike'];
export const DEFAULT_PASS_THROUGH_WINDOW_DAYS = 60;
export const DAY_MS = 24 * 60 * 60 * 1000;
