import type { ProductDetail, RateRow } from '../types';
import { isKnownNonStandardProduct } from './accountClass';
import { accessExcludesFromStandard, assessAccess } from './access';
import { getSuitabilityAllowed } from './suitabilityGate';

/** Parse a rate that may be a normalized fraction ("0.0634") or a raw percent ("6.34"). */
export function toFraction(rate: string | number | null | undefined): number | null {
  if (rate === null || rate === undefined || (typeof rate === 'string' && !rate.trim())) return null;
  const n = typeof rate === 'number' ? rate : Number(rate);
  if (!isFinite(n) || n < 0) return null;
  return n > 1 ? n / 100 : n;
}

/**
 * The metric every ranking/aggregation should use: the comparison rate (which
 * folds in fees and is the honest cost of a loan) when the row publishes a valid
 * one, else the headline rate. Deposits carry no comparison rate, so this is a
 * no-op for them. Keeping this in one place is what makes "comparison rate is the
 * default metric for all calculations" true everywhere rather than per-call.
 */
export function effectiveRate(
  row: { rate: string | number; comparison_rate?: string | number } | null | undefined,
): string | number | undefined {
  if (!row) return undefined;
  return toFraction(row.comparison_rate) !== null ? row.comparison_rate : row.rate;
}

/** {@link effectiveRate} parsed to a fraction (null when neither rate is usable). */
export function effectiveFraction(
  row: { rate: string | number; comparison_rate?: string | number } | null | undefined,
): number | null {
  return toFraction(effectiveRate(row));
}

const RATE_PERCENT_FORMATTERS = new Map<number, Intl.NumberFormat>();

function normalizedFractionDigits(digits: number): number {
  if (!Number.isFinite(digits)) return 2;
  // Intl.NumberFormat's integer option coercion floors fractional values.
  // Preserve that behaviour while avoiding RangeErrors for out-of-range input.
  return Math.max(0, Math.min(20, Math.floor(digits)));
}

function ratePercentFormatter(digits: number): Intl.NumberFormat {
  const normalized = normalizedFractionDigits(digits);
  let formatter = RATE_PERCENT_FORMATTERS.get(normalized);
  if (!formatter) {
    formatter = new Intl.NumberFormat('en-AU', {
      minimumFractionDigits: normalized,
      maximumFractionDigits: normalized,
    });
    RATE_PERCENT_FORMATTERS.set(normalized, formatter);
  }
  return formatter;
}

/** Format a fraction (0.0634) or percent (6.34) as an en-AU percentage string ("6.34%"). */
export function formatRate(rate: string | number | null | undefined, digits = 2): string {
  const f = toFraction(rate);
  if (f === null) return '—';
  return `${ratePercentFormatter(digits).format(f * 100)}%`;
}

/**
 * Format an already-ranked rate fraction as a percent.
 * Unlike {@link formatRate}/{@link toFraction}, a published 0% ranks as 0 and
 * must render as "0.00%" rather than the missing-rate em dash.
 */
export function formatRankedFraction(fraction: number | null | undefined, digits = 2): string {
  if (fraction === null || fraction === undefined || !isFinite(fraction) || fraction < 0) return '—';
  return `${ratePercentFormatter(digits).format(fraction * 100)}%`;
}

/** Percent digits only (no suffix) — chart axis labels. */
export function formatRateDigits(rate: string | number | null | undefined, digits = 2): string {
  const f = toFraction(rate);
  if (f === null) return '—';
  return ratePercentFormatter(digits).format(f * 100);
}

export function ratePercentValue(rate: string | number | null | undefined): number | null {
  const f = toFraction(rate);
  return f === null ? null : f * 100;
}

/** Difference between two fractions expressed in basis points. */
export function bpsBetween(a: number | null, b: number | null): number | null {
  if (a === null || b === null) return null;
  return Math.round((a - b) * 10000);
}

const ACRONYMS = new Set(['LVR', 'TD', 'PI', 'IO', 'FX', 'SMSF', 'P&I']);

const ENUM_LABEL_OVERRIDES: Record<string, string> = {
  OFFSET: 'Offset account',
  EXTRA_REPAYMENTS: 'Early / extra repayments',
  REDRAW: 'Redraw facility',
  GUARANTOR: 'Guarantor option',
  CASHBACK_OFFER: 'Cashback offer',
  NPP_PAYID: 'PayID',
  UNLIMITED_TXNS: 'Unlimited transactions',
  FREE_TXNS: 'Free transactions',
  BILL_PAYMENT: 'Bill payment',
  CARD_ACCESS: 'Card access',
  DIGITAL_BANKING: 'Digital banking',
};

/** Humanize a CDR enum like "PRINCIPAL_AND_INTEREST" -> "Principal & interest". */
export function humanizeEnum(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '';
  const raw = String(value).trim();
  if (!raw) return '';
  const override = ENUM_LABEL_OVERRIDES[raw.toUpperCase()];
  if (override) return override;
  const withAmp = raw.replace(/_AND_/gi, ' & ');
  const words = withAmp.replace(/_/g, ' ').toLowerCase().split(/\s+/);
  return words
    .map((w, i) => {
      const upper = w.toUpperCase();
      if (ACRONYMS.has(upper)) return upper;
      if (w === '&') return '&';
      return i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w;
    })
    .join(' ');
}

/** Case-insensitive sort by display label (defaults to humanizeEnum). */
export function sortByDisplayLabel(
  values: string[],
  labelOf: (value: string) => string = humanizeEnum,
): string[] {
  return [...values].sort((a, b) => {
    const byLabel = labelOf(a).localeCompare(labelOf(b), undefined, {
      sensitivity: 'base',
      numeric: true,
    });
    return byLabel !== 0 ? byLabel : a.localeCompare(b, undefined, { sensitivity: 'base' });
  });
}

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return isFinite(n) ? n : null;
}

export function formatMoneyShort(value: string | number | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return '';
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}m`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(n % 1_000 ? 1 : 0)}k`;
  return `$${n.toLocaleString()}`;
}

export function formatBalanceRange(
  min: string | number | null | undefined,
  max: string | number | null | undefined,
): string {
  const lo = toNumber(min);
  const hi = toNumber(max);
  if (lo === null && hi === null) return '';
  if (lo !== null && hi !== null) return `${formatMoneyShort(lo)}–${formatMoneyShort(hi)}`;
  if (lo !== null) return `${formatMoneyShort(lo)}+`;
  return `Up to ${formatMoneyShort(hi)}`;
}

/** Parse an ISO-8601 duration like "P3Y", "P36M", "P1Y6M" to a month count. */
export function isoDurationMonths(term: string | undefined): number | null {
  if (typeof term !== 'string') return null;
  const m = /^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?$/.exec(term.trim());
  if (!m || (!m[1] && !m[2])) return null;
  const months = Number(m[1] ?? 0) * 12 + Number(m[2] ?? 0);
  return months > 0 ? months : null;
}

export function formatTerm(row: RateRow): string {
  // term_months is authoritative; otherwise parse the ISO `term` (e.g. "P36M" = 3 yrs).
  // NB: ribbon_fixed_term only mirrors the *number* in `term` (P3Y→3, P36M→36), so its
  // unit is ambiguous on its own — only fall back to it (as years) when nothing else.
  let months = toNumber(row.term_months);
  if (months === null || months <= 0) {
    months = isoDurationMonths(typeof row.term === 'string' ? row.term : undefined);
  }
  if (months !== null && months > 0) {
    if (months % 12 === 0) {
      const years = months / 12;
      return `${years} yr${years > 1 ? 's' : ''}`;
    }
    return `${months} mo`;
  }
  const fixed = toNumber(row.ribbon_fixed_term);
  if (fixed !== null && fixed > 0) return `${fixed} yr${fixed > 1 ? 's' : ''} fixed`;
  return '';
}

export function isNonStandard(row: RateRow): boolean {
  if ((row.account_class ?? '') === 'non_standard') return true;
  return isKnownNonStandardProduct(row);
}

/**
 * Whether a deposit row's advertised rate depends on bonus actions or an
 * introductory window. These remain available in the opt-in full catalogue,
 * but are not unconditional rates that broadly apply without further steps.
 */
export function isConditionalDepositRate(row: RateRow): boolean {
  const depositKind = (row.ribbon_deposit_kind ?? '').toLowerCase().trim();
  const rateStructure = (row.ribbon_rate_structure ?? '').toLowerCase().trim();
  if (depositKind === 'bonus' || depositKind === 'introductory' || depositKind === 'intro') {
    return true;
  }
  if (rateStructure === 'bonus' || rateStructure === 'introductory' || rateStructure === 'intro') {
    return true;
  }
  const pathTokens = (row.taxonomy_path ?? '').toUpperCase().split('.');
  return pathTokens.some(
    (token) => token === 'BONUS' || token === 'INTRO' || token === 'INTRODUCTORY',
  );
}

/**
 * The unified default-suitability gate. A product is shown to ordinary users by
 * default only when it is *broadly available*: not a non-standard account class,
 * not a curated non-standard cohort, not a conditional bonus/introductory rate,
 * and not access-restricted (youth, region, staff, occupation, membership,
 * business, student, pension, package/existing-customer gates — via product
 * name, lender brand, or loaded eligibility).
 * Product-structure dimensions (LVR, deposit size, TD term, OO/investor, fixed/
 * variable) are allowed. Advanced users opt everything back in via the
 * "Broadly applicable products" setting (`includeNonStandard`). This is the ONE
 * predicate every surface must use; it shares {@link assessAccess} with the
 * orange restricted badge so badge and filter never disagree.
 */
export function isBroadlyAvailable(
  row: RateRow | null | undefined,
  detail?: ProductDetail | null,
): boolean {
  if (!row) return false;
  if (isNonStandard(row)) return false;
  if (isConditionalDepositRate(row)) return false;
  const access = assessAccess(row.product_name, detail ?? null, row.provider);
  if (accessExcludesFromStandard(access)) return false;
  return true;
}

export function visibleAccountRows(
  rows: RateRow[],
  includeNonStandard = false,
  detailsProducts?: Record<string, ProductDetail> | null,
): RateRow[] {
  if (includeNonStandard) return rows;
  // Prefer the one-shot post-ingest index so Browse/Home/Search stay O(1) after
  // details warm. Fall back to per-row assessAccess before the index exists.
  const allowed = getSuitabilityAllowed();
  if (allowed) {
    // The suitability index is product-key based. Recheck row-level rate
    // restrictions so an allowed sibling cannot admit a non-standard or
    // conditional variant of the same product.
    return rows.filter(
      (row) => allowed.has(row.product_key) && !isNonStandard(row) && !isConditionalDepositRate(row),
    );
  }
  return rows.filter((row) => isBroadlyAvailable(row, detailsProducts?.[row.product_key] ?? null));
}

/** Short, friendly "Updated 3 days ago" / "Updated today". */
export function relativeDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (isNaN(then)) return '';
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months} mo ago`;
  return `${Math.round(months / 12)} yr ago`;
}

export function formatRunDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(`${iso}T00:00:00Z`);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

/**
 * Calendar-day-safe label for an observed rate change.
 * Recent observations are relative; older ones use an exact date.
 */
export function formatRateChangeDate(
  iso: string | null | undefined,
  now: Date = new Date(),
): string {
  const ymd = String(iso || '').slice(0, 10);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  if (!match) return '';
  const observedDay = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.floor((today - observedDay) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days} days ago`;
  return new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  ).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}
