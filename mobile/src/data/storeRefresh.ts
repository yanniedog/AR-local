import type { DetailsPayload } from '../types';
import { cache } from './cache';
import type { PayloadProgressSnapshot } from './downloadProgress';
import { computeChanges, notify } from './notifications';
import {
  downloadCore,
  fetchManifest,
} from './payload';
import { shouldWarmDetails } from './optionalPrefs';
import { effectiveBankInsights, effectiveDeepSearch, effectiveHistoryRibbon } from '../lib/proAccess';
import { debugLog } from '../lib/debugLog';
import { logStoreRefreshSkipped } from '../lib/degradationLog';
import { hapticRefreshComplete } from '../lib/haptics';
import type { AppState, StoreGet, StoreSet } from './storeTypes';
import { onWifi } from './storeHelpers';

export function createRefreshActions(set: StoreSet, get: StoreGet) {
  return {
    async refresh(opts: { force?: boolean; manual?: boolean } = {}) {
      const { force = false, manual = false } = opts;
      const warmDetails = async () => {
        if (shouldWarmDetails(get().prefs, get().subscriptions)) {
          await get().ensureDetails();
        }
      };
      const warmOptionalAssets = () => {
        const p = get().prefs;
        if (effectiveDeepSearch(p)) void get().ensureSearchIndex();
        if (effectiveBankInsights(p)) void get().ensureBankInsights();
        if (effectiveHistoryRibbon(p)) void get().ensureHistoryBanks();
        void get().ensureRbaCalendar();
      };
      if (get().refreshing) {
        logStoreRefreshSkipped('already_refreshing');
        return false;
      }
      const prefs = get().prefs;
      if (prefs.wifiOnly && !manual && !(await onWifi())) {
        logStoreRefreshSkipped('wifi_only');
        debugLog.debug('store', 'refresh skipped (wifi-only, not on Wi-Fi)');
        set({ lastCheckedAt: new Date().toISOString(), refreshOutcome: 'wifi-skip' });
        return false;
      }
      debugLog.info('store', `refresh start manual=${manual} force=${force}`);
      set({ refreshing: true });
      const onProgress = (snapshot: PayloadProgressSnapshot) => set({ payloadProgress: snapshot });
      try {
        const remote = await fetchManifest(undefined, onProgress);
        set({ offline: false, lastCheckedAt: new Date().toISOString() });

        const meta = await cache.readMeta();
        const upToDate =
          !force &&
          meta?.source === 'remote' &&
          meta.manifest.run_date === remote.run_date &&
          meta.coreSha === remote.files.core.sha256;
        if (upToDate) {
          debugLog.debug('store', `refresh up-to-date run_date=${remote.run_date}`);
          const bundle = await cache.readBundle();
          set({
            manifest: remote,
            source: 'remote',
            offline: false,
            ...(bundle ? { core: bundle.core } : {}),
          });
          await warmDetails();
          warmOptionalAssets();
          set({ refreshOutcome: 'success' });
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
        const detailsUnchanged = !!meta && meta.detailsSha === remote.files.details.sha256;
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
          await notify(messages);
          debugLog.info('store', `notified ${messages.length} rate-change message(s)`);
        }
        debugLog.info('store', `refresh ok run_date=${core.run_date} changed=true`);
        set({ refreshOutcome: 'success' });
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
          refreshOutcome: 'failure',
        });
        return false;
      } finally {
        set({ refreshing: false, payloadProgress: null });
        if (manual) hapticRefreshComplete();
      }
    },
  } satisfies Pick<AppState, 'refresh'>;
}
