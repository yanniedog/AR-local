import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Network from 'expo-network';
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
import { computeChanges, notify, setBackgroundRefreshHandler } from './notifications';
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

  prefs: Prefs;
  favorites: string[];

  bootstrap: () => Promise<void>;
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

        setBackgroundRefreshHandler(() => get().refresh({}));
        // Try the network in the background; never blocks first paint.
        void get().refresh({});
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
            return false;
          }

          const previousCore = get().core;
          const { text, core } = await downloadCore(remote.files.core.url);
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
        if (detailsLoading) return;
        if (details && core && details.run_date === core.run_date) return;

        set({ detailsLoading: true });
        try {
          const cached = await cache.readDetails();
          if (cached && core && cached.run_date === core.run_date) {
            set({ details: cached });
            return;
          }
          if (source === 'remote' && manifest) {
            const { text, details: fresh } = await downloadDetails(manifest.files.details.url);
            await cache.writeDetails(text);
            set({ details: fresh });
            return;
          }
          // Sample / offline fallback.
          set({ details: sampleDetails as DetailsPayload });
        } catch {
          set({ details: sampleDetails as DetailsPayload });
        } finally {
          set({ detailsLoading: false });
        }
      },

      getDetail(productKey: string) {
        return get().details?.products[productKey] ?? null;
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
    },
  ),
);
