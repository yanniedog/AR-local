import * as Network from 'expo-network';

import { cache, type CacheMeta } from './cache';
import { normalizeHistoryBanksPayload } from './historyPayload';
import { sampleCore, sampleManifest } from './sample';
import { debugLog } from '../lib/debugLog';
import type { HistoryBanksPayload } from './historyPayload';

export async function onWifi(): Promise<boolean> {
  try {
    const state = await Network.getNetworkStateAsync();
    return state.type === Network.NetworkStateType.WIFI;
  } catch {
    return true; // assume ok if we can't tell
  }
}

export async function readValidatedHistoryBanks(): Promise<HistoryBanksPayload | null> {
  const raw = await cache.readHistoryBanks();
  if (!raw) return null;
  const normalized = normalizeHistoryBanksPayload(raw);
  if (normalized) return normalized;
  debugLog.warn('store', 'discarding invalid cached history banks payload');
  await cache.clearHistoryBanks();
  return null;
}

export async function installSampleSeed(): Promise<void> {
  const seedMeta: CacheMeta = {
    manifest: sampleManifest,
    source: 'sample',
    savedAt: new Date().toISOString(),
    coreSha: sampleManifest.files.core.sha256,
    detailsSha: null,
  };
  await cache.writeBundle(seedMeta, JSON.stringify(sampleCore));
}

export const productHistorySyncState = { request: 0 };
