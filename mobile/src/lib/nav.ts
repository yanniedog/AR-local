import { router } from 'expo-router';

import { SECTIONS } from '../constants';
import type { SectionKey } from '../types';

export const openProduct = (productKey: string) =>
  router.push(`/product/${encodeURIComponent(productKey)}`);

export const openBank = (provider: string) =>
  router.push(`/bank/${encodeURIComponent(provider)}`);

export const openBrowse = (section: SectionKey) =>
  router.push(`/browse?section=${SECTIONS[section].slug}`);

export const openCompare = (keys: string[]) =>
  router.push(`/compare?keys=${encodeURIComponent(keys.join(','))}`);
