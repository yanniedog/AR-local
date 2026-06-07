import * as FileSystem from 'expo-file-system';

import type { CorePayload, DetailsPayload, Manifest, PayloadSource } from '../types';

const DIR = `${FileSystem.documentDirectory}payload/`;
// Core + metadata live in ONE file written atomically, so they can never disagree
// (a crash can't leave a new core paired with an old manifest). Details are separate
// because they're downloaded lazily and validated by sha against the manifest.
const BUNDLE = `${DIR}core-bundle.json`;
const DETAILS = `${DIR}details.json`;

export interface CacheMeta {
  manifest: Manifest;
  source: PayloadSource;
  savedAt: string;
  coreSha: string;
  detailsSha: string | null;
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

export const cache = {
  async readBundle(): Promise<CoreBundle | null> {
    const b = await readJson<CoreBundle>(BUNDLE);
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
  /** Write core + meta together in a single file. `coreText` is the raw core JSON. */
  async writeBundle(meta: CacheMeta, coreText: string): Promise<void> {
    await ensureDir();
    await FileSystem.writeAsStringAsync(BUNDLE, `{"meta":${JSON.stringify(meta)},"core":${coreText}}`);
  },
  /** Update only the metadata, preserving the cached core (re-writes the bundle). */
  async updateMeta(meta: CacheMeta): Promise<void> {
    const b = await cache.readBundle();
    if (!b) return;
    await cache.writeBundle(meta, JSON.stringify(b.core));
  },
  async writeDetails(json: string): Promise<void> {
    await ensureDir();
    await FileSystem.writeAsStringAsync(DETAILS, json);
  },
  async clear(): Promise<void> {
    await FileSystem.deleteAsync(DIR, { idempotent: true });
  },
};
