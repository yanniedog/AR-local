import { DEFAULT_PREFS, type AppState, type StoreGet, type StoreSet } from './storeTypes';
import { cache } from './cache';
import { effectiveDeepSearch, effectiveHistoryRibbon } from '../lib/proAccess';
import { debugLog } from '../lib/debugLog';
import { useRegisterLogosStore } from '../lib/registerLogos';
import { logRetry } from '../lib/degradationLog';
import { sampleCore, sampleManifest } from './sample';
import { installSampleSeed, readValidatedHistoryBanks } from './storeHelpers';

export function createBootstrapActions(
  set: StoreSet,
  get: StoreGet,
  getStore: () => { persist?: { rehydrate?: () => void | Promise<void> } },
) {
  return {
    async bootstrap() {
      if (get().status === 'ready' || get().status === 'loading') return;
      debugLog.info('store', 'bootstrap');
      set({ status: 'loading', error: null });

      try {
        await getStore().persist?.rehydrate?.();
      } catch (err) {
        debugLog.warn('store', `prefs rehydrate failed: ${String((err as Error)?.message ?? err)}`);
      }

      try {
        const prefs = get().prefs;
        const bundle = await cache.readBundle();
        const [cachedSearch, cachedHistory] = await Promise.all([
          effectiveDeepSearch(prefs) ? cache.readSearchIndex() : Promise.resolve(null),
          effectiveHistoryRibbon(prefs) ? readValidatedHistoryBanks() : Promise.resolve(null),
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

      void useRegisterLogosStore.getState().ensure();
      void get().refresh({});
    },

    async retryDataLoad() {
      logRetry('retryDataLoad', 'start');
      debugLog.info('store', 'retryDataLoad');
      set({ status: 'idle', error: null });
      await get().bootstrap();
      if (get().status !== 'ready') {
        logRetry('retryDataLoad', 'failure', get().error ?? undefined);
        return;
      }
      await get().refresh({ force: true, manual: true });
      if (get().refreshOutcome === 'failure') {
        logRetry('retryDataLoad', 'failure', get().error ?? 'refresh failed');
      } else {
        logRetry('retryDataLoad', 'success');
      }
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
          bankInsights: null,
          bankInsightsError: null,
          rbaCalendar: null,
          rbaCalendarSha: null,
          rbaCalendarError: null,
          productHistory: null,
          productHistoryError: null,
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
  } satisfies Pick<
    AppState,
    'bootstrap' | 'retryDataLoad' | 'loadSampleFallback' | 'ensureCoreLoaded'
  >;
}

export const bootstrapInitialState = {
  status: 'idle' as const,
  refreshing: false,
  source: 'sample' as const,
  manifest: null,
  core: null,
  details: null,
  searchIndex: null,
  historyBanks: null,
  historyBanksError: null,
  bankInsights: null,
  bankInsightsError: null,
  rbaCalendar: null,
  rbaCalendarSha: null,
  rbaCalendarError: null,
  productHistory: null,
  productHistoryError: null,
  detailsLoading: false,
  error: null,
  offline: false,
  lastCheckedAt: null,
  payloadProgress: null,
  refreshOutcome: null,
  hydrated: false,
  activeSection: DEFAULT_PREFS.defaultSection,
  prefs: DEFAULT_PREFS,
  favorites: [] as string[],
  subscriptions: [],
};
