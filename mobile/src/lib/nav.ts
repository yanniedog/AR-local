import { router, type Href } from 'expo-router';

import { SECTIONS } from '../constants';
import { useStore } from '../data/store';
import type { SortKey } from '../data/selectors';
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

const browseDrillParams = (section: SectionKey, path: string[] = []) => ({
  section: SECTIONS[section].slug,
  ...(path.length ? { path: path.join('.') } : {}),
});

/** Switch to Browse tab and drill to a taxonomy node (replaces stacked /node pushes). */
export const openBrowseDrill = (section: SectionKey, path: string[] = []) => {
  useStore.getState().setActiveSection(section);
  router.navigate({
    pathname: '/browse',
    params: browseDrillParams(section, path),
  } as unknown as Href);
};

export const openBrowse = (section: SectionKey) => openBrowseDrill(section, []);

export const openHierarchy = (section: SectionKey, path: string[] = []) =>
  router.push({
    pathname: '/hierarchy',
    params: { section: SECTIONS[section].slug, ...(path.length ? { path: path.join('.') } : {}) },
  } as unknown as Href);

/** @deprecated Use openBrowseDrill — drills inside Browse tab instead of stacking /node. */
export const openNode = (section: SectionKey, path: string[]) => openBrowseDrill(section, path);

export const openSearch = (section: SectionKey, sort?: SortKey) =>
  router.push({ pathname: '/search', params: { section, ...(sort ? { sort } : {}) } });

// Flat, searchable/sortable product list — optionally scoped to a taxonomy node.
export const openProductsList = (section: SectionKey, path: string[] = [], sort?: SortKey) =>
  router.push({ pathname: '/search', params: { section, path: path.join('.'), ...(sort ? { sort } : {}) } });

export const openRibbonProducts = (section: SectionKey, sort: SortKey) =>
  router.push({ pathname: '/search', params: { section, sort, scope: 'hierarchy' } });

// Product keys can contain commas, so serialize the array unambiguously (JSON)
// rather than comma-joining.
export const openCompare = (keys: string[]) =>
  router.push({ pathname: '/compare', params: { keys: JSON.stringify(keys) } });
