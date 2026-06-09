// SDK 54 replaced the classic file API with a File/Directory API; the classic

// functions we use (documentDirectory, read/write/move/delete) live under /legacy.

import * as FileSystem from 'expo-file-system/legacy';



import type { CorePayload, DetailsPayload, Manifest, PayloadSource } from '../types';

import type { SearchIndexPayload } from './detailSearch';

import type { HistoryBanksPayload } from './historyPayload';



const DIR = `${FileSystem.documentDirectory}payload/`;

const BUNDLE = `${DIR}core-bundle.json`;

const BUNDLE_TMP = `${BUNDLE}.tmp`;

const DETAILS = `${DIR}details.json`;

const SEARCH_INDEX = `${DIR}search-index.json`;

const HISTORY_BANKS = `${DIR}history-banks.json`;



export interface CacheMeta {

  manifest: Manifest;

  source: PayloadSource;

  savedAt: string;

  coreSha: string;

  detailsSha: string | null;

  searchIndexSha?: string | null;

  historyBanksSha?: string | null;

}



export interface CoreBundle {

  meta: CacheMeta;

  core: CorePayload;

}



async function ensureDir(): Promise<void> {

  const info = await FileSystem.getInfoAsync(DIR);

  if (!info.exists) {

    await FileSystem.makeDirectoryAsync(DIR, { intermediates: true });

  }

}



async function readJson<T>(path: string): Promise<T | null> {

  try {

    const info = await FileSystem.getInfoAsync(path);

    if (!info.exists) return null;

    const text = await FileSystem.readAsStringAsync(path);

    return JSON.parse(text) as T;

  } catch {

    return null;

  }

}



let writeChain: Promise<void> = Promise.resolve();

function serialize<T>(fn: () => Promise<T>): Promise<T> {

  const run = writeChain.then(fn, fn);

  writeChain = run.then(

    () => undefined,

    () => undefined,

  );

  return run;

}



async function atomicWriteBundle(contents: string): Promise<void> {

  await ensureDir();

  await FileSystem.writeAsStringAsync(BUNDLE_TMP, contents);

  await FileSystem.deleteAsync(BUNDLE, { idempotent: true });

  await FileSystem.moveAsync({ from: BUNDLE_TMP, to: BUNDLE });

}



export const cache = {

  async readBundle(): Promise<CoreBundle | null> {

    let b = await readJson<CoreBundle>(BUNDLE);

    if (!b) b = await readJson<CoreBundle>(BUNDLE_TMP);

    if (!b || !b.meta || !b.core) return null;

    return b;

  },

  async readMeta(): Promise<CacheMeta | null> {

    return (await cache.readBundle())?.meta ?? null;

  },

  async readCore(): Promise<CorePayload | null> {

    return (await cache.readBundle())?.core ?? null;

  },

  async readDetails(): Promise<DetailsPayload | null> {

    return readJson<DetailsPayload>(DETAILS);

  },

  async writeBundle(meta: CacheMeta, coreText: string): Promise<void> {

    return serialize(() => atomicWriteBundle(`{"meta":${JSON.stringify(meta)},"core":${coreText}}`));

  },

  async updateMeta(meta: Partial<CacheMeta> & { coreSha: string; manifest: Manifest }): Promise<void> {

    return serialize(async () => {

      const b = await cache.readBundle();

      if (!b) return;

      if (b.meta.coreSha !== meta.coreSha) return;

      if (b.meta.manifest.generated_at > meta.manifest.generated_at) return;

      const merged: CacheMeta = { ...b.meta, ...meta };

      await atomicWriteBundle(`{"meta":${JSON.stringify(merged)},"core":${JSON.stringify(b.core)}}`);

    });

  },

  async writeDetails(json: string): Promise<void> {

    await ensureDir();

    await FileSystem.writeAsStringAsync(DETAILS, json);

  },

  async readSearchIndex(): Promise<SearchIndexPayload | null> {

    return readJson<SearchIndexPayload>(SEARCH_INDEX);

  },

  async writeSearchIndex(json: string): Promise<void> {

    await ensureDir();

    await FileSystem.writeAsStringAsync(SEARCH_INDEX, json);

  },

  async readHistoryBanks(): Promise<HistoryBanksPayload | null> {

    return readJson<HistoryBanksPayload>(HISTORY_BANKS);

  },

  async clearHistoryBanks(): Promise<void> {

    await FileSystem.deleteAsync(HISTORY_BANKS, { idempotent: true });

  },

  async writeHistoryBanks(json: string): Promise<void> {

    await ensureDir();

    await FileSystem.writeAsStringAsync(HISTORY_BANKS, json);

  },

  async clear(): Promise<void> {

    await FileSystem.deleteAsync(DIR, { idempotent: true });

  },

};


