import type { SectionKey } from '../types';
import { cache } from './cache';
import { resetDetailSearchIndexCache } from './detailSearch';
import {
  addSubscription,
  findSearchSubscription as lookupSearchSubscription,
  isProductSubscribed as productIsSubscribed,
  makeProductSubscription,
  makeSearchSubscription,
  productSubscriptionId,
  removeSubscription as dropSubscription,
  type Subscription,
} from './subscriptions';
import { DEFAULT_INTERESTS, normalizeInterests, resolveInterestSection } from './interests';
import { normalizeProfileFilters } from './profile';
import { normalizeCalcInputs } from './calc';
import { debugLog } from '../lib/debugLog';
import { hapticSelection } from '../lib/haptics';
import type { AppState, Prefs, StoreGet, StoreSet } from './storeTypes';

export function createUserActions(set: StoreSet, get: StoreGet) {
  return {
    getDetail(productKey: string) {
      return get().details?.products?.[productKey] ?? null;
    },

    toggleFavorite(key: string) {
      const favorites = get().favorites;
      set({
        favorites: favorites.includes(key)
          ? favorites.filter((k) => k !== key)
          : [...favorites, key],
      });
      hapticSelection();
    },

    isFavorite(key: string) {
      return get().favorites.includes(key);
    },

    subscribeProduct(productKey: string, rateIndex: number | null, labelRow: Parameters<AppState['subscribeProduct']>[2]) {
      if (productIsSubscribed(get().subscriptions, productKey, rateIndex)) return false;
      set({
        subscriptions: addSubscription(
          get().subscriptions,
          makeProductSubscription(labelRow, rateIndex),
        ),
      });
      return true;
    },

    unsubscribeProduct(productKey: string, rateIndex: number | null) {
      const id = productSubscriptionId(productKey, rateIndex);
      set({ subscriptions: dropSubscription(get().subscriptions, id) });
    },

    subscribeSearch(input: Parameters<AppState['subscribeSearch']>[0]) {
      if (lookupSearchSubscription(get().subscriptions, input)) return false;
      set({
        subscriptions: addSubscription(get().subscriptions, makeSearchSubscription(input)),
      });
      return true;
    },

    unsubscribeSearch(id: string) {
      get().removeSubscription(id);
    },

    removeSubscription(id: string) {
      set({ subscriptions: dropSubscription(get().subscriptions, id) });
    },

    restoreSubscription(sub: Subscription) {
      if (get().subscriptions.some((s) => s.id === sub.id)) return;
      set({ subscriptions: addSubscription(get().subscriptions, sub) });
    },

    isProductSubscribed(productKey: string, rateIndex: number | null) {
      return productIsSubscribed(get().subscriptions, productKey, rateIndex);
    },

    findSearchSubscription(input: Parameters<AppState['findSearchSubscription']>[0]) {
      return lookupSearchSubscription(get().subscriptions, input);
    },

    setActiveSection(section: SectionKey) {
      set({ activeSection: resolveInterestSection(get().prefs.interests, section) });
    },

    setPref<K extends keyof Prefs>(key: K, value: Prefs[K]) {
      if (key === 'interests') {
        const interests = normalizeInterests(value as SectionKey[]);
        const prefs = { ...get().prefs, interests };
        if (!interests.includes(prefs.defaultSection)) {
          prefs.defaultSection = interests[0];
        }
        set({
          prefs,
          activeSection: resolveInterestSection(interests, get().activeSection),
        });
      } else if (key === 'defaultSection') {
        const section = value as SectionKey;
        const interests = normalizeInterests(get().prefs.interests);
        set({
          prefs: {
            ...get().prefs,
            defaultSection: interests.includes(section) ? section : interests[0],
          },
        });
      } else {
        set({ prefs: { ...get().prefs, [key]: value } });
      }
      if (key === 'enableDeepSearch') {
        if (value) {
          void get().ensureSearchIndex();
          void get().ensureDetails();
        } else {
          set({ searchIndex: null });
        }
      }
      if (key === 'showHistoryRibbon') {
        set({ historyBanksError: null });
      }
    },

    completeOnboarding(interests: SectionKey[], notifications: boolean) {
      const normalized = normalizeInterests(interests);
      const defaultSection = normalized[0];
      set({
        activeSection: defaultSection,
        prefs: {
          ...get().prefs,
          onboarded: true,
          interests: normalized,
          defaultSection,
          notificationsEnabled: notifications,
        },
      });
    },

    async clearCache() {
      debugLog.info('store', 'clearCache');
      await cache.clear();
      resetDetailSearchIndexCache();
      set({
        core: null,
        details: null,
        searchIndex: null,
        historyBanks: null,
        historyBanksError: null,
        bankInsights: null,
        bankInsightsError: null,
        productHistory: null,
        productHistoryError: null,
        manifest: null,
        status: 'idle',
        source: 'sample',
      });
      await get().bootstrap();
    },

    clearRefreshOutcome() {
      set({ refreshOutcome: null });
    },
  } satisfies Pick<
    AppState,
    | 'getDetail'
    | 'toggleFavorite'
    | 'isFavorite'
    | 'subscribeProduct'
    | 'unsubscribeProduct'
    | 'subscribeSearch'
    | 'unsubscribeSearch'
    | 'removeSubscription'
    | 'restoreSubscription'
    | 'isProductSubscribed'
    | 'findSearchSubscription'
    | 'setPref'
    | 'setActiveSection'
    | 'completeOnboarding'
    | 'clearCache'
    | 'clearRefreshOutcome'
  >;
}
