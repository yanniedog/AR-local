import { canonical, hashText } from '../../lib/productTermsEngine/validation';
import { dayNumber } from '../../lib/productTermsEngine/calendar';
import type { SavingsSubject, HistoricalAuthority, HistoricalScope, AuthorityGraph } from './types';
import { exactList, includesInterval, interval } from './coverage';
export const monetaryIdentity = (v: object, omit: string) => hashText(canonical(Object.fromEntries(Object.entries(v).filter(([key]) => key !== omit))));
function civilDay(timestamp: string, timeZone: string) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(timestamp));
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)!.value).join('-');
}
export function validateAuthorityGraph(s: { scope: HistoricalScope; authorityGraph: AuthorityGraph; evidence: SavingsSubject['evidence'] }, refs: (ids: string[]) => void) {
  const g = s.authorityGraph;
  if (monetaryIdentity(g, 'identitySha256') !== g.identitySha256) throw new Error('Historical authority graph identity mismatch');
  const members = new Map(g.members.map(m => [m.sha256, m])); if (members.size !== g.members.length) throw new Error('Duplicate historical members');
  const required = new Set<string>();
  function member(id: string) { if (!members.has(id)) throw new Error('Historical member association missing'); required.add(id); }
  member(g.completedPeriod.sourceSnapshotSha256); refs(g.completedPeriod.evidenceIds);
  const asOfDay = civilDay(g.completedPeriod.asOf, g.completedPeriod.timezone);
  if (g.completedPeriod.completedThroughExclusive > asOfDay || s.scope.toExclusive > g.completedPeriod.completedThroughExclusive) throw new Error('Savings exceeds source-owned completed coverage');
  for (const e of s.evidence) member(e.documentSha256);
  const authorities = new Map(g.authorities.map(a => [a.id, a])); if (authorities.size !== g.authorities.length) throw new Error('Duplicate historical authority');
  for (const a of g.authorities) {
    if (monetaryIdentity(a, 'id') !== a.id) throw new Error('Historical authority identity mismatch'); interval(a.from, a.toExclusive);
    if (['productKey','family','cohortKey','tierKey','packageKey'].some(k => a.scope[k as keyof typeof a.scope] !== s.scope[k as keyof typeof s.scope]) || !includesInterval(a.scope.from, a.scope.toExclusive, a.from, a.toExclusive)) throw new Error('Historical authority scope mismatch');
    refs(a.evidenceIds);
    for (const f of a.fieldCoverage) { interval(f.from, f.toExclusive); refs(f.evidenceIds); if (!includesInterval(a.from, a.toExclusive, f.from, f.toExclusive) || f.postingEventDates.some(d => d < f.from || d >= f.toExclusive)) throw new Error('Historical field coverage invalid'); }
    if (a.kind === 'dated_official_clause') {
      refs(a.datedRateAndPolicyClauseIds); a.documentSha256s.forEach(member);
      const evidence = s.evidence.filter(e => a.datedRateAndPolicyClauseIds.includes(e.id));
      exactList(a.documentVersionIds, [...new Set(evidence.map(e => e.documentVersionId))].sort(), 'Dated clause document inventory differs');
      exactList(a.documentSha256s, [...new Set(evidence.map(e => e.documentSha256))].sort(), 'Dated clause hash inventory differs');
    } else {
      const p = a.coverageProof; refs(p.evidenceIds); if (!includesInterval(p.from, p.toExclusive, a.from, a.toExclusive)) throw new Error('Observation continuity unproven');
      for (const o of a.observations) { [o.manifestSha256,o.coreAssetSha256,o.detailsAssetSha256,o.rawSourceSha256].forEach(member); if (new Set(o.rateRows.map(r => r.rateIndex)).size !== o.rateRows.length || new Set(o.rateRows.map(r => r.coreRowIndex)).size !== o.rateRows.length) throw new Error('Historical rate references duplicate'); }
      if (p.basis === 'complete_daily_observations') {
        const days = new Set(a.observations.map(o => dayNumber(civilDay(o.observedAt, g.completedPeriod.timezone))));
        for (let d = dayNumber(a.from); d < dayNumber(a.toExclusive); d++) if (!days.has(d)) throw new Error('Historical observation day missing');
      }
    }
  }
  if ([...members.keys()].some(id => !required.has(id))) throw new Error('Unreferenced historical member');
  for (const relation of g.supersessions) {
    refs(relation.evidenceIds); interval(relation.from, relation.toExclusive);
    if (!authorities.has(relation.selectedAuthorityId) || !authorities.has(relation.supersededAuthorityId) || relation.selectedAuthorityId === relation.supersededAuthorityId) throw new Error('Invalid source supersession');
    const selected = authorities.get(relation.selectedAuthorityId)!, other = authorities.get(relation.supersededAuthorityId)!;
    if (!includesInterval(selected.from, selected.toExclusive, relation.from, relation.toExclusive) || !includesInterval(other.from, other.toExclusive, relation.from, relation.toExclusive)) throw new Error('Supersession exceeds authority overlap');
  }
  return authorities;
}
export function assertFieldCoverage(a: HistoricalAuthority, field: string, from: string, end: string, dates: string[], refs: string[]) {
  const entries = a.fieldCoverage.filter(f => f.field === field && f.from < end && f.toExclusive > from && f.evidenceIds.some(id => refs.includes(id))).sort((x, y) => x.from.localeCompare(y.from));
  let through = from;
  for (const entry of entries) { if (entry.from > through) break; if (entry.toExclusive > through) through = entry.toExclusive; }
  if (through < end || refs.some(id => !entries.some(f => f.from < end && f.toExclusive > from && f.evidenceIds.includes(id))) || dates.some(date => !entries.some(f => f.from <= date && date < f.toExclusive && f.postingEventDates.includes(date)))) throw new Error(`Source coverage missing for ${field}`);
}
