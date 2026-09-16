import { Decimal, decimalZero } from './decimal';
import type { SavingsAssessment } from './savingsTypes';
import type { SavingsActivityEvent, SavingsActivityMetric, SavingsActivityResult } from './savingsActivityTypes';
import type { Facts } from './types';

function metricResult(a: SavingsAssessment, m: SavingsActivityMetric): SavingsActivityResult {
  const result: SavingsActivityResult = { metricId: m.id, field: m.field, status: 'unknown', fact: null, reason: null, evidenceIds: m.evidenceIds };
  const unavailable = (reason: string) => ({ ...result, reason });
  const data = a.activity;
  if (!data || a.coverage !== 'complete' || !m.accountIds.every(id => data.coverage.some(c => c.accountId === id && c.status === 'complete' && c.from <= a.from && c.toExclusive >= a.toExclusive))) return unavailable('activity_coverage_unknown');
  const events: SavingsActivityEvent[] = [];
  for (const e of data.events) {
    if (!m.accountIds.includes(e.accountId)) continue;
    // Dates on the wrong basis cannot prove whether a transaction belongs to this window.
    if (e.dateBasis !== m.dateBasis) return unavailable('activity_date_basis_unknown');
    if (e.date < a.from || e.date >= a.toExclusive) continue;
    if (e.status === 'unknown') return unavailable('activity_classification_unknown');
    if (m.settlement === 'settled_only' && e.status === 'pending') continue;
    if (e.kind === 'unknown') return unavailable('activity_classification_unknown');
    events.push(e);
  }
  let value = decimalZero();
  if (m.kind === 'balance_growth') {
    if (!m.growthAdjustments) return unavailable('growth_basis_unknown');
    for (const id of m.accountIds) {
      const balance = data.balances.find(b => b.accountId === id && b.from === a.from && b.toExclusive === a.toExclusive);
      if (!balance) return unavailable('growth_basis_unknown');
      value = value.add(Decimal.parse(balance.closing).sub(Decimal.parse(balance.opening)));
    }
    for (const e of events) {
      if (!['interest', 'fee', 'tax'].includes(e.kind)) continue;
      if (m.growthAdjustments[e.kind as 'interest' | 'fee' | 'tax'] === 'exclude') {
        const amount = Decimal.parse(e.amount);
        value = e.kind === 'interest' ? value.sub(amount) : value.add(amount);
      }
    }
  } else {
    const kind = m.kind === 'deposit_total' ? 'deposit' : m.kind === 'purchase_count' ? 'purchase' : 'withdrawal';
    const included: SavingsActivityEvent[] = [];
    for (const e of events.filter(e => e.kind === kind)) {
      if (e.classification === null) return unavailable('activity_classification_unknown');
      if (m.includedClassifications.includes(e.classification)) included.push(e);
      else if (!m.excludedClassifications.includes(e.classification)) return unavailable('activity_classification_unknown');
    }
    const refunded = new Set<string>();
    if (m.kind === 'purchase_count') {
      const refunds = events.filter(e => e.kind === 'refund');
      if (refunds.length && m.refundPolicy === null) return unavailable('refund_policy_unknown');
      if (m.refundPolicy === 'exclude_refunded_purchase') {
        for (const refund of refunds) {
          if (!refund.originalPurchaseId || !included.some(e => e.id === refund.originalPurchaseId && e.accountId === refund.accountId)) return unavailable('refund_purchase_scope_unknown');
          refunded.add(refund.originalPurchaseId);
        }
      }
    }
    for (const e of included) {
      if (!refunded.has(e.id)) value = value.add(m.kind === 'deposit_total' ? Decimal.parse(e.amount) : Decimal.parse('1'));
    }
  }
  return { ...result, status: 'known', fact: { type: 'decimal', value: value.fixed(m.kind.endsWith('_count') ? 0 : 2), unit: m.kind.endsWith('_count') ? 'count' : 'AUD' } };
}

/** Generated metric fields replace caller-supplied aggregates, including on unknown results. */
export function assessSavingsActivity(assessment: SavingsAssessment, metrics: SavingsActivityMetric[]): { facts: Facts; results: SavingsActivityResult[] } {
  const facts: Facts = { ...assessment.facts };
  const results = metrics.map(m => metricResult(assessment, m));
  for (const result of results) {
    delete facts[result.field];
    if (result.status === 'known' && result.fact) facts[result.field] = result.fact;
  }
  return { facts, results };
}
