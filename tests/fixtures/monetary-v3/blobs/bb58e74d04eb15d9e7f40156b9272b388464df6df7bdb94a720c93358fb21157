import { formatRate, humanizeEnum } from './format';
import type {
  NormalizedProductFact,
  NormalizedProductFactKind,
  NormalizedProductFactUnit,
  ProductDetail,
  RateRow,
} from '../types';

export type FactCriterionOperator = 'exists' | 'eq' | 'gte' | 'lte';
export type FactCriterionScalar = string | number | boolean;

/** Persistable filter identity. At least one trusted key is required. */
export type FactCriterionIdentity =
  | { canonicalKey: string; sourceType?: string }
  | { canonicalKey?: string; sourceType: string };

export type FactCriterion = FactCriterionIdentity & {
  operator: FactCriterionOperator;
  value?: FactCriterionScalar;
  unit?: NormalizedProductFactUnit;
};

export interface PublishedFactFilterOption {
  id: string;
  label: string;
  criterion: FactCriterion;
}

const FACT_KINDS = new Set<NormalizedProductFactKind>([
  'fee', 'rate', 'tier', 'bundle', 'attribute', 'feature',
  'eligibility', 'constraint', 'condition',
]);
const FACT_UNITS = new Set([
  'AUD', 'fraction', 'duration', 'day', 'month', 'year',
  'count', 'boolean', 'text', 'enum',
]);

const isFactUnit = (value: unknown): value is NormalizedProductFactUnit =>
  typeof value === 'string' && (FACT_UNITS.has(value) || /^[A-Z]{3}$/.test(value));

/** Only these normalized keys may become interactive feature filters. */
export const CURATED_FEATURE_FACT_KEYS = new Set([
  'OFFSET', 'EXTRA_REPAYMENTS', 'REDRAW', 'GUARANTOR', 'CASHBACK_OFFER',
  'CARD_ACCESS', 'NPP_PAYID', 'UNLIMITED_TXNS', 'BILL_PAYMENT', 'OVERDRAFT',
  'FREE_TXNS', 'DIGITAL_BANKING', 'NOTIFICATIONS',
]);

/** Customer eligibility dimensions suitable for an exact-match product filter. */
export const CURATED_ELIGIBILITY_FACT_KEYS = new Set([
  'MIN_AGE', 'MAX_AGE', 'RESIDENCY', 'RESIDENCY_STATUS', 'EMPLOYMENT_STATUS',
  'CUSTOMER_TYPE', 'BORROWER_TYPE', 'NATURAL_PERSON', 'BUSINESS',
  'FIRST_HOME_BUYER', 'EXISTING_CUSTOMER', 'STAFF', 'MEMBERSHIP',
]);

/** Numeric/product boundaries exposed alongside eligibility filters. */
export const CURATED_CONSTRAINT_FACT_KEYS = new Set([
  'MIN_BALANCE', 'MAX_BALANCE', 'MIN_AMOUNT', 'MAX_AMOUNT',
  'MIN_LIMIT', 'MAX_LIMIT', 'MIN_LVR', 'MAX_LVR', 'MIN_TERM', 'MAX_TERM',
]);

const isScalar = (value: unknown): value is string | number | boolean =>
  typeof value === 'boolean' ||
  (typeof value === 'number' && Number.isFinite(value)) ||
  (typeof value === 'string' && value.trim().length > 0);

const isBoundScalar = (value: unknown): value is string | number =>
  (typeof value === 'number' && Number.isFinite(value)) ||
  (typeof value === 'string' && value.trim() !== '');

const isNumericLike = (value: unknown): value is string | number =>
  isBoundScalar(value) && Number.isFinite(Number(value));

function isFact(value: unknown): value is NormalizedProductFact {
  if (!value || typeof value !== 'object') return false;
  const fact = value as Partial<NormalizedProductFact>;
  if (typeof fact.id !== 'string' || !fact.id.trim()) return false;
  if (fact.groupId !== undefined && (typeof fact.groupId !== 'string' || !fact.groupId.trim())) return false;
  if (fact.parentId !== undefined && (typeof fact.parentId !== 'string' || !fact.parentId.trim())) return false;
  if (typeof fact.kind !== 'string' || !FACT_KINDS.has(fact.kind as NormalizedProductFactKind)) return false;
  if (typeof fact.canonicalKey !== 'string' || !fact.canonicalKey.trim()) return false;
  if (fact.label !== undefined && (typeof fact.label !== 'string' || !fact.label.trim())) return false;
  if (fact.unit !== undefined && !isFactUnit(fact.unit)) return false;
  if (fact.value !== undefined && !isScalar(fact.value)) return false;
  if (fact.minValue !== undefined && !isBoundScalar(fact.minValue)) return false;
  if (fact.maxValue !== undefined && !isBoundScalar(fact.maxValue)) return false;
  if (fact.cadence !== undefined && typeof fact.cadence !== 'string') return false;
  if (fact.condition !== undefined && typeof fact.condition !== 'string') return false;
  if (fact.sourceType !== undefined && typeof fact.sourceType !== 'string') return false;
  if (fact.appliesTo !== undefined && (!Array.isArray(fact.appliesTo) || !fact.appliesTo.every((item) => typeof item === 'string'))) return false;
  if (fact.searchTerms !== undefined && (!Array.isArray(fact.searchTerms) || !fact.searchTerms.every((item) => typeof item === 'string'))) return false;
  return true;
}

/** Runtime guard for downloaded payloads. Order and same-key variants are preserved. */
export function normalizedProductFacts(detail: ProductDetail | null | undefined): NormalizedProductFact[] {
  if (!Array.isArray(detail?.facts)) return [];
  return (detail.facts as unknown[]).filter(isFact);
}

/**
 * A lossless semantic identity for future change comparison. Never collapse
 * variants by canonicalKey: source id, typed values and condition all matter.
 */
export function productFactSignature(fact: NormalizedProductFact): string {
  return JSON.stringify({
    id: fact.id,
    groupId: fact.groupId,
    parentId: fact.parentId,
    kind: fact.kind,
    canonicalKey: fact.canonicalKey,
    label: fact.label,
    sourceType: fact.sourceType,
    value: fact.value,
    minValue: fact.minValue,
    maxValue: fact.maxValue,
    unit: fact.unit,
    cadence: fact.cadence,
    appliesTo: fact.appliesTo,
    condition: fact.condition,
  });
}

function candidateFilterKeys(fact: NormalizedProductFact): string[] {
  const sourceType = fact.sourceType?.trim().toUpperCase();
  const segments = fact.canonicalKey.trim().split(/[.:/]/).filter(Boolean);
  const canonicalLeaf = segments[segments.length - 1]?.toUpperCase();
  return Array.from(new Set([sourceType, canonicalLeaf].filter((key): key is string => Boolean(key))));
}

function curatedFeatureIdentityKey(fact: NormalizedProductFact): string | null {
  if (fact.kind !== 'feature') return null;
  return candidateFilterKeys(fact).find((key) => CURATED_FEATURE_FACT_KEYS.has(key)) ?? null;
}

export function curatedFeatureFactKey(fact: NormalizedProductFact): string | null {
  if (fact.kind !== 'feature' || fact.value === false) return null;
  return curatedFeatureIdentityKey(fact);
}

export function curatedEligibilityFactKey(fact: NormalizedProductFact): string | null {
  if (fact.value === false) return null;
  for (const key of candidateFilterKeys(fact)) {
    if (fact.kind === 'eligibility' && CURATED_ELIGIBILITY_FACT_KEYS.has(key)) return key;
    if (fact.kind === 'constraint' && CURATED_CONSTRAINT_FACT_KEYS.has(key)) return key;
  }
  return null;
}

const MAX_SEARCH_TERMS = 16;
const MAX_SEARCH_FIELD_LENGTH = 240;

function safeSearchText(value: unknown, rejectUrl = false): string | null {
  if (!isScalar(value)) return null;
  const text = String(value).trim().slice(0, MAX_SEARCH_FIELD_LENGTH);
  if (!text) return null;
  if (rejectUrl && /(?:https?:\/\/|www\.|:\/\/)/i.test(text)) return null;
  return text;
}

/** Explicit searchable fields only; ids, source enums and unknown object text stay private. */
export function productFactsSearchText(detail: ProductDetail | null | undefined): string[] {
  const chunks: string[] = [];
  for (const fact of normalizedProductFacts(detail)) {
    chunks.push(fact.canonicalKey);
    const label = safeSearchText(fact.label);
    chunks.push(label ?? humanizeEnum(fact.canonicalKey.split(/[.:/]/).filter(Boolean).at(-1) ?? fact.canonicalKey));
    for (const value of [fact.value, fact.minValue, fact.maxValue]) {
      const text = safeSearchText(value);
      if (text) chunks.push(text);
    }
    for (const value of fact.appliesTo?.slice(0, MAX_SEARCH_TERMS) ?? []) {
      const text = safeSearchText(value);
      if (text) chunks.push(text, humanizeEnum(text));
    }
    const condition = safeSearchText(fact.condition);
    if (condition) chunks.push(condition);
    for (const value of fact.searchTerms?.slice(0, MAX_SEARCH_TERMS) ?? []) {
      const text = safeSearchText(value, true);
      if (text) chunks.push(text);
    }
  }
  return chunks;
}

function formatNumber(value: string | number): string {
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString('en-AU', { maximumFractionDigits: 2 })
    : String(value);
}

function formatUnitValue(value: string | number | boolean, unit?: NormalizedProductFactUnit): string {
  if (unit === 'boolean' || typeof value === 'boolean') return value === true || value === 'true' ? 'Yes' : 'No';
  if (unit === 'AUD') return `$${formatNumber(value as string | number)}`;
  if (unit && /^[A-Z]{3}$/.test(unit)) return `${unit} ${formatNumber(value as string | number)}`;
  if (unit === 'fraction') return formatRate(value as string | number);
  if (unit === 'duration' && typeof value === 'string') return durationValueLabel(value);
  if (unit === 'enum') return humanizeEnum(value as string | number);
  if (unit === 'day' || unit === 'month' || unit === 'year' || unit === 'count') {
    const amount = formatNumber(value as string | number);
    if (unit === 'count') return amount;
    return `${amount} ${unit}${Number(value) === 1 ? '' : 's'}`;
  }
  return String(value).trim();
}

function durationParts(duration: string): string[] | null {
  const match = /^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?$/i.exec(duration.trim());
  if (!match || !match.slice(1).some(Boolean)) return null;
  const units = ['year', 'month', 'week', 'day'];
  return match.slice(1).flatMap((raw, index) => {
    if (!raw) return [];
    const amount = Number(raw);
    return `${amount} ${units[index]}${amount === 1 ? '' : 's'}`;
  });
}

function durationValueLabel(duration: string): string {
  return durationParts(duration)?.join(', ') ?? duration;
}

function cadenceLabel(cadence?: string): string {
  if (!cadence) return '';
  const parts = durationParts(cadence);
  if (!parts) return cadence;
  const singleUnit = /^1 ([a-z]+)$/.exec(parts.join(''));
  if (singleUnit) return `per ${singleUnit[1]}`;
  return `every ${parts.join(', ')}`;
}

export function productFactValue(fact: NormalizedProductFact): string | null {
  let value = '';
  if (fact.minValue !== undefined && fact.maxValue !== undefined) {
    value = `${formatUnitValue(fact.minValue, fact.unit)}–${formatUnitValue(fact.maxValue, fact.unit)}`;
  } else if (fact.minValue !== undefined) {
    value = `From ${formatUnitValue(fact.minValue, fact.unit)}`;
  } else if (fact.maxValue !== undefined) {
    value = `Up to ${formatUnitValue(fact.maxValue, fact.unit)}`;
  } else if (fact.value !== undefined) {
    value = formatUnitValue(fact.value, fact.unit);
  }
  const cadence = cadenceLabel(fact.cadence);
  return [value, cadence].filter(Boolean).join(' · ') || null;
}

export function productFactLabel(fact: NormalizedProductFact): string {
  if (fact.label?.trim()) return fact.label.trim();
  const parts = fact.canonicalKey.split(/[.:/]/).filter(Boolean);
  return humanizeEnum(parts[parts.length - 1] ?? fact.canonicalKey);
}

function factIdentityMatches(fact: NormalizedProductFact, criterion: FactCriterion): boolean {
  if (criterion.sourceType && fact.sourceType?.trim().toUpperCase() !== criterion.sourceType.trim().toUpperCase()) {
    return false;
  }
  if (criterion.canonicalKey && fact.canonicalKey !== criterion.canonicalKey) return false;
  return Boolean(criterion.sourceType || criterion.canonicalKey);
}

function scalarEquals(left: FactCriterionScalar, right: FactCriterionScalar): boolean {
  if (typeof left === 'number' || typeof right === 'number') {
    const a = Number(left);
    const b = Number(right);
    return Number.isFinite(a) && Number.isFinite(b) && a === b;
  }
  if (typeof left === 'boolean' || typeof right === 'boolean') return left === right;
  return left.trim().toLowerCase() === right.trim().toLowerCase();
}

function comparisonFactValue(fact: NormalizedProductFact, operator: 'gte' | 'lte'): FactCriterionScalar | undefined {
  if (fact.value !== undefined) return fact.value;
  // A caller testing whether a customer value is inside a published range uses
  // MIN <= customer (lte) and MAX >= customer (gte). Single-bound facts fall
  // back to their only bound so MIN_AGE/MAX_AGE facts work in either shape.
  if (operator === 'gte') return fact.maxValue ?? fact.minValue;
  return fact.minValue ?? fact.maxValue;
}

export function productMatchesFactCriterion(
  detail: ProductDetail | null | undefined,
  criterion: FactCriterion,
): boolean {
  return normalizedProductFacts(detail).some((fact) => {
    if (!factIdentityMatches(fact, criterion)) return false;
    if (criterion.unit && fact.unit !== criterion.unit) return false;
    if (criterion.operator === 'exists') return true;
    if (criterion.value === undefined) return false;
    if (criterion.operator === 'eq') {
      return [fact.value, fact.minValue, fact.maxValue]
        .filter((value): value is FactCriterionScalar => value !== undefined)
        .some((value) => scalarEquals(value, criterion.value!));
    }
    const factValue = comparisonFactValue(fact, criterion.operator);
    if (factValue === undefined) return false;
    const left = Number(factValue);
    const right = Number(criterion.value);
    if (!Number.isFinite(left) || !Number.isFinite(right)) return false;
    return criterion.operator === 'gte' ? left >= right : left <= right;
  });
}

/** AND across criteria, with each criterion checking every preserved fact variant. */
export function productMatchesAllFactCriteria(
  detail: ProductDetail | null | undefined,
  criteria: FactCriterion[] | null | undefined,
): boolean {
  if (!criteria?.length) return true;
  return criteria.every((criterion) => productMatchesFactCriterion(detail, criterion));
}

export function factCriterionId(criterion: FactCriterion): string {
  return JSON.stringify({
    canonicalKey: criterion.canonicalKey,
    sourceType: criterion.sourceType?.trim().toUpperCase(),
    operator: criterion.operator,
    value: criterion.value,
    unit: criterion.unit,
  });
}

export function normalizeFactCriterion(value: unknown): FactCriterion | null {
  if (!value || typeof value !== 'object') return null;
  const input = value as Partial<FactCriterion>;
  const canonicalKey = typeof input.canonicalKey === 'string' ? input.canonicalKey.trim() : '';
  const sourceType = typeof input.sourceType === 'string' ? input.sourceType.trim().toUpperCase() : '';
  if (!canonicalKey && !sourceType) return null;
  if (!['exists', 'eq', 'gte', 'lte'].includes(String(input.operator))) return null;
  const operator = input.operator as FactCriterionOperator;
  if (operator !== 'exists' && !isScalar(input.value)) return null;
  if (input.unit !== undefined && !isFactUnit(input.unit)) return null;
  return {
    ...(canonicalKey ? { canonicalKey } : {}),
    ...(sourceType ? { sourceType } : {}),
    operator,
    ...(operator !== 'exists' ? { value: input.value } : {}),
    ...(input.unit ? { unit: input.unit } : {}),
  } as FactCriterion;
}

function optionCriterion(fact: NormalizedProductFact): FactCriterion | null {
  const curatedKey = curatedFeatureIdentityKey(fact) ?? curatedEligibilityFactKey(fact);
  if (!curatedKey) return null;
  // The canonical key is the curated identity. Generic source enums such as
  // OTHER are useful qualifiers but are never specific enough on their own.
  const identity: FactCriterionIdentity = {
    canonicalKey: fact.canonicalKey,
    ...(fact.sourceType?.trim() ? { sourceType: fact.sourceType.trim().toUpperCase() } : {}),
  };
  if (fact.value !== undefined && (typeof fact.value === 'boolean' || isNumericLike(fact.value))) {
    return { ...identity, operator: 'eq', value: fact.value, unit: fact.unit };
  }
  // A chip represents the exact boundary the bank publishes. Threshold
  // operators are reserved for deliberate applicant-value/range criteria.
  if (fact.minValue !== undefined && fact.maxValue === undefined && isNumericLike(fact.minValue)) {
    return { ...identity, operator: 'eq', value: fact.minValue, unit: fact.unit };
  }
  if (fact.maxValue !== undefined && fact.minValue === undefined && isNumericLike(fact.maxValue)) {
    return { ...identity, operator: 'eq', value: fact.maxValue, unit: fact.unit };
  }
  // A scalar criterion cannot losslessly encode both ends of one range.
  if (fact.minValue !== undefined && fact.maxValue !== undefined) return null;
  return { ...identity, operator: 'exists' };
}

function criterionOptionLabel(fact: NormalizedProductFact, criterion: FactCriterion): string {
  const label = productFactLabel(fact);
  if (criterion.operator === 'exists' || criterion.value === true) return label;
  if (criterion.value === false) return `No ${label.toLowerCase()}`;
  const value = productFactValue(fact);
  if (!value) return label;
  return `${label}: ${value}`;
}

/** Curated, bounded model for the collapsed FilterSheet disclosure. */
export function publishedFactFilterOptions(
  rows: RateRow[],
  lookup: Record<string, ProductDetail> | null | undefined,
): PublishedFactFilterOption[] {
  if (!lookup) return [];
  const options = new Map<string, PublishedFactFilterOption>();
  const seenProducts = new Set<string>();
  for (const row of rows) {
    if (seenProducts.has(row.product_key)) continue;
    seenProducts.add(row.product_key);
    for (const fact of normalizedProductFacts(lookup[row.product_key])) {
      const criterion = optionCriterion(fact);
      if (!criterion) continue;
      const id = factCriterionId(criterion);
      if (!options.has(id)) options.set(id, { id, label: criterionOptionLabel(fact, criterion), criterion });
    }
  }
  return [...options.values()].sort((a, b) =>
    a.label.localeCompare(b.label, undefined, { sensitivity: 'base', numeric: true }),
  );
}

function selectedCriterionOption(criterion: FactCriterion): PublishedFactFilterOption {
  const id = factCriterionId(criterion);
  const rawLabel = criterion.sourceType
    ?? criterion.canonicalKey?.split('.').filter(Boolean).at(-1)
    ?? 'Published detail';
  const label = humanizeEnum(rawLabel) || 'Published detail';
  if (criterion.operator === 'exists' || criterion.value === true) return { id, label, criterion };
  if (criterion.value === false) return { id, label: `No ${label.toLowerCase()}`, criterion };
  const displayValue = productFactValue({
    id,
    kind: 'attribute',
    canonicalKey: criterion.canonicalKey ?? criterion.sourceType ?? 'published.detail',
    label,
    value: criterion.value,
    unit: criterion.unit,
  });
  return {
    id,
    label: displayValue ? `${label}: ${displayValue}` : label,
    criterion,
  };
}

/** Keep every applied criterion visible/removable, then fill the remaining
 * bounded disclosure capacity with available unselected options. */
export function boundedPublishedFactFilterOptions(
  options: readonly PublishedFactFilterOption[],
  selected: readonly FactCriterion[],
  limit = 32,
): PublishedFactFilterOption[] {
  const available = new Map(options.map((option) => [option.id, option]));
  const selectedOptions = selected.map((criterion) => {
    const id = factCriterionId(criterion);
    return available.get(id) ?? selectedCriterionOption(criterion);
  });
  const selectedIds = new Set(selectedOptions.map((option) => option.id));
  const remaining = options.filter((option) => !selectedIds.has(option.id));
  return [...selectedOptions, ...remaining.slice(0, Math.max(0, limit - selectedOptions.length))];
}

export interface ProductFactGroup {
  key: 'product' | 'features' | 'eligibility' | 'fees';
  title: string;
  facts: NormalizedProductFact[];
}

export interface ProductFactCluster {
  id: string;
  label: string;
  summary: string;
  facts: NormalizedProductFact[];
}

export interface ProductFactDisplayModel {
  groups: ProductFactGroup[];
  rateClusters: ProductFactCluster[];
}

const GROUPS: (Omit<ProductFactGroup, 'facts'> & { kinds: Set<NormalizedProductFactKind> })[] = [
  { key: 'product', title: 'Product facts', kinds: new Set(['rate', 'tier', 'bundle', 'attribute']) },
  { key: 'features', title: 'Features', kinds: new Set(['feature']) },
  { key: 'eligibility', title: 'Eligibility & limits', kinds: new Set(['eligibility', 'constraint', 'condition']) },
  { key: 'fees', title: 'Fees', kinds: new Set(['fee']) },
];

export function groupProductFacts(
  detail: ProductDetail | null | undefined,
  options?: { excludeFees?: boolean },
): ProductFactGroup[] {
  const facts = normalizedProductFacts(detail);
  return GROUPS.map((group) => ({
    key: group.key,
    title: group.title,
    facts: facts.filter((fact) => group.kinds.has(fact.kind) && !(options?.excludeFees && fact.kind === 'fee')),
  })).filter((group) => group.facts.length > 0);
}

function factAssociationId(
  fact: NormalizedProductFact,
  byId: Map<string, NormalizedProductFact>,
): string | null {
  if (fact.groupId) return `group:${fact.groupId}`;
  if (!fact.parentId) return null;
  const parent = byId.get(fact.parentId);
  return parent?.groupId ? `group:${parent.groupId}` : `parent:${fact.parentId}`;
}

function clusterLabel(facts: NormalizedProductFact[], index: number): string {
  const namedTier = facts.find((fact) => fact.kind === 'tier' && fact.label?.trim());
  return namedTier?.label?.trim() ?? `Rate option ${index + 1}`;
}

function clusterSummary(facts: NormalizedProductFact[]): string {
  const values = facts
    .filter((fact) => fact.kind === 'tier')
    .map(productFactValue)
    .filter((value): value is string => Boolean(value));
  const conditions = facts.filter((fact) => fact.kind === 'condition' && fact.condition?.trim()).length;
  const parts = [...new Set(values)].slice(0, 2);
  if (conditions) parts.push(`${conditions} condition${conditions === 1 ? '' : 's'}`);
  return parts.join(' · ') || 'Published tier details';
}

/**
 * Calm detail-page model. Rate/tier clusters stay associated and collapsed;
 * raw advertised/comparison rate facts remain searchable but are not repeated
 * beside the product hero and legacy ProductRatesList.
 */
export function productFactDisplayModel(
  detail: ProductDetail | null | undefined,
  options?: { excludeFees?: boolean },
): ProductFactDisplayModel {
  const facts = normalizedProductFacts(detail);
  const byId = new Map(facts.map((fact) => [fact.id, fact]));
  const associated = new Map<string, NormalizedProductFact[]>();
  for (const fact of facts) {
    const id = factAssociationId(fact, byId);
    if (!id) continue;
    const group = associated.get(id) ?? [];
    group.push(fact);
    associated.set(id, group);
  }
  const clusteredSignatures = new Set<string>();
  const rateClusters = [...associated.entries()]
    .filter(([, group]) => group.some((fact) => fact.kind === 'rate' || fact.kind === 'tier'))
    .map(([id, group], index) => {
      group.forEach((fact) => clusteredSignatures.add(productFactSignature(fact)));
      // The exact advertised/comparison figures already appear in the product
      // hero/rate list. Keep their tier relationship without repeating them.
      const displayFacts = group.filter(
        (fact) => fact.kind !== 'rate' && !(options?.excludeFees && fact.kind === 'fee'),
      );
      return {
        id,
        label: clusterLabel(group, index),
        summary: clusterSummary(group),
        facts: displayFacts,
      };
    })
    .filter((cluster) => cluster.facts.length > 0);

  const groups = groupProductFacts(detail, options)
    .map((group) => ({
      ...group,
      facts: group.facts.filter((fact) =>
        fact.kind !== 'rate' &&
        !(fact.kind === 'tier' && clusteredSignatures.has(productFactSignature(fact))) &&
        !clusteredSignatures.has(productFactSignature(fact)),
      ),
    }))
    .filter((group) => group.facts.length > 0 || (group.key === 'product' && rateClusters.length > 0));
  if (rateClusters.length > 0 && !groups.some((group) => group.key === 'product')) {
    groups.unshift({ key: 'product', title: 'Product facts', facts: [] });
  }
  return { groups, rateClusters };
}
