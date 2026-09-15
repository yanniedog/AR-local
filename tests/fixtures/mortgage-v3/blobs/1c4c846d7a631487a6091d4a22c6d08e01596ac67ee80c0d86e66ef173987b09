import { utf8ToBytes } from '@noble/hashes/utils';
import { canonical, hashText } from '../../lib/productTermsEngine/validation';
import type { Rule } from '../../lib/productTermsEngine/types';
import { safeId, validFact } from '../customerProfile';
import { assertEligibilityWire } from './schemaValidation';
import type { EligibilityAsset, EligibilitySubject } from './types';
export const eligibilityIdentity = (value: object, omitted: string) => hashText(canonical(Object.fromEntries(Object.entries(value).filter(([key]) => key !== omitted))));
export function eligibilityScopeId(scope: EligibilitySubject['scope']) { return hashText(canonical(['executable-scope-v2', 'eligibility_only', scope])); }
export function validateEligibilitySubject(raw: unknown): EligibilitySubject {
  if (utf8ToBytes(JSON.stringify(raw)).length > 256 * 1024) throw new Error('Eligibility subject exceeds limit');
  assertEligibilityWire(raw, 'subject'); const s = raw as EligibilitySubject;
  if (eligibilityIdentity(s, 'id') !== s.id || eligibilityScopeId(s.scope) !== s.scopeId || s.scope.effectiveFrom >= s.scope.effectiveToExclusive) throw new Error('Eligibility identity or interval invalid');
  if (s.scope.rateIndexes.some((n, i, values) => i > 0 && values[i - 1] >= n)) throw new Error('Rate scope must be sorted unique');
  const rows = s.source.rateRows;
  if (s.scope.coverage === 'product' ? rows.length !== 0 : rows.length !== s.scope.rateIndexes.length || rows.some(r => !s.scope.rateIndexes.includes(r.rateIndex))) throw new Error('Rate scope mismatch');
  if (new Set(rows.map(r => r.coreRowIndex)).size !== rows.length || new Set(rows.map(r => r.rateIndex)).size !== rows.length) throw new Error('Duplicate source rate');
  if (canonical(s.source.documentVersionIds) !== canonical([...new Set(s.evidence.map(e => e.documentVersionId))].sort()) || canonical(s.source.termRevisionIds) !== canonical([...new Set(s.source.termRevisionIds)].sort())) throw new Error('Eligibility source inventory mismatch');
  const refs = new Set<string>();
  for (const e of s.evidence) {
    const url = new URL(e.sourceUrl);
    if (refs.has(e.id) || e.id !== e.clauseId || !s.source.documentVersionIds.includes(e.documentVersionId) || url.protocol !== 'https:' || url.username || url.password || hashText(e.quote) !== e.quoteSha256) throw new Error('Eligibility evidence invalid');
    refs.add(e.id);
  }
  const checkRefs = (values: string[]) => { if (!values.length || values.some(id => !refs.has(id))) throw new Error('Eligibility clause missing'); };
  Object.values(s.fieldClauseIds).forEach(checkRefs);
  const definitions = new Map(s.inputDefinitions.map(d => [d.key, d])), roles = new Set<string>();
  if (definitions.size !== s.inputDefinitions.length) throw new Error('Duplicate eligibility input');
  for (const d of s.inputDefinitions) {
    checkRefs(d.clauseIds);
    if (!safeId(d.key) || !d.label.trim() || (d.type === 'decimal' ? !d.unit?.trim() : d.unit !== null)) throw new Error('Invalid eligibility input');
    if (d.binding === 'customer_fact') continue;
    if (roles.has(d.binding)) throw new Error('Duplicate scenario role'); roles.add(d.binding);
    if (d.binding === 'assessment_date' ? d.type !== 'date' : ['scenario_amount','scenario_security_value'].includes(d.binding) ? d.type !== 'decimal' || d.unit !== 'AUD' : d.type !== 'text') throw new Error('Scenario role type mismatch');
  }
  if (!roles.has('assessment_date')) throw new Error('Assessment date role missing');
  const ids = new Set<string>(), used = new Set<string>(); let nodes = 0;
  function visit(r: Rule, depth: number) {
    if (++nodes > 512 || depth > 16 || ids.has(r.id) || !safeId(r.id)) throw new Error('Eligibility rule limit'); ids.add(r.id);
    if (r.op === 'and' || r.op === 'or') r.rules.forEach(child => visit(child, depth + 1));
    else if (r.op === 'not') visit(r.rule, depth + 1);
    else if (r.op === 'compare') {
      const d = definitions.get(r.field); checkRefs(r.evidenceIds!); used.add(r.field);
      if (!d || !validFact(r.expected) || d.type !== r.expected.type || r.expected.type === 'decimal' && d.unit !== r.expected.unit || !['eq','ne'].includes(r.comparison) && !['decimal','date'].includes(d.type)) throw new Error('Eligibility rule input mismatch');
    } else throw new Error('Unsupported eligibility rule');
  }
  visit(s.eligibility, 0);
  if (s.inputDefinitions.some(d => d.binding !== 'assessment_date' && !used.has(d.key))) throw new Error('Unused eligibility definition');
  return s;
}
export function validateEligibilityAsset(raw: unknown): EligibilityAsset {
  if (utf8ToBytes(JSON.stringify(raw)).length > 512 * 1024) throw new Error('Eligibility asset exceeds limit');
  assertEligibilityWire(raw, 'asset'); const a = raw as EligibilityAsset;
  if (eligibilityIdentity(a, 'identitySha256') !== a.identitySha256) throw new Error('Eligibility asset identity mismatch');
  const ids = new Set<string>(), scopes = new Set<string>();
  for (const entry of a.subjects) {
    const s = validateEligibilitySubject(entry.subject);
    if (ids.has(s.id) || scopes.has(s.scopeId) || entry.approval.subjectId !== s.id || s.scope.productKey !== a.productKey || s.source.observationId !== a.sourceObservationId || s.source.generationId !== a.sourceGenerationId || s.source.runDate !== a.runDate || s.source.coreAssetSha256 !== a.coreAssetSha256 || s.source.detailsAssetSha256 !== a.detailsAssetSha256) throw new Error('Eligibility approval association mismatch');
    ids.add(s.id); scopes.add(s.scopeId);
  }
  return a;
}
