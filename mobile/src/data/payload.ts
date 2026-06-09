import * as Application from 'expo-application';
import * as Crypto from 'expo-crypto';
import { gunzipSync, strFromU8 } from 'fflate';

import { MANIFEST_URL, SUPPORTED_SCHEMA } from '../config';
import type { CorePayload, DetailsPayload, Manifest } from '../types';
import {
  fileNameFromUrl,
  type PayloadProgressHandler,
  type PayloadProgressPhase,
  type PayloadProgressSnapshot,
} from './downloadProgress';

/** Numeric semver compare: true when a < b ("1.0.0" < "1.1.0"). */
function versionLt(a: string, b: string): boolean {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0);
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x < y) return true;
    if (x > y) return false;
  }
  return false;
}

export interface DownloadOpts {
  fileName?: string;
  expectedBytes?: number;
  onProgress?: PayloadProgressHandler;
}

function emit(
  onProgress: PayloadProgressHandler | undefined,
  snapshot: PayloadProgressSnapshot,
): void {
  onProgress?.(snapshot);
}

/**
 * Download raw bytes with XMLHttpRequest progress events (works on iOS/Android).
 * Falls back to `expectedBytes` when Content-Length is missing.
 */
async function downloadBytes(
  url: string,
  opts: DownloadOpts & { phase?: PayloadProgressPhase } = {},
): Promise<ArrayBuffer> {
  const fileName = opts.fileName ?? fileNameFromUrl(url);
  const phase = opts.phase ?? 'download';
  const startedAt = Date.now();
  emit(opts.onProgress, {
    phase,
    fileName,
    bytesReceived: 0,
    totalBytes: opts.expectedBytes ?? null,
    startedAt,
  });

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('GET', url);
    xhr.responseType = 'arraybuffer';
    xhr.onprogress = (event) => {
      const totalBytes = event.lengthComputable
        ? event.total
        : (opts.expectedBytes ?? null);
      emit(opts.onProgress, {
        phase,
        fileName,
        bytesReceived: event.loaded,
        totalBytes,
        startedAt,
      });
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const buf = xhr.response as ArrayBuffer;
        emit(opts.onProgress, {
          phase,
          fileName,
          bytesReceived: buf.byteLength,
          totalBytes: buf.byteLength,
          startedAt,
        });
        resolve(buf);
        return;
      }
      reject(new Error(`asset HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error('network error'));
    xhr.send();
  });
}

/**
 * Fetch and parse the rolling manifest. Throws on network/HTTP errors, and on a
 * payload that needs a newer app build — so an out-of-date client never replaces
 * its compatible offline cache with an incompatible payload.
 */
export async function fetchManifest(
  url: string = MANIFEST_URL,
  onProgress?: PayloadProgressHandler,
): Promise<Manifest> {
  const buf = await downloadBytes(url, {
    fileName: 'manifest.json',
    onProgress,
    phase: 'manifest',
  });
  const text = strFromU8(new Uint8Array(buf));
  const startedAt = Date.now();
  emit(onProgress, {
    phase: 'parse',
    fileName: 'manifest.json',
    bytesReceived: buf.byteLength,
    totalBytes: buf.byteLength,
    startedAt,
  });
  const m = JSON.parse(text) as Manifest;
  if (typeof m.schema_version === 'number' && m.schema_version > SUPPORTED_SCHEMA) {
    throw new Error(`payload schema v${m.schema_version} unsupported (app supports v${SUPPORTED_SCHEMA}); update the app`);
  }
  const appVersion = Application.nativeApplicationVersion;
  if (m.app_min_version && appVersion && versionLt(appVersion, m.app_min_version)) {
    throw new Error(`payload requires app >= ${m.app_min_version} (have ${appVersion}); update the app`);
  }
  return m;
}

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Download a gzipped JSON asset and inflate it to a UTF-8 string (no TextDecoder dep).
 * When `expectedSha` is given, the raw bytes are verified against it before inflating —
 * so a stale asset served during a same-URL clobber can't be cached under a new hash.
 */
export async function downloadInflate(
  url: string,
  expectedSha?: string,
  opts: DownloadOpts = {},
): Promise<string> {
  const fileName = opts.fileName ?? fileNameFromUrl(url);
  const buf = await downloadBytes(url, { ...opts, fileName, phase: 'download' });
  const byteLen = buf.byteLength;

  const verifyStarted = Date.now();
  emit(opts.onProgress, {
    phase: 'verify',
    fileName,
    bytesReceived: byteLen,
    totalBytes: byteLen,
    startedAt: verifyStarted,
  });
  if (expectedSha) {
    const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, buf);
    const actual = toHex(digest);
    if (actual !== expectedSha) {
      throw new Error(`asset sha256 mismatch (expected ${expectedSha.slice(0, 12)}…, got ${actual.slice(0, 12)}…)`);
    }
  }

  const inflateStarted = Date.now();
  emit(opts.onProgress, {
    phase: 'inflate',
    fileName,
    bytesReceived: byteLen,
    totalBytes: byteLen,
    startedAt: inflateStarted,
  });
  const bytes = new Uint8Array(buf);
  // GitHub release assets are served raw; the bytes are our gzip. If a proxy
  // already decoded gzip transport, the bytes are plain JSON — handle both.
  const looksGzipped = bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
  return looksGzipped ? strFromU8(gunzipSync(bytes)) : strFromU8(bytes);
}

export interface CoreResult {
  text: string;
  core: CorePayload;
}

export async function downloadCore(
  url: string,
  expectedSha?: string,
  opts: DownloadOpts = {},
): Promise<CoreResult> {
  const fileName = opts.fileName ?? fileNameFromUrl(url);
  const text = await downloadInflate(url, expectedSha, opts);
  const parseStarted = Date.now();
  emit(opts.onProgress, {
    phase: 'parse',
    fileName,
    bytesReceived: text.length,
    totalBytes: text.length,
    startedAt: parseStarted,
  });
  return { text, core: JSON.parse(text) as CorePayload };
}

export interface DetailsResult {
  text: string;
  details: DetailsPayload;
}

export async function downloadDetails(
  url: string,
  expectedSha?: string,
  opts: DownloadOpts = {},
): Promise<DetailsResult> {
  const fileName = opts.fileName ?? fileNameFromUrl(url);
  const text = await downloadInflate(url, expectedSha, opts);
  const parseStarted = Date.now();
  emit(opts.onProgress, {
    phase: 'parse',
    fileName,
    bytesReceived: text.length,
    totalBytes: text.length,
    startedAt: parseStarted,
  });
  return { text, details: JSON.parse(text) as DetailsPayload };
}
