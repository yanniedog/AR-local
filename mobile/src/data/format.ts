import type { RateRow } from '../types';
import { isKnownNonStandardProduct } from './accountClass';

/** Parse a rate that may be a normalized fraction ("0.0634") or a raw percent ("6.34"). */
export function toFraction(rate: string | number | null | undefined): number | null {
  if (rate === null || rate === undefined || rate === '') return null;
  const n = typeof rate === 'number' ? rate : Number(rate);
  if (!isFinite(n) || n <= 0) return null;
  return n > 1 ? n / 100 : n;
}

function ratePercentFormatter(digits: number): Intl.NumberFormat {
  return new Intl.NumberFormat('en-AU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Format a fraction (0.0634) or percent (6.34) as an en-AU percentage string ("6.34%"). */
export function formatRate(rate: string | number | null | undefined, digits = 2): string {
  const f = toFraction(rate);
  if (f === null) return '—';
  return `${ratePercentFormatter(digits).format(f * 100)}%`;
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
  OFFSET: 'Mortgage offset',
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
function isoDurationMonths(term: string | undefined): number | null {
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

export function visibleAccountRows(rows: RateRow[], includeNonStandard = false): RateRow[] {
  return includeNonStandard ? rows : rows.filter((row) => !isNonStandard(row));
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
