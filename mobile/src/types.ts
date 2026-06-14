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
}

export interface DetailItem {
  label?: string;
  name?: string;
  value?: string | number;
  info?: string;
}

export interface ProductDetail {
  description?: string;
  last_updated?: string;
  fees?: DetailItem[];
  features?: DetailItem[];
  eligibility?: DetailItem[];
  constraints?: DetailItem[];
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
  rates: Array<RateRow & { run_date?: string }>;
  section?: SectionKey;
  carry_forward_count?: number;
  current_only?: boolean;
}
