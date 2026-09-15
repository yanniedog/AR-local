import { dayNumber } from './calendar';
import { Decimal } from './decimal';
import type { EligibilityResult, Fact, Facts, Rule, RuleTrace, Truth } from './types';

function compareFacts(actual: Fact, expected: Fact): number {
  if (!actual || !expected || actual.type !== expected.type) throw new Error('fact_type_mismatch');
  if (actual.type === 'decimal' && expected.type === 'decimal') {
    if (!actual.unit || actual.unit !== expected.unit) throw new Error('fact_unit_mismatch');
    return Decimal.parse(actual.value).compare(Decimal.parse(expected.value));
  }
  if (actual.type === 'date' && expected.type === 'date') return Math.sign(dayNumber(actual.value) - dayNumber(expected.value));
  if (actual.type === 'boolean' && (typeof actual.value !== 'boolean' || typeof expected.value !== 'boolean')) throw new Error('invalid_boolean');
  if (actual.type === 'text' && (typeof actual.value !== 'string' || typeof expected.value !== 'string')) throw new Error('invalid_text');
  if (!['boolean', 'text'].includes(actual.type)) throw new Error('fact_type_unsupported');
  return actual.value === expected.value ? 0 : actual.value < expected.value ? -1 : 1;
}

/** Three-valued clause evaluation; full-product coverage/applicability is checked separately. */
export function evaluateEligibility(rule: Rule, facts: Facts): EligibilityResult {
  let nodes = 0;
  const reasons: string[] = [];
  const seen = new Set<string>();
  function visit(item: Rule, depth: number): RuleTrace {
    const id = typeof item?.id === 'string' ? item.id : 'invalid_rule';
    const evidenceIds = Array.isArray(item?.evidenceIds) ? item.evidenceIds : [];
    const unknown = (reason: string): RuleTrace => { reasons.push(reason); return { id, evidenceIds, status: 'needs_information', reason }; };
    if (++nodes > 512 || depth > 16) return unknown('rule_limit_exceeded');
    if (!item || !item.id || seen.has(item.id)) return unknown('rule_identity_invalid');
    seen.add(item.id);
    if (item.op === 'unknown') return unknown(item.reason || 'unsupported_rule');
    if (item.op === 'and' || item.op === 'or') {
      if (!Array.isArray(item.rules) || item.rules.length === 0 || item.rules.length > 128) return unknown('empty_or_oversized_rule_group');
      const children = item.rules.map(child => visit(child, depth + 1));
      const states = children.map(child => child.status);
      const decisive: Truth = item.op === 'and' ? 'does_not_meet' : 'meets';
      const status: Truth = states.includes(decisive) ? decisive : states.includes('needs_information') ? 'needs_information' : item.op === 'and' ? 'meets' : 'does_not_meet';
      return { id, evidenceIds, status, children };
    }
    if (item.op === 'not') {
      const child = visit(item.rule, depth + 1);
      return { id, evidenceIds, status: child.status === 'needs_information' ? child.status : child.status === 'meets' ? 'does_not_meet' : 'meets', children: [child] };
    }
    if (item.op !== 'compare') return unknown('operator_unsupported');
    if (!Object.prototype.hasOwnProperty.call(facts, item.field) || facts[item.field] === undefined) return unknown(`missing:${item.field}`);
    try {
      if (!['eq', 'ne', 'gt', 'gte', 'lt', 'lte'].includes(item.comparison)) return unknown('comparison_unsupported');
      if (['gt', 'gte', 'lt', 'lte'].includes(item.comparison) && !['decimal', 'date'].includes(item.expected.type)) return unknown('ordered_type_unsupported');
      const value = compareFacts(facts[item.field]!, item.expected);
      const pass = { eq: value === 0, ne: value !== 0, gt: value > 0, gte: value >= 0, lt: value < 0, lte: value <= 0 }[item.comparison];
      return { id, evidenceIds, status: pass ? 'meets' : 'does_not_meet' };
    } catch { return unknown(`invalid:${item.field}`); }
  }
  const trace = visit(rule, 0);
  return { status: trace.status, trace, reasons: [...new Set(reasons)] };
}
