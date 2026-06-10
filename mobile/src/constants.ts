import type { SectionKey } from './types';

export interface SectionMeta {
  key: SectionKey;
  title: string;
  short: string;
  icon: string;
  lowerIsBetter: boolean;
  slug: string;
  blurb: string;
  accentColor: string;
}

export const SECTIONS: Record<SectionKey, SectionMeta> = {
  Mortgage: {
    key: 'Mortgage', title: 'Home loans', short: 'Home loans', icon: 'home', lowerIsBetter: true,
    slug: 'home-loans', blurb: 'Variable & fixed mortgage rates', accentColor: '#3b82f6',
  },
  Savings: {
    key: 'Savings', title: 'Savings accounts', short: 'Savings', icon: 'wallet', lowerIsBetter: false,
    slug: 'savings', blurb: 'At-call & bonus savings rates', accentColor: '#14b8a6',
  },
  TD: {
    key: 'TD', title: 'Term deposits', short: 'Term deposits', icon: 'time', lowerIsBetter: false,
    slug: 'term-deposits', blurb: 'Fixed-term deposit rates', accentColor: '#d97706',
  },
};

export const SECTION_ORDER: SectionKey[] = ['Mortgage', 'Savings', 'TD'];

export function sectionFromSlug(slug: string): SectionKey | undefined {
  return SECTION_ORDER.find((key) => SECTIONS[key].slug === slug);
}
