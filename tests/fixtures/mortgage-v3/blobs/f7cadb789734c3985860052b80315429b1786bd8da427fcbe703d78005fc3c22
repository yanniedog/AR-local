import { dayNumber } from './calendar';
import { Decimal, decimalZero } from './decimal';
import type { LedgerContract, LedgerScenario, Rule } from './types';
import { validateActivityData, validateActivityMetrics } from './savingsActivityValidation';
function ruleWeight(rule: Rule): number {
  return 1 + (rule.op === 'and' || rule.op === 'or' ? rule.rules.reduce((sum, r) => sum + ruleWeight(r), 0) : rule.op === 'not' ? ruleWeight(rule.rule) : 0);
}

/** Fail closed before any daily processing. A missing successor never inherits an expired intro rate. */
export function validateSavings(contract: LedgerContract, scenario: LedgerScenario, refs: (ids: string[]) => void, ruleRefs: (rule: Rule) => void): void {
  const schedule = contract.savingsSchedule;
  if (schedule === undefined) {
    if (scenario.savingsAssessments?.length) throw new Error('savings_assessment_without_schedule');
    return;
  }
  if (!schedule || contract.direction !== 'asset' || schedule.schemaVersion !== 1 || !['aggregate', 'per_tier'].includes(schedule.dailyAccrualRounding) ||
      !Array.isArray(schedule.intervals) || !schedule.intervals.length || schedule.intervals.length > 512) throw new Error('savings_schedule_unsupported');
  if (scenario.events.some(e => e.type === 'rate')) throw new Error('flat_rate_event_with_savings_schedule');
  const ids = new Set<string>(); let previousEnd: number | null = null, maxTiers = 0, metricCount = 0;
  for (const interval of schedule.intervals) {
    if (!interval.id || ids.has(interval.id)) throw new Error('savings_interval_identity_invalid');
    ids.add(interval.id); refs(interval.evidenceIds);
    const from = dayNumber(interval.from), end = dayNumber(interval.toExclusive);
    if (end <= from || (previousEnd !== null && from !== previousEnd)) throw new Error('savings_interval_gap_or_overlap');
    previousEnd = end;
    if (!Array.isArray(interval.components) || !interval.components.length || interval.components.length > 8) throw new Error('savings_components_invalid');
    const componentIds = new Set<string>(); let tierCount = 0;
    for (const component of interval.components) {
      if (!component.id || componentIds.has(component.id) || !['base', 'bonus', 'intro'].includes(component.kind) ||
          !['marginal', 'whole_balance'].includes(component.allocation) || component.rateMeaning !== 'additive') throw new Error('savings_component_unsupported');
      componentIds.add(component.id); refs(component.evidenceIds);
      if (!Array.isArray(component.tiers) || !component.tiers.length || component.tiers.length > 32) throw new Error('savings_tiers_invalid');
      tierCount += component.tiers.length;
      const tierIds = new Set<string>(); let lower = decimalZero();
      component.tiers.forEach((tier, index) => {
        if (!tier.id || tierIds.has(tier.id)) throw new Error('savings_tier_identity_invalid');
        tierIds.add(tier.id); refs(tier.evidenceIds);
        const rate = Decimal.parse(tier.annualRate);
        if (rate.compare(Decimal.parse('-1')) < 0 || rate.compare(Decimal.parse('1')) > 0) throw new Error('rate_fraction_out_of_bounds');
        if (tier.upperInclusive === null) {
          if (index !== component.tiers.length - 1) throw new Error('savings_unlimited_tier_not_last');
        } else {
          const upper = Decimal.parse(tier.upperInclusive);
          if (upper.compare(upper.rounded(2, 'toward_zero')) !== 0 || upper.compare(lower) <= 0 || index === component.tiers.length - 1) throw new Error('savings_tier_boundary_invalid');
          lower = upper;
        }
      });
      if (component.qualification !== null) {
        const q = component.qualification;
        if (!q?.assessmentKey || !q.accountId) throw new Error('savings_qualification_scope_missing');
        if (!Array.isArray(q.windows) || !q.windows.length || q.windows.length > 600) throw new Error('savings_qualification_windows_missing');
        let windowEnd: number | null = null;
        for (const w of q.windows) {
          refs(w.evidenceIds);
          const appliesFrom = dayNumber(w.appliesFrom), appliesTo = dayNumber(w.appliesToExclusive);
          if (dayNumber(w.toExclusive) <= dayNumber(w.from) || appliesTo <= appliesFrom ||
              (windowEnd !== null && appliesFrom !== windowEnd)) throw new Error('savings_qualification_window_gap_or_overlap');
          windowEnd = appliesTo;
        }
        if (dayNumber(q.windows[0].appliesFrom) > from || windowEnd! < end) throw new Error('savings_qualification_window_coverage_missing');
        ruleRefs(q.rule);
        tierCount += ruleWeight(q.rule) + (q.activityMetrics?.length ?? 0);
        metricCount += q.activityMetrics?.length ?? 0;
        if (q.activityMetrics !== undefined) validateActivityMetrics(q.activityMetrics, refs);
      }
    }
    maxTiers = Math.max(maxTiers, tierCount);
  }
  const start = dayNumber(scenario.startDate), end = dayNumber(scenario.endDateExclusive);
  if (dayNumber(schedule.intervals[0].from) > start || previousEnd! < end) throw new Error('savings_horizon_coverage_missing');
  if ((end - start) * maxTiers > 250_000) throw new Error('savings_output_limit');
  const assessments = scenario.savingsAssessments ?? [];
  if (!Array.isArray(assessments) || assessments.length > 1200) throw new Error('savings_assessment_limit');
  const assessmentIds = new Set<string>();
  let eventCount = 0;
  const scopes = new Map<string, { from: number; to: number }[]>();
  for (const a of assessments) {
    if (!a.id || assessmentIds.has(a.id) || !a.assessmentKey || !a.accountId || !['complete', 'unknown'].includes(a.coverage) ||
        !a.facts || typeof a.facts !== 'object' || Array.isArray(a.facts)) throw new Error('savings_assessment_invalid');
    assessmentIds.add(a.id); refs(a.evidenceIds);
    const matchedWindow = schedule.intervals.some(i => i.components.some(c => {
      const q = c.qualification;
      return q && q.assessmentKey === a.assessmentKey && q.accountId === a.accountId && q.windows.some(w =>
        w.from === a.from && w.toExclusive === a.toExclusive && w.appliesFrom === a.appliesFrom && w.appliesToExclusive === a.appliesToExclusive);
    }));
    if (!matchedWindow) throw new Error('savings_assessment_window_unreviewed');
    if (a.activity !== undefined) { validateActivityData(a.activity); eventCount += a.activity.events.length; }
    if (eventCount > 50_000) throw new Error('savings_activity_event_limit');
    if (eventCount * metricCount > 2_000_000) throw new Error('savings_activity_work_limit');
    const from = dayNumber(a.appliesFrom), to = dayNumber(a.appliesToExclusive);
    if (dayNumber(a.toExclusive) <= dayNumber(a.from) || to <= from) throw new Error('savings_assessment_dates_invalid');
    const key = JSON.stringify([a.assessmentKey, a.accountId]);
    const prior = scopes.get(key) ?? [];
    if (prior.some(p => from < p.to && to > p.from)) throw new Error('savings_assessment_overlap');
    prior.push({ from, to }); scopes.set(key, prior);
  }
}
