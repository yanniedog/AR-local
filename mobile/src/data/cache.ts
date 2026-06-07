import * as FileSystem from 'expo-file-system';

import type { CorePayload, DetailsPayload, Manifest, PayloadSource } from '../types';

const DIR = `${FileSystem.documentDirectory}payload/`;
const CORE = `${DIR}core.json`;
const DETAILS = `${DIR}details.json`;
const META = `${DIR}meta.json`;

export interface CacheMeta {
  manifest: Manifest;
  source: PayloadSource;
  savedAt: string;
  coreSha: string;
  detailsSha: string | null;
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

export const cache = {
  async readCore(): Promise<CorePayload | null> {
    return readJson<CorePayload>(CORE);
  },
  async readDetails(): Promise<DetailsPayload | null> {
    return readJson<DetailsPayload>(DETAILS);
  },
  async readMeta(): Promise<CacheMeta | null> {
    return readJson<CacheMeta>(META);
  },
  async writeCore(json: string): Promise<void> {
    await ensureDir();
    await FileSystem.writeAsStringAsync(CORE, json);
  },
  async writeDetails(json: string): Promise<void> {
    await ensureDir();
    await FileSystem.writeAsStringAsync(DETAILS, json);
  },
  async writeMeta(meta: CacheMeta): Promise<void> {
    await ensureDir();
    await FileSystem.writeAsStringAsync(META, JSON.stringify(meta));
  },
  async clear(): Promise<void> {
    await FileSystem.deleteAsync(DIR, { idempotent: true });
  },
};
