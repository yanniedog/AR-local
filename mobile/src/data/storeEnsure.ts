import type { DetailsPayload } from '../types';
import { cache } from './cache';
import {
  downloadBankInsights,
  downloadDetails,
  downloadHistoryBanks,
  downloadRbaCalendar,
  downloadSearchIndex,
} from './payload';
import { shouldWarmDetails } from './optionalPrefs';
import { dailyHistorySha, syncHistoryFromDailyPayloads } from './historyDaily';
import { normalizeHistoryBanksPayload } from './historyPayload';
import type { HistoryBanksPayload } from './historyPayload';
import { normalizeBankInsightsPayload } from './bankInsights';
import { normalizeProductHistoryPayload, syncProductHistoryFromDailyPayloads } from './productHistory';
import { effectiveBankInsights, effectiveDeepSearch, effectiveHistoryRibbon } from '../lib/proAccess';
import { debugLog } from '../lib/debugLog';
import { logDegradation, logEnsureSkipped } from '../lib/degradationLog';
import { sampleDetails } from './sample';
import type { AppState, StoreGet, StoreSet } from './storeTypes';
import { productHistorySyncState, readValidatedHistoryBanks } from './storeHelpers';

export function createEnsureActions(set: StoreSet, get: StoreGet) {
  return {
    async ensureDetails(opts: { forProductView?: boolean } = {}) {
      const { forProductView = false } = opts;
      const { details, core, manifest, source, detailsLoading, prefs, subscriptions } = get();
      if (!core || detailsLoading) return;
      if (!forProductView && !shouldWarmDetails(prefs, subscriptions)) return;

      const wantSha = manifest?.files.details.sha256 ?? null;
      const meta = await cache.readMeta();
      const shaOk = !wantSha || meta?.detailsSha === wantSha;
      if (details && details.run_date === core.run_date && shaOk) return;

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
          if (!datasetUnchanged()) return;
          await cache.writeDetails(text);
          if (!datasetUnchanged()) return;
          await cache.updateMeta({
            manifest,
            source: 'remote',
            savedAt: new Date().toISOString(),
            coreSha: manifest.files.core.sha256,
            detailsSha: manifest.files.details.sha256,
          });
          if (!datasetUnchanged()) return;
          set({ details: fresh });
          return;
        }
        if (get().source === 'sample') set({ details: sampleDetails as DetailsPayload });
      } catch (err) {
        const msg = String((err as Error)?.message ?? err);
        debugLog.warn('store', `ensureDetails failed: ${msg}`);
        logDegradation('warn', 'store.ensureFailed', { fn: 'ensureDetails', error: msg });
        if (get().source === 'sample') set({ details: sampleDetails as DetailsPayload });
      } finally {
        set({ detailsLoading: false });
        const cur = get();
        const movedOn =
          cur.core?.run_date !== core.run_date ||
          cur.manifest?.files.core.sha256 !== manifest?.files.core.sha256 ||
          cur.manifest?.files.details.sha256 !== manifest?.files.details.sha256;
        if (cur.core && movedOn) void get().ensureDetails(opts);
      }
    },

    async ensureSearchIndex() {
      if (!effectiveDeepSearch(get().prefs)) {
        logEnsureSkipped('ensureSearchIndex', 'proGate');
        return;
      }
      const { core, manifest, source, searchIndex } = get();
      if (!core || !manifest?.files.search_index) return;
      const asset = manifest.files.search_index;
      const coreSha = manifest.files.core.sha256;
      const meta = await cache.readOptionalMeta();
      const shaFresh = meta?.coreSha === coreSha && meta?.searchIndexSha === asset.sha256;
      if (searchIndex && searchIndex.run_date === core.run_date && shaFresh) {
        return;
      }
      const cached = await cache.readSearchIndex();
      if (cached && cached.run_date === core.run_date && shaFresh) {
        set({ searchIndex: cached });
        return;
      }
      if (source !== 'remote') return;
      try {
        const { text, searchIndex: fresh } = await downloadSearchIndex(asset.url, asset.sha256);
        await cache.writeSearchIndex(text);
        await cache.writeOptionalMeta({ coreSha, searchIndexSha: asset.sha256 });
        set({ searchIndex: fresh });
      } catch (err) {
        const msg = String((err as Error)?.message ?? err);
        debugLog.warn('store', `ensureSearchIndex failed: ${msg}`);
        logDegradation('warn', 'store.ensureFailed', { fn: 'ensureSearchIndex', error: msg });
      }
    },

    async ensureHistoryBanks(opts: { force?: boolean } = {}) {
      const { force = false } = opts;
      if (!effectiveHistoryRibbon(get().prefs)) {
        logEnsureSkipped('ensureHistoryBanks', 'proGate');
        return;
      }
      if (force) set({ historyBanksError: null });
      debugLog.info('store', 'ensureHistoryBanks start');
      const { core, manifest, source, historyBanks } = get();
      if (!core) {
        debugLog.debug('store', 'ensureHistoryBanks skipped (no core)');
        return;
      }
      if (source !== 'remote' || !manifest) {
        set({ historyBanks: null, historyBanksError: null });
        return;
      }

      const coreSha = manifest.files.core.sha256;
      const meta = await cache.readOptionalMeta();
      const shaMatches = (sha?: string) => meta?.coreSha === coreSha && meta?.historyBanksSha === sha;
      const cached = historyBanks ?? (await readValidatedHistoryBanks());

      const installHistory = async (validated: HistoryBanksPayload, sha: string) => {
        const text = JSON.stringify(validated);
        await cache.writeHistoryBanks(text);
        await cache.writeOptionalMeta({ coreSha, historyBanksSha: sha });
        set({ historyBanks: validated, historyBanksError: null });
        debugLog.info(
          'store',
          `ensureHistoryBanks ok run_date=${validated.run_date} slices=${validated.run_dates.length}`,
        );
      };

      const compactAsset = manifest.files.history_banks;
      if (compactAsset) {
        if (!force && cached && cached.run_date === core.run_date && shaMatches(compactAsset.sha256)) {
          set({ historyBanks: cached, historyBanksError: null });
          return;
        }
        try {
          const { historyBanks: fresh } = await downloadHistoryBanks(
            compactAsset.url,
            compactAsset.sha256,
          );
          const validated = normalizeHistoryBanksPayload(fresh);
          if (!validated) throw new Error('history_banks payload failed validation');
          await installHistory(validated, compactAsset.sha256);
          return;
        } catch (err) {
          debugLog.warn(
            'store',
            `ensureHistoryBanks compact asset failed: ${String((err as Error)?.message ?? err)}`,
          );
        }
      }

      if (!force && cached && cached.run_date === core.run_date && cached.run_dates.length > 1) {
        set({ historyBanks: cached, historyBanksError: null });
        return;
      }

      try {
        const synced = await syncHistoryFromDailyPayloads({
          targetRunDate: core.run_date,
          currentCore: core,
          existing: cached,
          cachedDates: new Set(cached?.run_dates ?? []),
        });
        if (synced.run_dates.length > 1) {
          await installHistory(synced, dailyHistorySha(synced.run_dates));
          return;
        }
      } catch (err) {
        debugLog.warn(
          'store',
          `ensureHistoryBanks daily sync failed: ${String((err as Error)?.message ?? err)}`,
        );
      }

      const asset = manifest.files.history_banks;
      if (!asset) {
        if (cached && cached.run_dates.length > 1) {
          set({ historyBanks: cached, historyBanksError: null });
          return;
        }
        set({ historyBanks: null, historyBanksError: 'history dates unavailable' });
        return;
      }

      if (!force && cached && cached.run_date === core.run_date && shaMatches(asset.sha256)) {
        set({ historyBanks: cached, historyBanksError: null });
        return;
      }

      try {
        const { historyBanks: fresh } = await downloadHistoryBanks(asset.url, asset.sha256);
        const validated = normalizeHistoryBanksPayload(fresh);
        if (!validated) {
          debugLog.error('store', 'ensureHistoryBanks rejected payload after download (validation failed)');
          set({ historyBanks: null, historyBanksError: 'history_banks payload failed validation' });
          return;
        }
        await installHistory(validated, asset.sha256);
      } catch (err) {
        const msg = String((err as Error)?.message ?? err);
        debugLog.error('store', `ensureHistoryBanks failed: ${msg}`);
        set({ historyBanks: cached?.run_dates.length ? cached : null, historyBanksError: msg });
      }
    },

    async ensureBankInsights(opts: { force?: boolean } = {}) {
      const { force = false } = opts;
      if (!effectiveBankInsights(get().prefs)) {
        logEnsureSkipped('ensureBankInsights', 'proGate');
        return;
      }
      const { core, manifest, source, bankInsights } = get();
      if (!core) return;
      if (source !== 'remote' || !manifest) {
        set({ bankInsights: null, bankInsightsError: null });
        return;
      }
      const asset = manifest.files.bank_history;
      if (!asset) {
        logDegradation('warn', 'store.ensureUnavailable', { fn: 'ensureBankInsights', reason: 'manifest_missing_asset' });
        set({ bankInsightsError: 'bank history unavailable' });
        return;
      }
      if (force) set({ bankInsightsError: null });
      const coreSha = manifest.files.core.sha256;
      const meta = await cache.readOptionalMeta();
      const fresh = (p: ReturnType<StoreGet>['bankInsights']) =>
        !!p && p.run_date === core.run_date && meta?.coreSha === coreSha && meta?.bankInsightsSha === asset.sha256;
      if (!force && fresh(bankInsights)) {
        set({ bankInsightsError: null });
        return;
      }
      const cached = force ? null : normalizeBankInsightsPayload(await cache.readBankInsights());
      if (!force && fresh(cached)) {
        set({ bankInsights: cached, bankInsightsError: null });
        return;
      }
      try {
        const { bankInsights: downloaded } = await downloadBankInsights(asset.url, asset.sha256);
        await cache.writeBankInsights(JSON.stringify(downloaded));
        await cache.writeOptionalMeta({ coreSha, bankInsightsSha: asset.sha256 });
        set({ bankInsights: downloaded, bankInsightsError: null });
        debugLog.info(
          'store',
          `ensureBankInsights ok run_date=${downloaded.run_date} banks=${Object.keys(downloaded.banks).length} events=${downloaded.events.length}`,
        );
      } catch (err) {
        const msg = String((err as Error)?.message ?? err);
        debugLog.warn('store', `ensureBankInsights failed: ${msg}`);
        logDegradation('warn', 'store.ensureFailed', { fn: 'ensureBankInsights', error: msg });
        const fallback = force ? bankInsights : cached ?? bankInsights ?? null;
        set({ bankInsights: fallback, bankInsightsError: msg });
      }
    },

    async ensureRbaCalendar() {
      const { core, manifest, source, rbaCalendar, rbaCalendarSha } = get();
      if (!core || source !== 'remote' || !manifest) {
        if (source !== 'remote' || !manifest) {
          set({ rbaCalendar: null, rbaCalendarSha: null, rbaCalendarError: null });
        }
        return;
      }
      const asset = manifest.files.rba_calendar;
      if (!asset) {
        set({ rbaCalendar: null, rbaCalendarSha: null, rbaCalendarError: 'rba calendar unavailable' });
        return;
      }
      if (rbaCalendar && rbaCalendarSha === asset.sha256) return;
      try {
        const { rbaCalendar: downloaded } = await downloadRbaCalendar(asset.url, asset.sha256);
        set({ rbaCalendar: downloaded, rbaCalendarSha: asset.sha256, rbaCalendarError: null });
        debugLog.info(
          'store',
          `ensureRbaCalendar ok decisions=${downloaded.decisions.length} schedule=${downloaded.schedule.length}`,
        );
      } catch (err) {
        const msg = String((err as Error)?.message ?? err);
        debugLog.warn('store', `ensureRbaCalendar failed: ${msg}`);
        set({ rbaCalendarError: msg });
      }
    },

    async retryHistoryBanks() {
      if (!effectiveHistoryRibbon(get().prefs)) return;
      set({ historyBanksError: null });
      const { manifest } = get();
      if (!manifest?.files.history_banks) {
        await get().refresh({ manual: true, force: true });
      }
      await get().ensureHistoryBanks({ force: true });
    },

    async retryBankInsights() {
      if (!effectiveBankInsights(get().prefs)) {
        logEnsureSkipped('retryBankInsights', 'proGate');
        return;
      }
      set({ bankInsightsError: null });
      const { manifest } = get();
      if (!manifest?.files.bank_history) {
        await get().refresh({ manual: true, force: true });
      }
      await get().ensureBankInsights({ force: true });
    },

    async ensureProductHistory(opts: { force?: boolean } = {}) {
      const { force = false } = opts;
      if (!effectiveHistoryRibbon(get().prefs)) {
        logEnsureSkipped('ensureProductHistory', 'proGate');
        return;
      }
      if (force) set({ productHistoryError: null });
      const { core, manifest, source, productHistory } = get();
      if (!core) return;
      if (source !== 'remote') {
        set({ productHistory: null, productHistoryError: null });
        return;
      }
      const cached = productHistory ?? normalizeProductHistoryPayload(await cache.readProductHistory());
      const coreSha = manifest?.files.core.sha256 ?? '';
      const requestId = ++productHistorySyncState.request;
      const revisionIsCurrent = () => {
        const current = get();
        return (
          requestId === productHistorySyncState.request &&
          current.source === 'remote' &&
          current.core?.run_date === core.run_date &&
          (current.manifest?.files.core.sha256 ?? '') === coreSha
        );
      };
      try {
        const synced = await syncProductHistoryFromDailyPayloads({
          targetRunDate: core.run_date,
          currentCore: core,
          coreSha,
          existing: cached,
        });
        if (!revisionIsCurrent()) {
          debugLog.info('store', `ensureProductHistory superseded run_date=${synced.run_date}`);
          return;
        }
        await cache.writeProductHistory(JSON.stringify(synced));
        set({ productHistory: synced, productHistoryError: null });
        debugLog.info(
          'store',
          `ensureProductHistory ok run_date=${synced.run_date} slices=${synced.run_dates.length} products=${Object.keys(synced.products).length}`,
        );
      } catch (err) {
        const msg = String((err as Error)?.message ?? err);
        debugLog.warn('store', `ensureProductHistory failed: ${msg}`);
        logDegradation('warn', 'store.ensureFailed', { fn: 'ensureProductHistory', error: msg });
        if (!revisionIsCurrent()) return;
        set({ productHistory: cached ?? null, productHistoryError: msg });
      }
    },
  } satisfies Pick<
    AppState,
    | 'ensureDetails'
    | 'ensureSearchIndex'
    | 'ensureHistoryBanks'
    | 'ensureBankInsights'
    | 'ensureRbaCalendar'
    | 'ensureProductHistory'
    | 'retryHistoryBanks'
    | 'retryBankInsights'
  >;
}
