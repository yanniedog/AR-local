import * as FileSystem from 'expo-file-system';

import type { CorePayload, DetailsPayload, Manifest, PayloadSource } from '../types';

const DIR = `${FileSystem.documentDirectory}payload/`;
// Core + metadata live in ONE file written atomically (temp file + move), so they can
// never disagree and an interrupted write can't truncate the live bundle. Details are
// separate because they're downloaded lazily and validated by sha against the manifest.
const BUNDLE = `${DIR}core-bundle.json`;
const BUNDLE_TMP = `${BUNDLE}.tmp`;
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

// Serialize all bundle writes so a refresh's writeBundle and ensureDetails' updateMeta
// (a read-modify-write) can never interleave and clobber each other.
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
  // rename is atomic on the same filesystem; delete the old target first since native
  // move rejects an existing destination. If interrupted here, readBundle recovers
  // from the .tmp that's already complete.
  await FileSystem.deleteAsync(BUNDLE, { idempotent: true });
  await FileSystem.moveAsync({ from: BUNDLE_TMP, to: BUNDLE });
}

export const cache = {
  async readBundle(): Promise<CoreBundle | null> {
    let b = await readJson<CoreBundle>(BUNDLE);
    if (!b) {
      // Recover from a half-finished atomic write (live file deleted, tmp complete).
      b = await readJson<CoreBundle>(BUNDLE_TMP);
    }
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
  /** Write core + meta together atomically. `coreText` is the raw core JSON. */
  async writeBundle(meta: CacheMeta, coreText: string): Promise<void> {
    return serialize(() => atomicWriteBundle(`{"meta":${JSON.stringify(meta)},"core":${coreText}}`));
  },
  /** Update only the metadata, preserving the cached core (serialized read-modify-write).
   *  Conditional: discards the update if the on-disk core has advanced past the one this
   *  metadata was built for (coreSha mismatch), so a stale update queued after a newer
   *  refresh can't pair the new core with an old manifest. */
  async updateMeta(meta: CacheMeta): Promise<void> {
    return serialize(async () => {
      const b = await cache.readBundle();
      if (!b) return;
      // Discard if the on-disk bundle has advanced past the manifest this update is for:
      // a different core, or a newer manifest version (generated_at) for the same core
      // (e.g. a details-only correction adopted by a later refresh). Without the version
      // check a stale same-core update could regress the bundle to an older details hash.
      if (b.meta.coreSha !== meta.coreSha) return;
      if (b.meta.manifest.generated_at > meta.manifest.generated_at) return;
      await atomicWriteBundle(`{"meta":${JSON.stringify(meta)},"core":${JSON.stringify(b.core)}}`);
    });
  },
  async writeDetails(json: string): Promise<void> {
    await ensureDir();
    await FileSystem.writeAsStringAsync(DETAILS, json);
  },
  async clear(): Promise<void> {
    await FileSystem.deleteAsync(DIR, { idempotent: true });
  },
};
