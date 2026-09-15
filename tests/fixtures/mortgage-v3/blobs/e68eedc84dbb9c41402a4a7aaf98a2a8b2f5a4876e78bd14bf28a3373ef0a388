import { dayNumber } from '../lib/productTermsEngine/calendar';
import { Decimal } from '../lib/productTermsEngine/decimal';
import type { Fact } from '../lib/productTermsEngine/types';

export type AnswerState = 'known' | 'unknown' | 'unavailable' | 'not_applicable';
export interface InputDefinition {
  id: string; label: string; type: Fact['type']; unit?: string;
}
export interface InputProvenance {
  source: 'user_input' | 'legacy_user_input';
  recordedAt: string | null;
  productKey: string | null;
  effectiveFrom: string | null;
  effectiveToExclusive: string | null;
}
export type CustomerAnswer = { state: Exclude<AnswerState, 'known'>; provenance: InputProvenance } |
  { state: 'known'; fact: Fact; provenance: InputProvenance };
export interface NegotiatedTerm {
  id: string; label: string; value: string; unit: string; note: string;
  provenance: InputProvenance & { source: 'user_input'; productKey: string };
}
export interface CustomerProfile {
  version: 1;
  revision: number;
  answers: Record<string, CustomerAnswer>;
  definitions: Record<string, InputDefinition>;
  negotiatedTerms: NegotiatedTerm[];
  /** Exact original retained, never fed to published facts or financial rules. */
  legacyScenario: unknown;
}
export const own = (value: object, key: string): boolean => Object.prototype.hasOwnProperty.call(value, key);
export const safeId = (value: unknown): value is string => typeof value === 'string' &&
  /^[A-Za-z][A-Za-z0-9_.:-]{0,179}$/.test(value) && !['__proto__', 'constructor', 'prototype'].includes(value);
const text = (value: unknown, max = 2000): value is string => typeof value === 'string' && value.length <= max;
function date(value: unknown): boolean {
  if (value === null) return true;
  try { return typeof value === 'string' && Number.isFinite(dayNumber(value)); } catch { return false; }
}
export function validFact(value: unknown): value is Fact {
  if (!value || typeof value !== 'object') return false;
  const f = value as Fact;
  if (f.type === 'boolean') return typeof f.value === 'boolean';
  if (f.type === 'text') return text(f.value);
  if (f.type === 'date') return typeof f.value === 'string' && date(f.value);
  if (f.type !== 'decimal' || !text(f.value, 100) || !text(f.unit, 80) || !f.unit.trim()) return false;
  try { Decimal.parse(f.value); return true; } catch { return false; }
}
export function validDefinition(value: unknown): value is InputDefinition {
  if (!value || typeof value !== 'object') return false;
  const d = value as InputDefinition;
  return safeId(d.id) && text(d.label, 160) && !!d.label.trim() &&
    ['decimal', 'text', 'date', 'boolean'].includes(d.type) &&
    (d.type !== 'decimal' || (text(d.unit, 80) && !!d.unit.trim()));
}
export function validProvenance(p: InputProvenance): boolean {
  return !!p && ['user_input', 'legacy_user_input'].includes(p.source) &&
    (p.recordedAt === null || (typeof p.recordedAt === 'string' && /^\d{4}-\d\d-\d\dT/.test(p.recordedAt) && Number.isFinite(Date.parse(p.recordedAt)))) &&
    (p.productKey === null || (text(p.productKey, 300) && !!p.productKey.trim())) &&
    date(p.effectiveFrom) && date(p.effectiveToExclusive) &&
    (!p.effectiveFrom || !p.effectiveToExclusive || p.effectiveFrom < p.effectiveToExclusive);
}
export function validateProfile(value: unknown): CustomerProfile {
  const p = value as CustomerProfile;
  if (!p || p.version !== 1) throw new Error('Unsupported customer profile version. Original data retained.');
  if (!Number.isSafeInteger(p.revision) || p.revision < 0 || !p.answers || !p.definitions ||
      typeof p.answers !== 'object' || Array.isArray(p.answers) || typeof p.definitions !== 'object' || Array.isArray(p.definitions) ||
      !Array.isArray(p.negotiatedTerms) || p.negotiatedTerms.length > 200 || Object.keys(p.answers).length > 512) throw new Error('Invalid customer profile.');
  for (const [id, a] of Object.entries(p.answers)) {
    const d = own(p.definitions, id) ? p.definitions[id] : null;
    if (!safeId(id) || !validDefinition(d) || d.id !== id || !a || !validProvenance(a.provenance) ||
        !['known', 'unknown', 'unavailable', 'not_applicable'].includes(a.state) ||
        (a.state === 'known' && (!validFact(a.fact) || a.fact.type !== d.type ||
          (a.fact.type === 'decimal' && a.fact.unit !== d.unit)))) throw new Error('Invalid customer answer.');
  }
  const ids = new Set<string>();
  for (const t of p.negotiatedTerms) {
    if (!t || !safeId(t.id) || ids.has(t.id) || !text(t.label, 160) || !t.label.trim() ||
        !text(t.value) || !t.value.trim() || !text(t.unit, 80) || !t.unit.trim() || !text(t.note) ||
        !validProvenance(t.provenance) || t.provenance.source !== 'user_input' || !t.provenance.productKey) throw new Error('Invalid negotiated term.');
    ids.add(t.id);
  }
  return p;
}
export function userProvenance(productKey: string | null = null): InputProvenance {
  return { source: 'user_input', recordedAt: new Date().toISOString(), productKey, effectiveFrom: null, effectiveToExclusive: null };
}
