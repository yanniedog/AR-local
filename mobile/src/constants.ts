import type { SectionKey } from './types';

export interface SectionMeta {
  key: SectionKey;
  /** Plural product label for headings. */
  title: string;
  /** Short tab/segment label. */
  short: string;
  /** Ionicons name. */
  icon: string;
  /** True when lower rates are better (loans); false when higher is better (deposits). */
  lowerIsBetter: boolean;
  /** Route slug used in URLs. */
  slug: string;
  blurb: string;
}

export const SECTIONS: Record<SectionKey, SectionMeta> = {
  Mortgage: {
    key: 'Mortgage',
    title: 'Home loans',
    short: 'Home loans',
    icon: 'home',
    lowerIsBetter: true,
    slug: 'home-loans',
    blurb: 'Variable & fixed mortgage rates',
  },
  Savings: {
    key: 'Savings',
    title: 'Savings accounts',
    short: 'Savings',
    icon: 'wallet',
    lowerIsBetter: false,
    slug: 'savings',
    blurb: 'At-call & bonus savings rates',
  },
  TD: {
    key: 'TD',
    title: 'Term deposits',
    short: 'Term deposits',
    icon: 'time',
    lowerIsBetter: false,
    slug: 'term-deposits',
    blurb: 'Fixed-term deposit rates',
  },
};

export const SECTION_ORDER: SectionKey[] = ['Mortgage', 'Savings', 'TD'];

export function sectionFromSlug(slug: string): SectionKey | undefined {
  return SECTION_ORDER.find((key) => SECTIONS[key].slug === slug);
}
