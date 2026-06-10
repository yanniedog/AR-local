import AsyncStorage from '@react-native-async-storage/async-storage';
import * as BackgroundFetch from 'expo-background-fetch';
import * as Network from 'expo-network';
import * as TaskManager from 'expo-task-manager';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import { SECTIONS } from '../constants';
import { RATE_MOVE_BPS_THRESHOLD } from '../config';
import type {
  CorePayload,
  DetailsPayload,
  Manifest,
  PayloadSource,
  ProductDetail,
  RateRow,
  SectionKey,
} from '../types';
import { cache, type CacheMeta } from './cache';
import type { PayloadProgressSnapshot } from './downloadProgress';
import { BACKGROUND_TASK, computeChanges, notify } from './notifications';
import {
  addSubscription,
  findSearchSubscription as lookupSearchSubscription,
  isProductSubscribed as productIsSubscribed,
  makeProductSubscription,
  makeSearchSubscription,
  productSubscriptionId,
  removeSubscription as dropSubscription,
  type FilterSnapshot,
  type Subscription,
} from './subscriptions';
import { type SearchIndexPayload, resetDetailSearchIndexCache } from './detailSearch';
import type { HistoryBanksPayload } from './historyPayload';
import { normalizeHistoryBanksPayload } from './historyPayload';
import { shouldWarmDetails } from './optionalPrefs';
import {
  downloadCore,
  downloadDetails,
  downloadHistoryBanks,
  downloadSearchIndex,
  fetchManifest,
} from './payload';
import { sampleCore, sampleDetails, sampleManifest } from './sample';

export { shouldWarmDetails } from './optionalPrefs';
import type { ThemeMode } from '../theme/theme';
import { debugLog } from '../lib/debugLog';
import { hapticRefreshComplete, hapticSelection } from '../lib/haptics';

export interface Prefs {
  themeMode: ThemeMode;
  defaultSection: SectionKey;
  notificationsEnabled: boolean;
  /** Session replay (Clarity) + crash/log reporting (Firebase Crashlytics). */
  diagnosticsEnabled: boolean;
  wifiOnly: boolean;
  includeNonStandard: boolean;
  /** Fulltext search across product info (off by default). */
  enableDeepSearch: boolean;
  /** Section ribbon time-series chart on Home (off by default). */
  showHistoryRibbon: boolean;
  onboarded: boolean;
  interests: SectionKey[];
  rateMoveThresholdBps: number;
}

export const DEFAULT_PREFS: Prefs = {
  themeMode: 'system',
  defaultSection: 'Mortgage',
  notificationsEnabled: false,
  diagnosticsEnabled: true,
  wifiOnly: false,
  includeNonStandard: false,
  enableDeepSearch: false,
  showHistoryRibbon: false,
  onboarded: false,
  interests: ['Mortgage', 'Savings', 'TD'],
  rateMoveThresholdBps: RATE_MOVE_BPS_THRESHOLD,
};

export type Status = 'idle' | 'loading' | 'ready' | 'error';

interface AppState {
  status: Status;
  refreshing: boolean;
  source: PayloadSource;
  manifest: Manifest | null;
  core: CorePayload | null;
  details: DetailsPayload | null;
  searchIndex: SearchIndexPayload | null;
  historyBanks: HistoryBanksPayload | null;
  /** Set when optional history payload download/parse fails (pref may stay on). */
  historyBanksError: string | null;
  detailsLoading: boolean;
  error: string | null;
  offline: boolean;
  lastCheckedAt: string | null;
  /** Live payload fetch metrics while upgrading from bundled sample. */
  payloadProgress: PayloadProgressSnapshot | null;
  /** True once persisted prefs/favorites have rehydrated from AsyncStorage. */
  hydrated: boolean;
  /** Last-selected product section; synced across Home and Browse. */
  activeSection: SectionKey;

  prefs: Prefs;
  favorites: string[];
  subscriptions: Subscription[];

  bootstrap: () => Promise<void>;
  retryDataLoad: () => Promise<void>;
  loadSampleFallback: () => Promise<void>;
  /** Load core/manifest from disk cache if not already in memory (used by the headless task). */
  ensureCoreLoaded: () => Promise<void>;
  refresh: (opts?: { force?: boolean; manual?: boolean }) => Promise<boolean>;
  ensureDetails: (opts?: { forProductView?: boolean }) => Promise<void>;
  ensureSearchIndex: () => Promise<void>;
  ensureHistoryBanks: () => Promise<void>;
  getDetail: (productKey: string) => ProductDetail | null;
  toggleFavorite: (key: string) => void;
  isFavorite: (key: string) => boolean;
  subscribeProduct: (productKey: string, rateIndex: number | null, labelRow: RateRow) => boolean;
  unsubscribeProduct: (productKey: string, rateIndex: number | null) => void;
  subscribeSearch: (input: {
    section: SectionKey;
    path: string[];
    hierarchyScoped: boolean;
    query: string;
    filters: FilterSnapshot;
  }) => boolean;
  unsubscribeSearch: (id: string) => void;
  removeSubscription: (id: string) => void;
  restoreSubscription: (sub: Subscription) => void;
  isProductSubscribed: (productKey: string, rateIndex: number | null) => boolean;
  findSearchSubscription: (input: {
    section: SectionKey;
    path: string[];
    hierarchyScoped: boolean;
    query: string;
    filters: FilterSnapshot;
  }) => Subscription | undefined;
  setPref: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void;
  setActiveSection: (section: SectionKey) => void;
  completeOnboarding: (interests: SectionKey[], notifications: boolean) => void;
  clearCache: () => Promise<void>;
}

async function onWifi(): Promise<boolean> {
  try {
    const state = await Network.getNetworkStateAsync();
    return state.type === Network.NetworkStateType.WIFI;
  } catch {
    return true; // assume ok if we can't tell
  }
}

async function readValidatedHistoryBanks(): Promise<HistoryBanksPayload | null> {
  const raw = await cache.readHistoryBanks();
  if (!raw) return null;
  const normalized = normalizeHistoryBanksPayload(raw);
  if (normalized) return normalized;
  debugLog.warn('store', 'discarding invalid cached history banks payload');
  await cache.clearHistoryBanks();
  return null;
}

async function installSampleSeed(): Promise<void> {
  const seedMeta: CacheMeta = {
    manifest: sampleManifest,
    source: 'sample',
    savedAt: new Date().toISOString(),
    coreSha: sampleManifest.files.core.sha256,
    detailsSha: null,
  };
  await cache.writeBundle(seedMeta, JSON.stringify(sampleCore));
}

export const useStore = create<AppState>()(
  persist(
    (set, get) => ({
      status: 'idle',
      refreshing: false,
      source: 'sample',
      manifest: null,
      core: null,
      details: null,
      searchIndex: null,
      historyBanks: null,
      historyBanksError: null,
      detailsLoading: false,
      error: null,
      offline: false,
      lastCheckedAt: null,
      payloadProgress: null,
      hydrated: false,
      activeSection: DEFAULT_PREFS.defaultSection,

      prefs: DEFAULT_PREFS,
      favorites: [],
      subscriptions: [],

      async bootstrap() {
        if (get().status === 'ready' || get().status === 'loading') return;
        debugLog.info('store', 'bootstrap');
        set({ status: 'loading', error: null });

        try {
          await useStore.persist?.rehydrate?.();
        } catch (err) {
          debugLog.warn('store', `prefs rehydrate failed: ${String((err as Error)?.message ?? err)}`);
        }

        try {
          const prefs = get().prefs;
          const bundle = await cache.readBundle();
          const [cachedSearch, cachedHistory] = await Promise.all([
            prefs.enableDeepSearch ? cache.readSearchIndex() : Promise.resolve(null),
            prefs.showHistoryRibbon ? readValidatedHistoryBanks() : Promise.resolve(null),
          ]);
          if (bundle) {
            debugLog.info('store', `cache hit run_date=${bundle.core.run_date} source=${bundle.meta.source}`);
            set({
              core: bundle.core,
              manifest: bundle.meta.manifest,
              source: bundle.meta.source,
              status: 'ready',
              error: null,
              ...(cachedSearch ? { searchIndex: cachedSearch } : {}),
              ...(cachedHistory ? { historyBanks: cachedHistory } : {}),
            });
          } else {
            debugLog.info('store', 'cache miss — seeding bundled sample');
            await installSampleSeed();
            set({
              core: sampleCore,
              manifest: sampleManifest,
              source: 'sample',
              status: 'ready',
              error: null,
            });
          }
        } catch (err) {
          const msg = String((err as Error)?.message ?? err);
          debugLog.error('store', `bootstrap failed: ${msg}`);
          set({ status: 'error', error: msg });
          return;
        }

        void get().refresh({});
      },

      async retryDataLoad() {
        debugLog.info('store', 'retryDataLoad');
        set({ status: 'idle', error: null });
        await get().bootstrap();
        if (get().status !== 'ready') return;
        await get().refresh({ force: true, manual: true });
      },

      async loadSampleFallback() {
        debugLog.info('store', 'loadSampleFallback');
        set({ status: 'loading', error: null, refreshing: false, payloadProgress: null });
        try {
          await installSampleSeed();
          set({
            core: sampleCore,
            manifest: sampleManifest,
            source: 'sample',
            status: 'ready',
            error: null,
            offline: true,
            details: null,
            searchIndex: null,
            historyBanks: null,
            historyBanksError: null,
          });
        } catch (err) {
          const msg = String((err as Error)?.message ?? err);
          debugLog.error('store', `loadSampleFallback failed: ${msg}`);
          set({ status: 'error', error: msg });
        }
      },

      async ensureCoreLoaded() {
        if (get().core) return;
        const bundle = await cache.readBundle();
        if (bundle) {
          set({ core: bundle.core, manifest: bundle.meta.manifest, source: bundle.meta.source });
        }
      },

      async refresh(opts = {}) {
        const { force = false, manual = false } = opts;
        // Warm details during refresh so subscriptions and change detection see products.
        const warmDetails = async () => {
          if (shouldWarmDetails(get().prefs, get().subscriptions)) {
            await get().ensureDetails();
          }
        };
        const warmOptionalAssets = () => {
          const p = get().prefs;
          if (p.enableDeepSearch) void get().ensureSearchIndex();
          if (p.showHistoryRibbon) void get().ensureHistoryBanks();
        };
        if (get().refreshing) return false;
        const prefs = get().prefs;
        if (prefs.wifiOnly && !manual && !(await onWifi())) {
          debugLog.debug('store', 'refresh skipped (wifi-only, not on Wi-Fi)');
          set({ lastCheckedAt: new Date().toISOString() });
          return false;
        }
        debugLog.info('store', `refresh start manual=${manual} force=${force}`);
        set({ refreshing: true });
        const onProgress = (snapshot: PayloadProgressSnapshot) => set({ payloadProgress: snapshot });
        try {
          const remote = await fetchManifest(undefined, onProgress);
          // Do NOT install the remote manifest yet — if the core download fails we'd
          // be left with a new manifest paired with the old core, poisoning the
          // metadata-only freshness check. Install it only once its core is in hand.
          set({ offline: false, lastCheckedAt: new Date().toISOString() });

          const meta = await cache.readMeta();
          const upToDate =
            !force &&
            meta?.source === 'remote' &&
            meta.manifest.run_date === remote.run_date &&
            meta.coreSha === remote.files.core.sha256;
          if (upToDate) {
            debugLog.debug('store', `refresh up-to-date run_date=${remote.run_date}`);
            // Core already matches on disk — adopt manifest and sync in-memory source
            // so the sample-connect banner dismisses after a successful refresh.
            const bundle = await cache.readBundle();
            set({
              manifest: remote,
              source: 'remote',
              offline: false,
              ...(bundle ? { core: bundle.core } : {}),
            });
            // Details may have been republished for the same run_date (e.g. corrected
            // fees) — ensureDetails re-checks the details sha.
            await warmDetails();
            warmOptionalAssets();
            return false;
          }

          const previousCore = get().core;
          const previousSource = get().source;
          let previousDetailsProducts = get().details?.products ?? null;
          if (!previousDetailsProducts && previousCore) {
            const cachedDetails = await cache.readDetails();
            if (cachedDetails && cachedDetails.run_date === previousCore.run_date) {
              previousDetailsProducts = cachedDetails.products ?? null;
              if (!get().details) set({ details: cachedDetails });
            }
          }
          const { text, core } = await downloadCore(
            remote.files.core.url,
            remote.files.core.sha256,
            {
              fileName: remote.files.core.name,
              expectedBytes: remote.files.core.bytes,
              onProgress,
            },
          );
          // A forced refresh (pull-to-refresh / "Refresh now") re-downloads the core
          // even when nothing changed. If the details payload is byte-identical to what
          // we already cached, keep the existing details + hash so a transient details
          // failure doesn't strip an offline user's fees/features.
          const detailsUnchanged = !!meta && meta.detailsSha === remote.files.details.sha256;
          // Atomic core+meta write: they can never end up mismatched on disk.
          await cache.writeBundle(
            {
              manifest: remote,
              source: 'remote',
              savedAt: new Date().toISOString(),
              coreSha: remote.files.core.sha256,
              detailsSha: detailsUnchanged ? remote.files.details.sha256 : null,
            },
            text,
          );
          set({
            core,
            manifest: remote,
            source: 'remote',
            status: 'ready',
            error: null,
            details: detailsUnchanged ? get().details : null,
          });

          // Local notifications on meaningful change — only when the baseline was a
          // previously-installed remote dataset, never the bundled sample (otherwise
          // the first live refresh would alert on sample-vs-real differences).
          // Warm details before diffing so detail-filtered search subscriptions see products.
          await warmDetails();
          warmOptionalAssets();

          if (prefs.notificationsEnabled && previousSource === 'remote') {
            const messages = computeChanges(
              previousCore,
              core,
              get().favorites,
              prefs.rateMoveThresholdBps,
              get().subscriptions,
              previousDetailsProducts,
              get().details?.products ?? null,
            );
            // Await so a headless background task doesn't resolve (and let the OS
            // suspend the app) before the notifications are actually scheduled.
            await notify(messages);
            debugLog.info('store', `notified ${messages.length} rate-change message(s)`);
          }
          debugLog.info('store', `refresh ok run_date=${core.run_date} changed=true`);
          return true;
        } catch (err) {
          const msg = String((err as Error)?.message ?? err);
          debugLog.error('store', `refresh failed: ${msg}`);
          const hasData = !!get().core;
          set({
            offline: true,
            status: hasData ? 'ready' : 'error',
            error: hasData ? null : msg,
            lastCheckedAt: new Date().toISOString(),
          });
          return false;
        } finally {
          set({ refreshing: false, payloadProgress: null });
          if (manual) hapticRefreshComplete();
        }
      },

      async ensureDetails(opts = {}) {
        const { forProductView = false } = opts;
        const { details, core, manifest, source, detailsLoading, prefs, subscriptions } = get();
        if (!core || detailsLoading) return;
        if (!forProductView && !shouldWarmDetails(prefs, subscriptions)) return;

        // Details are fresh only when run_date AND the manifest's details sha match.
        const wantSha = manifest?.files.details.sha256 ?? null;
        const meta = await cache.readMeta();
        const shaOk = !wantSha || meta?.detailsSha === wantSha;
        if (details && details.run_date === core.run_date && shaOk) return;

        // A concurrent refresh may swap core/manifest while we await reads/downloads
        // below; only install a result if the dataset we captured is still current.
        const datasetUnchanged = () => {
          const cur = get();
          return (
            cur.core?.run_date === core.run_date &&
            cur.manifest?.files.core.sha256 === manifest?.files.core.sha256 &&
            cur.manifest?.files.details.sha256 === manifest?.files.details.sha256
          );
        };

        set({ detailsLoading: true });
        try {
          const cached = await cache.readDetails();
          if (cached && cached.run_date === core.run_date && shaOk) {
            if (datasetUnchanged()) set({ details: cached });
            return;
          }
          if (source === 'remote' && manifest) {
            const { text, details: fresh } = await downloadDetails(
              manifest.files.details.url,
              manifest.files.details.sha256,
            );
            // Discard an obsolete download if a refresh swapped the dataset mid-flight.
            if (!datasetUnchanged()) return;
            await cache.writeDetails(text);
            // Re-check after the awaited write: a newer refresh may have installed its
            // core/meta while writeDetails was suspended — don't clobber it.
            if (!datasetUnchanged()) return;
            // Persist the manifest these details belong to (not the stale on-disk
            // meta), so an offline cold launch treats the cached details as fresh.
            // updateMeta preserves the cached core in the same atomic bundle.
            await cache.updateMeta({
              manifest,
              source: 'remote',
              savedAt: new Date().toISOString(),
              coreSha: manifest.files.core.sha256,
              detailsSha: manifest.files.details.sha256,
            });
            // Final re-check after the awaited writeMeta, before touching state.
            if (!datasetUnchanged()) return;
            set({ details: fresh });
            return;
          }
          // Only fall back to the bundled sample when we are *still* on sample data
          // (re-read source — a refresh may have switched us to remote mid-flight).
          if (get().source === 'sample') set({ details: sampleDetails as DetailsPayload });
        } catch (err) {
          debugLog.warn('store', `ensureDetails failed: ${String((err as Error)?.message ?? err)}`);
          // A live details download failed: leave details unavailable rather than
          // show stale sample fees/features next to current rates. Only use the
          // bundled sample when the rest of the data is also the sample.
          if (get().source === 'sample') set({ details: sampleDetails as DetailsPayload });
        } finally {
          set({ detailsLoading: false });
          // If a concurrent refresh moved the dataset past what this invocation
          // captured (a new run OR a same-run core/details correction), our result was
          // discarded — schedule a load for the now-current dataset. Bounded: it only
          // re-runs while the manifest keeps changing, and the top-of-function freshness
          // check no-ops once details are current.
          const cur = get();
          const movedOn =
            cur.core?.run_date !== core.run_date ||
            cur.manifest?.files.core.sha256 !== manifest?.files.core.sha256 ||
            cur.manifest?.files.details.sha256 !== manifest?.files.details.sha256;
          if (cur.core && movedOn) void get().ensureDetails(opts);
        }
      },

      async ensureSearchIndex() {
        if (!get().prefs.enableDeepSearch) return;
        const { core, manifest, source, searchIndex } = get();
        if (!core || !manifest?.files.search_index) return;
        const asset = manifest.files.search_index;
        const meta = await cache.readMeta();
        if (searchIndex && searchIndex.run_date === core.run_date && meta?.searchIndexSha === asset.sha256) {
          return;
        }
        const cached = await cache.readSearchIndex();
        if (cached && cached.run_date === core.run_date && meta?.searchIndexSha === asset.sha256) {
          set({ searchIndex: cached });
          return;
        }
        if (source !== 'remote') return;
        try {
          const { text, searchIndex: fresh } = await downloadSearchIndex(asset.url, asset.sha256);
          await cache.writeSearchIndex(text);
          await cache.updateMeta({
            manifest,
            source: 'remote',
            savedAt: new Date().toISOString(),
            coreSha: manifest.files.core.sha256,
            searchIndexSha: asset.sha256,
          });
          set({ searchIndex: fresh });
        } catch (err) {
          debugLog.warn('store', `ensureSearchIndex failed: ${String((err as Error)?.message ?? err)}`);
        }
      },

      async ensureHistoryBanks() {
        if (!get().prefs.showHistoryRibbon) return;
        debugLog.info('store', 'ensureHistoryBanks start');
        const { core, manifest, source, historyBanks } = get();
        if (!core) {
          debugLog.debug('store', 'ensureHistoryBanks skipped (no core)');
          return;
        }
        if (!manifest?.files.history_banks) {
          debugLog.debug('store', 'ensureHistoryBanks skipped (manifest has no history_banks)');
          set({ historyBanks: null, historyBanksError: null });
          return;
        }
        const asset = manifest.files.history_banks;
        const meta = await cache.readMeta();
        if (historyBanks && historyBanks.run_date === core.run_date && meta?.historyBanksSha === asset.sha256) {
          set({ historyBanksError: null });
          return;
        }
        const cached = await readValidatedHistoryBanks();
        if (cached && cached.run_date === core.run_date && meta?.historyBanksSha === asset.sha256) {
          set({ historyBanks: cached, historyBanksError: null });
          return;
        }
        if (source !== 'remote') {
          set({ historyBanks: null, historyBanksError: null });
          return;
        }
        try {
          const { text, historyBanks: fresh } = await downloadHistoryBanks(asset.url, asset.sha256);
          const validated = normalizeHistoryBanksPayload(fresh);
          if (!validated) {
            debugLog.error('store', 'ensureHistoryBanks rejected payload after download (validation failed)');
            set({ historyBanks: null, historyBanksError: 'history_banks payload failed validation' });
            return;
          }
          await cache.writeHistoryBanks(text);
          await cache.updateMeta({
            manifest,
            source: 'remote',
            savedAt: new Date().toISOString(),
            coreSha: manifest.files.core.sha256,
            historyBanksSha: asset.sha256,
          });
          set({ historyBanks: validated, historyBanksError: null });
          debugLog.info('store', `ensureHistoryBanks ok run_date=${validated.run_date}`);
        } catch (err) {
          const msg = String((err as Error)?.message ?? err);
          debugLog.error('store', `ensureHistoryBanks failed: ${msg}`);
          set({ historyBanks: null, historyBanksError: msg });
        }
      },

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

      subscribeProduct(productKey, rateIndex, labelRow) {
        if (productIsSubscribed(get().subscriptions, productKey, rateIndex)) return false;
        set({
          subscriptions: addSubscription(
            get().subscriptions,
            makeProductSubscription(labelRow, rateIndex),
          ),
        });
        return true;
      },

      unsubscribeProduct(productKey, rateIndex) {
        const id = productSubscriptionId(productKey, rateIndex);
        set({ subscriptions: dropSubscription(get().subscriptions, id) });
      },

      subscribeSearch(input) {
        if (lookupSearchSubscription(get().subscriptions, input)) return false;
        set({
          subscriptions: addSubscription(get().subscriptions, makeSearchSubscription(input)),
        });
        return true;
      },

      unsubscribeSearch(id) {
        get().removeSubscription(id);
      },

      removeSubscription(id) {
        set({ subscriptions: dropSubscription(get().subscriptions, id) });
      },

      restoreSubscription(sub) {
        if (get().subscriptions.some((s) => s.id === sub.id)) return;
        set({ subscriptions: addSubscription(get().subscriptions, sub) });
      },

      isProductSubscribed(productKey, rateIndex) {
        return productIsSubscribed(get().subscriptions, productKey, rateIndex);
      },

      findSearchSubscription(input) {
        return lookupSearchSubscription(get().subscriptions, input);
      },

      setActiveSection(section) {
        set({ activeSection: section });
      },

      setPref(key, value) {
        set({ prefs: { ...get().prefs, [key]: value } });
        if (key === 'enableDeepSearch') {
          if (value) {
            void get().ensureSearchIndex();
            void get().ensureDetails();
          } else {
            set({ searchIndex: null });
          }
        }
        if (key === 'showHistoryRibbon') {
          if (value) {
            set({ historyBanksError: null });
            void get().ensureHistoryBanks();
          } else {
            set({ historyBanks: null, historyBanksError: null });
          }
        }
      },

      completeOnboarding(interests, notifications) {
        const defaultSection = interests[0] ?? get().prefs.defaultSection;
        set({
          activeSection: defaultSection,
          prefs: {
            ...get().prefs,
            onboarded: true,
            interests: interests.length ? interests : DEFAULT_PREFS.interests,
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
          manifest: null,
          status: 'idle',
          source: 'sample',
        });
        await get().bootstrap();
      },
    }),
    {
      name: 'ar-rates',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (s) => {
        const { showHistoryRibbon: _sessionOnly, ...prefsToPersist } = s.prefs;
        return {
          prefs: prefsToPersist,
          favorites: s.favorites,
          subscriptions: s.subscriptions,
          activeSection: s.activeSection,
        };
      },
      merge: (persisted, current) => {
        const p = persisted as Partial<AppState> | undefined;
        const prefs = { ...DEFAULT_PREFS, ...p?.prefs, showHistoryRibbon: false };
        const persistedActiveSection = p?.activeSection;
        const isValidActiveSection =
          typeof persistedActiveSection === 'string' &&
          Object.prototype.hasOwnProperty.call(SECTIONS, persistedActiveSection);
        const activeSection = isValidActiveSection ? persistedActiveSection : prefs.defaultSection;
        return {
          ...current,
          ...p,
          prefs,
          activeSection,
        };
      },
      // Flip `hydrated` once persisted state is restored, so the initial route
      // doesn't redirect returning users to onboarding before prefs load.
      onRehydrateStorage: () => () => {
        useStore.setState({ hydrated: true });
      },
    },
  ),
);

// OS-scheduled background refresh. Defined here (not in notifications.ts) so it can
// rehydrate persisted prefs/favorites and call refresh() directly — important when
// the app is launched headless (terminated) and the UI never mounted.
try {
  if (typeof TaskManager.isTaskDefined === 'function' && !TaskManager.isTaskDefined(BACKGROUND_TASK)) {
    TaskManager.defineTask(BACKGROUND_TASK, async () => {
      try {
        try {
          await useStore.persist?.rehydrate?.();
        } catch {
          // proceed with defaults if rehydrate fails
        }
        // persist excludes core/manifest — load them from disk so the diff has a
        // baseline and rate-change notifications fire on terminated-app runs.
        await useStore.getState().ensureCoreLoaded();
        const state = useStore.getState();
        if (shouldWarmDetails(state.prefs, state.subscriptions)) {
          await state.ensureDetails();
        }
        if (state.prefs.enableDeepSearch) await state.ensureSearchIndex();
        if (state.prefs.showHistoryRibbon) await state.ensureHistoryBanks();
        const changed = await useStore.getState().refresh({});
        return changed
          ? BackgroundFetch.BackgroundFetchResult.NewData
          : BackgroundFetch.BackgroundFetchResult.NoData;
      } catch {
        return BackgroundFetch.BackgroundFetchResult.Failed;
      }
    });
  }
} catch {
  // TaskManager unavailable (e.g. web / test env) — background refresh is optional.
}
