import { SECTIONS } from '../constants';
import type { RateRow, SectionKey } from '../types';
import { isNonStandard, toFraction } from './format';

// The Pi packages a dot-delimited `taxonomy_path` per rate row, e.g.
//   HOME_LOAN.OO.PI.VARIABLE.LVR_70_80
//   SAVINGS.SAVINGS_ACCT.BONUS.TIERED
//   TERM_DEPOSIT.12M.AT_MATURITY.TIERED
// This module turns those into the AR-local dashboard's drill-down hierarchy.

export const ROOT: Record<SectionKey, string> = {
  Mortgage: 'HOME_LOAN',
  Savings: 'SAVINGS',
  TD: 'TERM_DEPOSIT',
};

const LABELS: Record<string, string> = {
  HOME_LOAN: 'Home loans',
  OO: 'Owner-occupied',
  INV: 'Investor',
  PI: 'Principal & interest',
  IO: 'Interest only',
  VARIABLE: 'Variable rate',
  FIXED: 'Fixed rate',
  SAVINGS: 'Savings',
  SAVINGS_ACCT: 'Savings account',
  AT_CALL: 'At-call',
  BASE: 'Base rate',
  BONUS: 'Bonus rate',
  INTRO: 'Introductory',
  FLAT: 'Flat rate',
  TIERED: 'Tiered balance',
  TERM_DEPOSIT: 'Term deposit',
  AT_MATURITY: 'Paid at maturity',
  MONTHLY: 'Paid monthly',
  QUARTERLY: 'Paid quarterly',
  SEMI_ANNUALLY: 'Paid semi-annually',
  ANNUALLY: 'Paid annually',
  WEEKLY: 'Paid weekly',
  DAILY: 'Paid daily',
  OTHER: 'Other',
};

// Canonical ordering per segment family (mirrors the dashboard ribbon's tier order).
const ORDER: Record<string, number> = {
  OO: 0, INV: 1,
  PI: 0, IO: 1,
  VARIABLE: 0, FIXED: 1,
  AT_CALL: 0, SAVINGS_ACCT: 1,
  BASE: 0, BONUS: 1, INTRO: 2,
  FLAT: 0, TIERED: 1,
  AT_MATURITY: 0, MONTHLY: 1, QUARTERLY: 2, SEMI_ANNUALLY: 3, ANNUALLY: 4,
};

function months(seg: string): number | null {
  const m = /^(\d+)M$/.exec(seg);
  return m ? Number(m[1]) : null;
}

function lvrLabel(seg: string): string {
  const v = seg.replace(/^LVR_/, '');
  if (v === 'LE60') return '≤60% LVR';
  if (v === 'UNSPECIFIED' || v === 'NA') return 'LVR n/a';
  let m = /^(\d+)_(\d+)$/.exec(v);
  if (m) return `${m[1]}–${m[2]}% LVR`;
  m = /^GT?(\d+)$/.exec(v);
  if (m) return `${m[1]}%+ LVR`;
  m = /^(\d+)$/.exec(v);
  if (m) return `≤${m[1]}% LVR`;
  return `${v} LVR`;
}

/** Human label for a single taxonomy segment. */
export function segLabel(seg: string): string {
  if (!seg) return 'Other';
  if (LABELS[seg]) return LABELS[seg];
  if (seg.startsWith('LVR_')) return lvrLabel(seg);
  const mo = months(seg);
  if (mo !== null) {
    if (mo % 12 === 0) {
      const y = mo / 12;
      return `${y} year${y > 1 ? 's' : ''}`;
    }
    return `${mo} months`;
  }
  return seg.charAt(0) + seg.slice(1).toLowerCase().replace(/_/g, ' ');
}

function pathSegs(tp: string | undefined): string[] {
  return (tp ?? '').split('.').filter(Boolean);
}

export interface RateStats {
  min: number | null;
  max: number | null;
  mean: number | null;
  median: number | null;
  count: number;
  providers: number;
}

export function statsFor(rows: RateRow[], includeNonStandard = false): RateStats {
  const fractions: number[] = [];
  const providers = new Set<string>();
  for (const r of rows) {
    if (!includeNonStandard && isNonStandard(r)) continue;
    const f = toFraction(r.rate);
    if (f === null) continue;
    fractions.push(f);
    providers.add(r.provider);
  }
  if (!fractions.length) {
    return { min: null, max: null, mean: null, median: null, count: 0, providers: 0 };
  }
  fractions.sort((a, b) => a - b);
  const n = fractions.length;
  const mid = n >> 1;
  return {
    min: fractions[0],
    max: fractions[n - 1],
    mean: fractions.reduce((s, x) => s + x, 0) / n,
    median: n % 2 ? fractions[mid] : (fractions[mid - 1] + fractions[mid]) / 2,
    count: n,
    providers: providers.size,
  };
}

/** Rows whose taxonomy_path sits at or below `path` (segments under the section root). */
export function rowsUnder(rows: RateRow[], section: SectionKey, path: string[]): RateRow[] {
  const root = ROOT[section];
  return rows.filter((r) => {
    const segs = pathSegs(r.taxonomy_path);
    if (segs[0] !== root) return path.length === 0; // untyped rows live under the root only
    for (let i = 0; i < path.length; i++) {
      if (segs[i + 1] !== path[i]) return false;
    }
    return true;
  });
}

export interface TaxoNode {
  seg: string;
  label: string;
  rows: RateRow[];
  stats: RateStats;
  hasChildren: boolean;
}

function compareSeg(a: string, b: string, section: SectionKey): number {
  const ma = months(a);
  const mb = months(b);
  if (ma !== null && mb !== null) return ma - mb;
  if (a.startsWith('LVR_') && b.startsWith('LVR_')) {
    // Sort by the first digit run, so LE60 / 70_80 / GT95 all order correctly.
    const da = /(\d+)/.exec(a);
    const db = /(\d+)/.exec(b);
    return (da ? parseInt(da[1], 10) : 0) - (db ? parseInt(db[1], 10) : 0);
  }
  const oa = ORDER[a];
  const ob = ORDER[b];
  if (oa !== undefined && ob !== undefined) return oa - ob;
  if (oa !== undefined) return -1;
  if (ob !== undefined) return 1;
  return segLabel(a).localeCompare(segLabel(b));
}

/** Child nodes one level below `path` (grouped by the next taxonomy segment). */
export function childrenOf(rows: RateRow[], section: SectionKey, path: string[]): TaxoNode[] {
  const root = ROOT[section];
  const depth = path.length + 1; // index of the "next" segment in the full path
  const buckets = new Map<string, RateRow[]>();
  for (const r of rowsUnder(rows, section, path)) {
    const segs = pathSegs(r.taxonomy_path);
    if (segs[0] !== root) continue;
    const next = segs[depth];
    if (next === undefined) continue; // row terminates at this node (a leaf product)
    if (!buckets.has(next)) buckets.set(next, []);
    buckets.get(next)!.push(r);
  }
  const nodes: TaxoNode[] = [];
  for (const [seg, segRows] of buckets) {
    nodes.push({
      seg,
      label: segLabel(seg),
      rows: segRows,
      stats: statsFor(segRows),
      hasChildren: childHasDeeper(segRows, root, depth),
    });
  }
  nodes.sort((a, b) => compareSeg(a.seg, b.seg, section));
  return nodes;
}

function childHasDeeper(rows: RateRow[], root: string, depth: number): boolean {
  for (const r of rows) {
    const segs = pathSegs(r.taxonomy_path);
    if (segs[0] === root && segs[depth + 1] !== undefined) return true;
  }
  return false;
}

/** Products that terminate exactly at `path` (no deeper taxonomy). */
export function leafProducts(rows: RateRow[], section: SectionKey, path: string[]): RateRow[] {
  const root = ROOT[section];
  const full = path.length + 1;
  return rowsUnder(rows, section, path).filter((r) => {
    const segs = pathSegs(r.taxonomy_path);
    return segs[0] === root && segs.length <= full;
  });
}

/** Breadcrumb labels for a path under a section. */
export function breadcrumb(section: SectionKey, path: string[]): string[] {
  return [SECTIONS[section].title, ...path.map(segLabel)];
}
