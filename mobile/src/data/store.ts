import AsyncStorage from '@react-native-async-storage/async-storage';
import * as BackgroundFetch from 'expo-background-fetch';
import * as Network from 'expo-network';
import * as TaskManager from 'expo-task-manager';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

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
import { downloadCore, downloadDetails, fetchManifest } from './payload';
import { sampleCore, sampleDetails, sampleManifest } from './sample';
import type { ThemeMode } from '../theme/theme';

export interface Prefs {
  themeMode: ThemeMode;
  defaultSection: SectionKey;
  notificationsEnabled: boolean;
  wifiOnly: boolean;
  includeNonStandard: boolean;
  onboarded: boolean;
  interests: SectionKey[];
  rateMoveThresholdBps: number;
}

const DEFAULT_PREFS: Prefs = {
  themeMode: 'system',
  defaultSection: 'Mortgage',
  notificationsEnabled: false,
  wifiOnly: false,
  includeNonStandard: false,
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
  detailsLoading: boolean;
  error: string | null;
  offline: boolean;
  lastCheckedAt: string | null;
  /** Live payload fetch metrics while upgrading from bundled sample. */
  payloadProgress: PayloadProgressSnapshot | null;
  /** True once persisted prefs/favorites have rehydrated from AsyncStorage. */
  hydrated: boolean;

  prefs: Prefs;
  favorites: string[];
  subscriptions: Subscription[];

  bootstrap: () => Promise<void>;
  /** Load core/manifest from disk cache if not already in memory (used by the headless task). */
  ensureCoreLoaded: () => Promise<void>;
  refresh: (opts?: { force?: boolean; manual?: boolean }) => Promise<boolean>;
  ensureDetails: () => Promise<void>;
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
  isProductSubscribed: (productKey: string, rateIndex: number | null) => boolean;
  findSearchSubscription: (input: {
    section: SectionKey;
    path: string[];
    hierarchyScoped: boolean;
    query: string;
    filters: FilterSnapshot;
  }) => Subscription | undefined;
  setPref: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void;
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

export const useStore = create<AppState>()(
  persist(
    (set, get) => ({
      status: 'idle',
      refreshing: false,
      source: 'sample',
      manifest: null,
      core: null,
      details: null,
      detailsLoading: false,
      error: null,
      offline: false,
      lastCheckedAt: null,
      payloadProgress: null,
      hydrated: false,

      prefs: DEFAULT_PREFS,
      favorites: [],
      subscriptions: [],

      async bootstrap() {
        if (get().status === 'ready' || get().status === 'loading') return;
        set({ status: 'loading' });

        // Restore persisted prefs before the automatic refresh below, so a returning
        // user's wifiOnly / notification settings are honoured on the first refresh
        // instead of racing against async hydration with the defaults.
        try {
          await useStore.persist?.rehydrate?.();
        } catch {
          // proceed with defaults if rehydrate fails
        }

        // Core + meta are persisted atomically in one bundle, so they always agree.
        const bundle = await cache.readBundle();
        if (bundle) {
          set({
            core: bundle.core,
            manifest: bundle.meta.manifest,
            source: bundle.meta.source,
            status: 'ready',
          });
        } else {
          // Seed from the bundled sample so the app is instantly usable offline.
          const seedMeta: CacheMeta = {
            manifest: sampleManifest,
            source: 'sample',
            savedAt: new Date().toISOString(),
            coreSha: sampleManifest.files.core.sha256,
            detailsSha: null,
          };
          await cache.writeBundle(seedMeta, JSON.stringify(sampleCore));
          set({
            core: sampleCore,
            manifest: sampleManifest,
            source: 'sample',
            status: 'ready',
          });
        }

        // Try the network in the background; never blocks first paint.
        void get().refresh({});
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
          await get().ensureDetails();
        };
        if (get().refreshing) return false;
        const prefs = get().prefs;
        if (prefs.wifiOnly && !manual && !(await onWifi())) {
          set({ lastCheckedAt: new Date().toISOString() });
          return false;
        }
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
            details: detailsUnchanged ? get().details : null,
          });

          // Local notifications on meaningful change — only when the baseline was a
          // previously-installed remote dataset, never the bundled sample (otherwise
          // the first live refresh would alert on sample-vs-real differences).
          // Warm details before diffing so detail-filtered search subscriptions see products.
          await warmDetails();

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
          }
          return true;
        } catch (err) {
          // Keep whatever data we already have; just flag offline.
          const hasData = !!get().core;
          set({
            offline: true,
            status: hasData ? 'ready' : 'error',
            error: hasData ? null : String((err as Error)?.message ?? err),
            lastCheckedAt: new Date().toISOString(),
          });
          return false;
        } finally {
          set({ refreshing: false, payloadProgress: null });
        }
      },

      async ensureDetails() {
        const { details, core, manifest, source, detailsLoading } = get();
        if (!core || detailsLoading) return;

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
        } catch {
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
          if (cur.core && movedOn) void get().ensureDetails();
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

      isProductSubscribed(productKey, rateIndex) {
        return productIsSubscribed(get().subscriptions, productKey, rateIndex);
      },

      findSearchSubscription(input) {
        return lookupSearchSubscription(get().subscriptions, input);
      },

      setPref(key, value) {
        set({ prefs: { ...get().prefs, [key]: value } });
      },

      completeOnboarding(interests, notifications) {
        set({
          prefs: {
            ...get().prefs,
            onboarded: true,
            interests: interests.length ? interests : DEFAULT_PREFS.interests,
            defaultSection: interests[0] ?? get().prefs.defaultSection,
            notificationsEnabled: notifications,
          },
        });
      },

      async clearCache() {
        await cache.clear();
        set({ core: null, details: null, manifest: null, status: 'idle', source: 'sample' });
        await get().bootstrap();
      },
    }),
    {
      name: 'ar-rates',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (s) => ({ prefs: s.prefs, favorites: s.favorites, subscriptions: s.subscriptions }),
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
        await useStore.getState().ensureDetails();
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
