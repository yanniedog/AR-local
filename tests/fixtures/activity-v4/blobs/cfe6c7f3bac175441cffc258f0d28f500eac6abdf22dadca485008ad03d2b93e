import { dayNumber } from './calendar';
import { Decimal, decimalZero } from './decimal';
import type { SavingsActivityData, SavingsActivityMetric } from './savingsActivityTypes';

const identifier = (v: string) => typeof v === 'string' && /^[A-Za-z][A-Za-z0-9_.:-]{0,179}$/.test(v) && !['constructor', 'prototype', '__proto__'].includes(v);
const account = (v: string) => typeof v === 'string' && v.trim().length > 0 && v.length <= 300;
const money = (v: string) => {
  const n = Decimal.parse(v);
  if (n.compare(decimalZero()) < 0 || n.compare(n.rounded(2, 'toward_zero')) !== 0) throw new Error('activity_amount_invalid');
};
export function validateActivityMetrics(metrics: SavingsActivityMetric[], refs: (ids: string[]) => void): void {
  if (!Array.isArray(metrics) || !metrics.length || metrics.length > 16) throw new Error('activity_metric_limit');
  const ids = new Set<string>(), fields = new Set<string>();
  for (const m of metrics) {
    if (!identifier(m.id) || ids.has(m.id) || !identifier(m.field) || fields.has(m.field) || !identifier(m.accountRole) ||
        !Array.isArray(m.accountIds) || !m.accountIds.length || m.accountIds.length > 16 || m.accountIds.some(id => !account(id)) || new Set(m.accountIds).size !== m.accountIds.length ||
        !['deposit_total', 'withdrawal_count', 'purchase_count', 'balance_growth'].includes(m.kind) ||
        !['processed', 'transaction'].includes(m.dateBasis) || !['settled_only', 'include_pending'].includes(m.settlement) ||
        ![null, 'ignore', 'exclude_refunded_purchase'].includes(m.refundPolicy)) throw new Error('activity_policy_unsupported');
    ids.add(m.id); fields.add(m.field); refs(m.evidenceIds);
    if (!Array.isArray(m.includedClassifications) || !Array.isArray(m.excludedClassifications) ||
        m.includedClassifications.length + m.excludedClassifications.length > 128) throw new Error('activity_classifications_invalid');
    const all = [...m.includedClassifications, ...m.excludedClassifications];
    if (all.some(c => typeof c !== 'string' || !c || c.length > 100) || new Set(all).size !== all.length || (m.kind !== 'balance_growth' && !m.includedClassifications.length)) throw new Error('activity_classifications_invalid');
    if (m.kind === 'balance_growth' && (!m.growthAdjustments || !['interest', 'fee', 'tax'].every(k => ['include', 'exclude'].includes(m.growthAdjustments![k as 'interest' | 'fee' | 'tax'])))) throw new Error('growth_adjustments_unknown');
  }
}
export function validateActivityData(data: SavingsActivityData): void {
  if (!data || !Array.isArray(data.events) || data.events.length > 10_000 || !Array.isArray(data.coverage) || data.coverage.length > 64 ||
      !Array.isArray(data.balances) || data.balances.length > 64) throw new Error('activity_data_limit');
  const ids = new Set<string>();
  for (const e of data.events) {
    if (!identifier(e.id) || ids.has(e.id) || !account(e.accountId) || !['processed', 'transaction'].includes(e.dateBasis) ||
        !['settled', 'pending', 'unknown'].includes(e.status) || !['deposit', 'withdrawal', 'purchase', 'refund', 'interest', 'fee', 'tax', 'unknown'].includes(e.kind) ||
        (e.classification !== null && (typeof e.classification !== 'string' || e.classification.length > 100))) throw new Error('activity_event_invalid');
    ids.add(e.id); dayNumber(e.date); money(e.amount);
  }
  const coverageIds = new Set<string>(), balanceIds = new Set<string>();
  const intervals = new Map<string, { from: number; to: number }[]>();
  function interval(kind: string, accountId: string, from: string, to: string): void {
    const key = JSON.stringify([kind, accountId]), start = dayNumber(from), end = dayNumber(to);
    const prior = intervals.get(key) ?? [];
    if (prior.some(p => start < p.to && end > p.from)) throw new Error('activity_interval_overlap');
    prior.push({ from: start, to: end }); intervals.set(key, prior);
  }
  for (const c of data.coverage) {
    const id = JSON.stringify([c.accountId, c.from, c.toExclusive]);
    if (!account(c.accountId) || coverageIds.has(id) || !['complete', 'unknown'].includes(c.status) || dayNumber(c.toExclusive) <= dayNumber(c.from)) throw new Error('activity_coverage_invalid');
    interval('coverage', c.accountId, c.from, c.toExclusive);
    coverageIds.add(id);
  }
  for (const b of data.balances) {
    const id = JSON.stringify([b.accountId, b.from, b.toExclusive]);
    if (!account(b.accountId) || balanceIds.has(id) || dayNumber(b.toExclusive) <= dayNumber(b.from)) throw new Error('activity_balances_invalid');
    interval('balance', b.accountId, b.from, b.toExclusive);
    balanceIds.add(id); money(b.opening); money(b.closing);
  }
}
