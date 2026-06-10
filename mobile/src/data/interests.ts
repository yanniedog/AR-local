import type { SegOption } from '../components/controls';
import { SECTION_ORDER } from '../constants';
import type { SectionKey } from '../types';

export const DEFAULT_INTERESTS: SectionKey[] = ['Mortgage', 'Savings', 'TD'];

/** Short labels for section segmented controls (Home, Browse). */
export const SECTION_SEG_LABELS: Record<SectionKey, string> = {
  Mortgage: 'Mortgage',
  Savings: 'Savings',
  TD: 'Term Deposits',
};

const VALID = new Set<SectionKey>(SECTION_ORDER);

/** Dedupe, drop unknown keys, fall back to defaults when empty. */
export function normalizeInterests(interests: SectionKey[]): SectionKey[] {
  const out: SectionKey[] = [];
  const seen = new Set<SectionKey>();
  for (const key of interests) {
    if (!VALID.has(key) || seen.has(key)) continue;
    seen.add(key);
    out.push(key);
  }
  return out.length ? out : [...DEFAULT_INTERESTS];
}

export function orderedInterestSections(interests: SectionKey[]): SectionKey[] {
  return normalizeInterests(interests);
}

export function sectionSegmentOptions(interests: SectionKey[]): SegOption<SectionKey>[] {
  return orderedInterestSections(interests).map((key) => ({
    value: key,
    label: SECTION_SEG_LABELS[key],
  }));
}

export function toggleInterest(current: SectionKey[], key: SectionKey): SectionKey[] {
  const ordered = normalizeInterests(current);
  if (ordered.includes(key)) {
    if (ordered.length === 1) return ordered;
    return ordered.filter((k) => k !== key);
  }
  return [...ordered, key];
}

export function moveInterest(
  current: SectionKey[],
  key: SectionKey,
  direction: 'up' | 'down',
): SectionKey[] {
  const ordered = [...normalizeInterests(current)];
  const idx = ordered.indexOf(key);
  if (idx < 0) return ordered;
  const swap = direction === 'up' ? idx - 1 : idx + 1;
  if (swap < 0 || swap >= ordered.length) return ordered;
  [ordered[idx], ordered[swap]] = [ordered[swap], ordered[idx]];
  return ordered;
}

export function resolveInterestSection(
  interests: SectionKey[],
  preferred?: SectionKey,
): SectionKey {
  const ordered = orderedInterestSections(interests);
  if (preferred && ordered.includes(preferred)) return preferred;
  return ordered[0];
}
