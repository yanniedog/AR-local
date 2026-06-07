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
  SectionKey,
} from '../types';
import { cache, type CacheMeta } from './cache';
import { BACKGROUND_TASK, computeChanges, notify } from './notifications';
import { downloadCore, downloadDetails, fetchManifest } from './payload';
import { sampleCore, sampleDetails, sampleManifest } from './sample';
import type { ThemeMode } from '../theme/theme';

export interface Prefs {
  themeMode: ThemeMode;
  defaultSection: SectionKey;
  notificationsEnabled: boolean;
  wifiOnly: boolean;
  onboarded: boolean;
  interests: SectionKey[];
  rateMoveThresholdBps: number;
}

const DEFAULT_PREFS: Prefs = {
  themeMode: 'system',
  defaultSection: 'Mortgage',
  notificationsEnabled: false,
  wifiOnly: false,
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
  /** True once persisted prefs/favorites have rehydrated from AsyncStorage. */
  hydrated: boolean;

  prefs: Prefs;
  favorites: string[];

  bootstrap: () => Promise<void>;
  /** Load core/manifest from disk cache if not already in memory (used by the headless task). */
  ensureCoreLoaded: () => Promise<void>;
  refresh: (opts?: { force?: boolean; manual?: boolean }) => Promise<boolean>;
  ensureDetails: () => Promise<void>;
  getDetail: (productKey: string) => ProductDetail | null;
  toggleFavorite: (key: string) => void;
  isFavorite: (key: string) => boolean;
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
      hydrated: false,

      prefs: DEFAULT_PREFS,
      favorites: [],

      async bootstrap() {
        if (get().status === 'ready' || get().status === 'loading') return;
        set({ status: 'loading' });

        const meta = await cache.readMeta();
        const cachedCore = await cache.readCore();
        if (meta && cachedCore) {
          set({
            core: cachedCore,
            manifest: meta.manifest,
            source: meta.source,
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
          await cache.writeCore(JSON.stringify(sampleCore));
          await cache.writeMeta(seedMeta);
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
        const meta = await cache.readMeta();
        const cachedCore = await cache.readCore();
        if (meta && cachedCore) {
          set({ core: cachedCore, manifest: meta.manifest, source: meta.source });
        }
      },

      async refresh(opts = {}) {
        const { force = false, manual = false } = opts;
        if (get().refreshing) return false;
        const prefs = get().prefs;
        if (prefs.wifiOnly && !manual && !(await onWifi())) {
          set({ lastCheckedAt: new Date().toISOString() });
          return false;
        }
        set({ refreshing: true });
        try {
          const remote = await fetchManifest();
          set({ offline: false, manifest: remote, lastCheckedAt: new Date().toISOString() });

          const meta = await cache.readMeta();
          const upToDate =
            !force &&
            meta?.source === 'remote' &&
            meta.manifest.run_date === remote.run_date &&
            meta.coreSha === remote.files.core.sha256;
          if (upToDate) {
            set({ refreshing: false });
            // Core is unchanged, but details may have been republished for the same
            // run_date (e.g. corrected fees) — ensureDetails re-checks the details sha.
            void get().ensureDetails();
            return false;
          }

          const previousCore = get().core;
          const { text, core } = await downloadCore(remote.files.core.url, remote.files.core.sha256);
          await cache.writeCore(text);
          await cache.writeMeta({
            manifest: remote,
            source: 'remote',
            savedAt: new Date().toISOString(),
            coreSha: remote.files.core.sha256,
            detailsSha: null,
          });
          set({ core, source: 'remote', status: 'ready', details: null });

          // Local notifications on meaningful change.
          if (prefs.notificationsEnabled) {
            const messages = computeChanges(
              previousCore,
              core,
              get().favorites,
              prefs.rateMoveThresholdBps,
            );
            void notify(messages);
          }

          // Warm details in the background.
          void get().ensureDetails();
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
          set({ refreshing: false });
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

        set({ detailsLoading: true });
        try {
          const cached = await cache.readDetails();
          if (cached && cached.run_date === core.run_date && shaOk) {
            set({ details: cached });
            return;
          }
          if (source === 'remote' && manifest) {
            const { text, details: fresh } = await downloadDetails(
              manifest.files.details.url,
              manifest.files.details.sha256,
            );
            await cache.writeDetails(text);
            if (meta) await cache.writeMeta({ ...meta, detailsSha: manifest.files.details.sha256 });
            set({ details: fresh });
            return;
          }
          // Only fall back to the bundled sample when we are actually on sample data.
          if (source === 'sample') set({ details: sampleDetails as DetailsPayload });
        } catch {
          // A live details download failed: leave details unavailable rather than
          // show stale sample fees/features next to current rates. Only use the
          // bundled sample when the rest of the data is also the sample.
          if (source === 'sample') set({ details: sampleDetails as DetailsPayload });
        } finally {
          set({ detailsLoading: false });
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
      partialize: (s) => ({ prefs: s.prefs, favorites: s.favorites }),
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
