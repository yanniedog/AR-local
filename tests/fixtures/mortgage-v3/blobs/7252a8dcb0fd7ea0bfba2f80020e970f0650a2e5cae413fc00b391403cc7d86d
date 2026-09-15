import { utf8ToBytes } from '@noble/hashes/utils';
import { canonical, hashText } from '../../lib/productTermsEngine/validation';
import { Decimal } from '../../lib/productTermsEngine/decimal';
import type { Rule } from '../../lib/productTermsEngine/types';
import { safeId, validFact } from '../customerProfile';
import { validateAuthorityGraph, monetaryIdentity } from '../monetaryContracts/authority';
import { exactList, includesInterval, interval } from '../monetaryContracts/coverage';
import { assertMortgageWire } from './schemaValidation';
import { mortgagePostingDates } from './calendar';
import type { MortgageAsset, MortgageSubject } from './types';
export function mortgageBudget(subjects: MortgageSubject[]) {
 const members = new Map<string,string>(), observations = new Map<string,string>(), authorities = new Set<string>(); let bytes = 0, decoded = 0, nodes = 0, events = 0;
 const visit = (r: Rule, depth: number) => { if (++nodes > 512 || depth > 16) throw new Error('Mortgage rule budget'); if (r.op === 'and' || r.op === 'or') r.rules.forEach(c => visit(c, depth + 1)); else if (r.op === 'not') visit(r.rule, depth + 1); };
 for (const s of subjects) {
  for (const m of s.authorityGraph.members) { const raw = canonical(m), prior = members.get(m.sha256); if (prior && prior !== raw) throw new Error('Mortgage member collision'); if (!prior) { members.set(m.sha256,raw); bytes += m.bytes; decoded += m.decodedBytes; } }
  for (const a of s.authorityGraph.authorities) { authorities.add(a.id); if (a.kind === 'retained_observation') for (const o of a.observations) { const raw = canonical(o), old = observations.get(o.observationId); if (old && old !== raw) throw new Error('Mortgage observation collision'); observations.set(o.observationId,raw); } }
  events += s.policy.postingInventory.dueDates.length + s.policy.fees.occurrences.length; visit(s.policy.eligibility,0);
 }
 if (members.size > 512 || authorities.size > 64 || observations.size > 366 || events > 366 || bytes > 32*1024*1024 || decoded > 24*1024*1024) throw new Error('Mortgage source operation limit');
}
/** Public structured graph only: producer verifies original source bytes and typed revisions. */
export function mortgageCoverage(s: MortgageSubject, eventDates: Record<string,string[]> = {}) {
 const start = s.scope.from, end = s.scope.toExclusive, g = s.authorityGraph, selected = s.policy.authorityIds;
 const ids = new Set(g.authorities.map(a => a.id)); if (new Set(selected).size !== selected.length || selected.some(id => !ids.has(id))) throw new Error('Mortgage selected authority invalid');
 const bounds = [...new Set([start,end,...g.authorities.flatMap(a => [a.from,a.toExclusive]),...g.supersessions.flatMap(r => [r.from,r.toExclusive])])].filter(d => d >= start && d <= end).sort();
 const segments = bounds.slice(0,-1).map((from,i) => {
  const to = bounds[i+1], active = g.authorities.filter(a => includesInterval(a.from,a.toExclusive,from,to));
  const winners = active.filter(a => selected.includes(a.id) && active.every(b => a.id === b.id || g.supersessions.some(r => r.selectedAuthorityId === a.id && r.supersededAuthorityId === b.id && includesInterval(r.from,r.toExclusive,from,to))));
  if (winners.length !== 1) throw new Error('Mortgage historical authority gap or conflict'); return { from,to,authority:winners[0] };
 });
 if (selected.some(id => !segments.some(x => x.authority.id === id))) throw new Error('Mortgage unused selected authority');
 for (const [field,refs] of Object.entries(s.policy.fieldEvidenceIds)) {
  const entries = segments.flatMap(x => x.authority.fieldCoverage.filter(f => f.field === field && f.from < x.to && f.toExclusive > x.from && f.evidenceIds.some(r => refs.includes(r))).map(f => ({ ...f, from: f.from > x.from ? f.from : x.from, toExclusive: f.toExclusive < x.to ? f.toExclusive : x.to }))).sort((a,b) => a.from.localeCompare(b.from));
  let through = start; for (const f of entries) { if (f.from > through) break; if (f.toExclusive > through) through = f.toExclusive; }
  if (through < end || refs.some(id => !entries.some(f => f.evidenceIds.includes(id))) || (eventDates[field] ?? []).some(d => !entries.some(f => f.from <= d && d < f.toExclusive && f.postingEventDates.includes(d)))) throw new Error(`Mortgage source coverage missing: ${field}`);
 }
}
export function validateMortgageSubject(raw: unknown): MortgageSubject {
 if (utf8ToBytes(JSON.stringify(raw)).length > 256*1024) throw new Error('Mortgage subject limit'); assertMortgageWire(raw,'subject'); const s = raw as MortgageSubject; mortgageBudget([s]);
 if (monetaryIdentity(s,'id') !== s.id || hashText(canonical(['monetary-scope-v3',s.capability,s.scope])) !== s.scopeId || s.routing.productKey !== s.scope.productKey) throw new Error('Mortgage identity mismatch'); interval(s.scope.from,s.scope.toExclusive);
 exactList(s.documentVersionIds,[...new Set(s.evidence.map(e => e.documentVersionId))].sort(),'Mortgage document inventory'); exactList(s.termRevisionIds,[...new Set(s.termRevisionIds)].sort(),'Mortgage revision inventory');
 const evidence = new Set<string>(); for (const e of s.evidence) { const u = new URL(e.sourceUrl); if (e.id !== e.clauseId || evidence.has(e.id) || hashText(e.quote) !== e.quoteSha256 || u.protocol !== 'https:' || u.username || u.password) throw new Error('Mortgage evidence invalid'); evidence.add(e.id); }
 const refs = (r: string[]) => { if (!r.length || r.some(id => !evidence.has(id))) throw new Error('Mortgage evidence missing'); };
 validateAuthorityGraph(s,refs); Object.values(s.policy.fieldEvidenceIds).forEach(refs);
 if (Decimal.parse(s.policy.annualRate).compare(Decimal.parse('1')) > 0) throw new Error('Mortgage rate unsupported');
 exactList(s.policy.postingInventory.dueDates,mortgagePostingDates(s),'Mortgage posting inventory');
 const feeIds = new Set<string>(), orders = new Set<string>(); for (const f of s.policy.fees.occurrences) { const key = `${f.dueDate}:${f.order}`; if (!safeId(f.id) || feeIds.has(f.id) || orders.has(key) || f.incurredDate < s.scope.from || f.incurredDate > f.dueDate || f.dueDate >= s.scope.toExclusive) throw new Error('Mortgage fee inventory invalid'); feeIds.add(f.id); orders.add(key); refs(f.evidenceIds); }
 const definitions = new Map(s.policy.inputDefinitions.map(d => [d.field,d])), roles = new Set<string>(), used = new Set<string>(), ruleIds = new Set<string>(); if (definitions.size !== s.policy.inputDefinitions.length) throw new Error('Mortgage duplicate input');
 const bindingTypes: Record<string,[string,string|null]> = { opening_principal:['decimal','AUD'],obligation_amount:['decimal','AUD'],from_date:['date',null],to_exclusive_date:['date',null],confirmed_annual_rate:['decimal','fraction'],offer_purpose:['text',null],offer_security:['text',null],repayment_type:['text',null] };
 for (const d of definitions.values()) { refs(d.evidenceIds); if (!safeId(d.field) || !d.label.trim() || (d.type === 'decimal' ? !d.unit?.trim() : d.unit !== null) || Object.hasOwn(bindingTypes,d.field) && d.binding !== d.field) throw new Error('Mortgage input binding invalid'); if (d.binding !== 'customer_fact') { const expected = bindingTypes[d.binding]; if (roles.has(d.binding) || expected[0] !== d.type || expected[1] !== d.unit) throw new Error('Mortgage scenario role invalid'); roles.add(d.binding); } }
 function visit(r: Rule) { if (!safeId(r.id) || ruleIds.has(r.id)) throw new Error('Mortgage rule identity'); ruleIds.add(r.id); if (r.op === 'not') visit(r.rule); else if (r.op === 'and' || r.op === 'or') r.rules.forEach(visit); else if (r.op === 'compare') { const d = definitions.get(r.field); refs(r.evidenceIds!); used.add(r.field); if (!d || !validFact(r.expected) || d.type !== r.expected.type || r.expected.type === 'decimal' && d.unit !== r.expected.unit || !['eq','ne'].includes(r.comparison) && !['decimal','date'].includes(d.type)) throw new Error('Mortgage rule input invalid'); } }
 visit(s.policy.eligibility); if ([...definitions.values()].some(d => !used.has(d.field))) throw new Error('Mortgage unused input');
 const dates = s.policy.postingInventory.dueDates; mortgageCoverage(s,{ interestBasis:dates,postingRounding:dates,postingResidue:dates,postingDates:dates,feeInventory:[...new Set(s.policy.fees.occurrences.flatMap(f => [f.incurredDate,f.dueDate]))],feeSettlement:s.policy.fees.occurrences.map(f => f.dueDate) }); return s;
}
export function validateMortgageAsset(raw: unknown): MortgageAsset {
 if (utf8ToBytes(JSON.stringify(raw)).length > 512*1024) throw new Error('Mortgage asset limit'); assertMortgageWire(raw,'asset'); const a = raw as MortgageAsset; if (monetaryIdentity(a,'identitySha256') !== a.identitySha256) throw new Error('Mortgage asset identity'); mortgageBudget(a.subjects.map(x => x.subject)); const ids = new Set<string>(), scopes = new Set<string>();
 for (const e of a.subjects) { const s = validateMortgageSubject(e.subject); if (ids.has(s.id) || scopes.has(s.scopeId) || e.approval.subjectId !== s.id || e.approval.authorityGraphSha256 !== s.authorityGraph.identitySha256 || a.productKey !== s.scope.productKey || canonical(a.routing) !== canonical(s.routing)) throw new Error('Mortgage approval binding'); ids.add(s.id); scopes.add(s.scopeId); } return a;
}
