import { router } from 'expo-router';

import { SECTIONS } from '../constants';
import type { SectionKey } from '../types';

// Use expo-router's object form so it handles param encoding/decoding. Passing
// pre-encoded strings caused double-decode crashes for keys containing '%' and
// ambiguous splits for keys containing ','. useLocalSearchParams returns the
// original (decoded) values on the other side.
export const openProduct = (productKey: string, rateIndex?: number) =>
  router.push({
    pathname: '/product/[key]',
    params: { key: productKey, ...(rateIndex != null ? { ri: String(rateIndex) } : {}) },
  });

export const openBank = (provider: string) =>
  router.push({ pathname: '/bank/[provider]', params: { provider } });

export const openBrowse = (section: SectionKey) =>
  router.push({ pathname: '/browse', params: { section: SECTIONS[section].slug } });

// Product keys can contain commas, so serialize the array unambiguously (JSON)
// rather than comma-joining.
export const openCompare = (keys: string[]) =>
  router.push({ pathname: '/compare', params: { keys: JSON.stringify(keys) } });
