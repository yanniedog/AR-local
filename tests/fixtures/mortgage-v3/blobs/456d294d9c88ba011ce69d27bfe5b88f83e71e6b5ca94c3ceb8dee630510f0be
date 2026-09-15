export type SectionKey = 'Mortgage' | 'Savings' | 'TD';

export const SECTION_KEYS: SectionKey[] = ['Mortgage', 'Savings', 'TD'];

/** A flattened rate row (a superset of the dashboard's BANK_SECTION_COLUMNS). */
export interface RateRow {
  provider: string;
  product_id?: string;
  product_key: string;
  product_name: string;
  category?: string;
  /** Normalized fraction as a string, e.g. "0.0634" == 6.34%. */
  rate: string;
  /**
   * For a bonus/intro headline, the product's published unconditional ongoing
   * (base) tier rate — what the customer earns once the bonus conditions lapse
   * or the intro window ends. Pi-joined from the sibling base tier; absent when
   * the bank does not publish a separate base tier.
   */
  ongoing_rate?: string;
  comparison_rate?: string;
  rate_type?: string;
  repayment_type?: string;
  loan_purpose?: string;
  term?: string;
  term_months?: string | number;
  lvr_tier?: string;
  ribbon_normalized?: boolean;
  security_purpose?: string;
  ribbon_repayment_type?: string;
  ribbon_rate_structure?: string;
  ribbon_fixed_term?: string | number;
  account_type?: string;
  ribbon_deposit_kind?: string;
  balance_min?: string | number;
  balance_max?: string | number;
  interest_payment?: string;
  feature_set?: string;
  /** 'standard' | 'non_standard' | '' (legacy). */
  account_class?: string;
  /** Canonical semantic-tier identity is safe for an exact saved-rate alert. */
  exact_alert_eligible?: boolean;
  rate_index?: number;
  last_updated?: string;
  /** Dot-delimited hierarchy, e.g. "HOME_LOAN.OO.PI.VARIABLE.LVR_70_80". */
  taxonomy_path?: string;
}

export interface RibbonStats {
  min: number | null;
  max: number | null;
  mean: number | null;
  median: number | null;
}

export interface RibbonProvider extends RibbonStats {
  provider: string;
  rates: number;
  products: number;
}

export interface Ribbon {
  counts: { rates: number; products: number; providers: number };
  range: RibbonStats;
  providers: RibbonProvider[];
}

export interface SectionData {
  rates: RateRow[];
  ribbon: Ribbon;
}

export interface Brand {
  short: string;
  color: string;
  /** Offline-capable canonical logo embedded by the release payload. */
  logo?: string;
  /** CDR Register logoUri (regulator-maintained) for brands without embedded art. */
  logo_uri?: string;
  /** Register logoUri in SVG form — rendered via react-native-svg, not <Image>. */
  logo_svg_uri?: string;
}

export interface RbaEntry {
  date: string;
  rate: number;
}

export interface CorePayload {
  schema_version: number;
  run_date: string;
  sections: Record<SectionKey, SectionData>;
  brands: Record<string, Brand>;
  rba: RbaEntry[];
  /** RBA meeting dates that left the cash-rate target unchanged (holds). */
  rba_holds?: string[];
  /** Optional producer-measured ingest coverage; absent on older payloads. */
  coverage?: PayloadCoverage;
}

export interface CoverageFailure {
  provider: string;
  reason?: string;
  phase?: string;
  status?: string;
  count?: number;
}

export interface PayloadCoverage {
  /** Producer's exhaustive source-to-published exclusions; verified by app health. */
  payload_accounting?: unknown;
  schema_version?: number;
  /** Canonical producer observation date. */
  observed_on?: string;
  /** Backward-compatible timestamp alias. */
  observed_at?: string;
  providers_attempted?: number;
  providers_succeeded?: number;
  /** Canonical producer failure groups. */
  provider_failures?: CoverageFailure[];
  /** Backward-compatible failure alias. */
  failures?: CoverageFailure[];
  counts?: {
    brands_observed?: number;
    providers_failed?: number;
    providers_partial?: number;
    products?: number;
    rates?: number;
    failure_records?: number;
  };
  limitations?: string[];
}

export interface FeeAmountRange {
  feeMinimum?: string | number;
  feeMaximum?: string | number;
}

export interface FeeRateBased {
  rateType?: string;
  rate?: string | number;
  accrualFrequency?: string;
  amountRange?: FeeAmountRange;
}

export interface FeeDiscountEligibility {
  discountEligibilityType?: string;
  additionalValue?: string | number;
  additionalInfo?: string;
}

export interface FeeDiscount {
  description?: string;
  discountType?: string;
  amount?: string | number;
  balanceRate?: string | number;
  feeRate?: string | number;
  transactionRate?: string | number;
  accruedRate?: string | number;
  additionalValue?: string | number;
  additionalInfo?: string;
  fixedAmount?: { amount?: string | number };
  rateBased?: FeeRateBased;
  eligibility?: FeeDiscountEligibility[];
}

export interface DetailItem {
    label?: string;
    name?: string;
    value?: string | number;
    info?: string;
    /** Structured CDR fee evidence. Additive so older cached payloads remain valid. */
    amountStatus?: 'fixed' | 'variable' | 'rate' | 'unpublished';
    amount?: string | number;
    currency?: string;
    additionalValue?: string | number;
    balanceRate?: string | number;
    transactionRate?: string | number;
    accruedRate?: string | number;
    accrualFrequency?: string;
    feeCap?: string | number;
    feeCapPeriod?: string;
    feeMethodUType?: string;
    fixedAmount?: { amount?: string | number };
    variable?: FeeAmountRange;
    rateBased?: FeeRateBased;
    discounts?: FeeDiscount[];
  }

export type NormalizedProductFactKind =
  | 'fee'
  | 'rate'
  | 'tier'
  | 'bundle'
  | 'attribute'
  | 'feature'
  | 'eligibility'
  | 'constraint'
  | 'condition';

export type NormalizedProductFactUnit =
  | 'AUD'
  | 'fraction'
  | 'duration'
  | 'day'
  | 'month'
  | 'year'
  | 'count'
  | 'boolean'
  | 'text'
  | 'enum'
  /** Other ISO 4217 currency codes, for example USD. */
  | (string & {});

/** Lossless, source-stable product fact emitted by the payload producer. */
export interface NormalizedProductFact {
  id: string;
  /** Stable semantic association without exposing a raw source/object path. */
  groupId?: string;
  /** Parent fact id for tier/condition/discount relationships. */
  parentId?: string;
  kind: NormalizedProductFactKind;
  canonicalKey: string;
  /** Concise customer-facing name; preferred over a humanized canonical key. */
  label?: string;
  /** Original CDR enum, when one exists. Never free-form producer commentary. */
  sourceType?: string;
  value?: string | number | boolean;
  minValue?: string | number;
  maxValue?: string | number;
  unit?: NormalizedProductFactUnit;
  /** ISO-8601 duration, for example P1M. */
  cadence?: string;
  appliesTo?: string[];
  /** Customer-facing source condition; distinct conditions remain distinct facts. */
  condition?: string;
  /** Curated aliases only; descriptions and URLs are excluded by contract. */
  searchTerms?: string[];
}

/** Authoritative lender document URIs (CDR additionalInformation). */
export interface ProductLinks {
  overview?: string;
  eligibility?: string;
  fees?: string;
  terms?: string;
  bundle?: string;
}

export interface ProductDetail {
  displayIdentity?: { name?: string; provider?: string; productCategory?: string };
  /** Original per-rate wording; optional on older immutable payloads. */
  rateConditions?: RateConditions;
  description?: string;
  last_updated?: string;
  fees?: DetailItem[];
  features?: DetailItem[];
  eligibility?: DetailItem[];
  constraints?: DetailItem[];
  /** Additive normalized facts; legacy arrays remain supported for old payloads. */
  facts?: NormalizedProductFact[];
  /** Links to the lender's official overview / eligibility / fees / terms pages. */
  links?: ProductLinks;
  /** Original references retained before generic URL cleaning. */
  sourceDocuments?: { url: string; sourceUrl?: string; sourcePath: string; relation: string; label?: string }[];
}

export interface RateConditions {
  schemaVersion: 1;
  sourceSha256: string;
  entries: RateConditionEntry[];
}
export interface RateConditionEntry {
  id: string; rateFamily: 'deposit' | 'lending'; rateIndex: number;
  rateSourcePointer: string; tierSourcePointer?: string; sourcePointer: string; text: string;
}

export interface DetailsPayload {
  schema_version: number;
  run_date: string;
  products: Record<string, ProductDetail>;
}

/** Present when the asset is AES-256-GCM encrypted (docs/SECURITY_CDR_PIPELINE.md). */
export interface ManifestEnc {
  alg: string;
  key_id: string;
}

export interface ManifestFile {
  name: string;
  bytes: number;
  sha256: string;
  url: string;
  enc?: ManifestEnc;
}

export interface Manifest {
  executable_v3?: import('./data/monetaryContracts/types').MonetaryNamespace;
  /** Optional lazy capability descriptors; deliberately outside legacy eager files. */
  executable_v2?: { schema_version: 2; index: { name: string; bytes: number; sha256: string }; shards: Record<string, { name: string; bytes: number; sha256: string }> };
  source_observation?: { generation_id?: string; contract_digest?: string; [key: string]: unknown };
  payload_revision?: {
    schema_version: 1;
    revision: number;
    generation_id: string;
    bundle_sha256: string;
    parent_revision: number | null;
  };
  schema_version: number;
  run_date: string;
  generated_at: string;
  app_min_version: string;
  repo: string;
  tag: string;
  counts: Record<string, number>;
  schedule: { label: string; next_due_utc?: string };
  files: {
    core: ManifestFile;
    details: ManifestFile;
    search_index?: ManifestFile;
    history_banks?: ManifestFile;
    /** Per-bank daily series + rate-move events (bank intelligence asset). */
    bank_history?: ManifestFile;
    /** Variable-mortgage minus at-call-savings provider mean history. */
    bank_spread_history?: ManifestFile;
    /** RBA decision calendar + forward meeting schedule (countdown asset). */
    rba_calendar?: ManifestFile;
    /** Lazy immutable per-product document evidence index. */
    terms_index?: ManifestFile;
  };
  enc?: ManifestEnc;
}

export type PayloadSource = 'sample' | 'cache' | 'remote';

export type HistoryWindow = '30D' | '90D' | '1Y' | 'All';

export interface BankHistoryPoint {
  date: string;
  min: number | null;
  max: number | null;
  mean: number | null;
  median: number | null;
  count?: number;
}

/** Chart model passed to BankHistoryChart (dashboard bank-history parity). */
export interface BankHistoryChartModel {
  dates: string[];
  points: BankHistoryPoint[];
  section: SectionKey;
  allDates?: string[];
}

/**
 * Pi `/api/banks/history/section` cache — populated by the history-cache agent.
 * Rates carry `run_date` for the time axis.
 */
export interface BankHistoryCache {
  run_dates: string[];
  rates: (RateRow & { run_date?: string })[];
  section?: SectionKey;
  carry_forward_count?: number;
  current_only?: boolean;
}
