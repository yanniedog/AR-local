import { hasAppHealthFetchGuard } from '../lib/appHealthTransportGuard';
import { bindVerifiedDetails } from './detailsIdentity';
import * as Application from 'expo-application';
import * as Crypto from 'expo-crypto';
import { Gunzip, gunzipSync, strFromU8 } from 'fflate';

import { resolvePayloadKeyHex } from '../lib/keyVault';
import { decryptAsset, isEncryptedAsset } from '../lib/payloadCrypto';

import { MANIFEST_URL, SUPPORTED_SCHEMA } from '../config';
import { debugLog } from '../lib/debugLog';
import { logFetchHttpError } from '../lib/degradationLog';
import { versionLt } from '../lib/versionCompare';
import { HEAVY_JSON_BYTES, parseJsonHeavy, yieldToUi } from '../lib/yieldToUi';
import type { CorePayload, DetailsPayload, Manifest } from '../types';
import { normalizeCoreWithIntegrity, type CoreIntegrityContext } from './sectionIntegrity';
import { normalizeBankInsightsPayload } from './bankInsights';
import { normalizeBankSpreadHistoryPayload } from './bankSpreadHistory';
import { normalizeHistoryBanksPayload } from './historyPayload';
import { normalizeRbaCalendar } from './rbaCalendar';
import {
  fileNameFromUrl,
  type PayloadProgressHandler,
  type PayloadProgressPhase,
  type PayloadProgressSnapshot,
} from './downloadProgress';

/** Yield before sync inflate/parse when the payload is large enough to jank the UI. */
const YIELD_BEFORE_HEAVY_BYTES = HEAVY_JSON_BYTES;
const INFLATE_CHUNK_BYTES = 64 * 1024;
export const BANK_SPREAD_MAX_COMPRESSED_BYTES = 8 * 1024 * 1024;
export const BANK_SPREAD_MAX_INFLATED_BYTES = 64 * 1024 * 1024;

/**
 * Decompress a large gzip without monopolising the JS thread for the entire
 * payload. Fflate's async worker API is unavailable in React Native, so feed
 * its streaming inflater bounded compressed chunks and yield between pushes.
 */
export async function gunzipCooperatively(
  bytes: Uint8Array,
  chunkBytes: number = INFLATE_CHUNK_BYTES,
  maxOutputBytes: number = Number.POSITIVE_INFINITY,
): Promise<Uint8Array> {
  const safeChunkBytes = Math.max(1, Math.floor(chunkBytes));
  const outputs: Uint8Array[] = [];
  let outputBytes = 0;
  const stream = new Gunzip((chunk) => {
    outputBytes += chunk.length;
    if (outputBytes > maxOutputBytes) {
      throw new Error(`inflated asset exceeds ${maxOutputBytes} byte limit`);
    }
    outputs.push(chunk);
  });
  for (let offset = 0; offset < bytes.length; offset += safeChunkBytes) {
    const end = Math.min(bytes.length, offset + safeChunkBytes);
    stream.push(bytes.subarray(offset, end), end === bytes.length);
    if (end < bytes.length) await yieldToUi();
  }
  const result = new Uint8Array(outputBytes);
  let writeOffset = 0;
  for (const chunk of outputs) {
    result.set(chunk, writeOffset);
    writeOffset += chunk.length;
  }
  return result;
}

export interface DownloadOpts {
  fileName?: string;
  expectedBytes?: number;
  /** Hard ceiling for bytes received before hash verification. */
  maxCompressedBytes?: number;
  /** Hard ceiling enforced while inflating, not after allocation. */
  maxInflatedBytes?: number;
  /** Immutable descriptor's exact expanded byte count, when declared. */
  expectedInflatedBytes?: number;
  /** V3 immutable descriptors require exact compressed and inflated sizes. */
  requireExactBytes?: boolean;
  /** Optional immutable contract encoding assertion. */
  expectedEncoding?: 'gzip' | 'identity';
  /** Legacy v1 may use ARE1; v3 descriptors currently may not. */
  allowEncrypted?: boolean;
  /** Receives a copy of the exact downloaded bytes after descriptor SHA verification. */
  onVerifiedBytes?: (bytes: Uint8Array) => void;
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

function manifestFetchUrl(url: string): string {
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}_=${Date.now()}`;
}

async function downloadBytes(
  url: string,
  opts: DownloadOpts & { phase?: PayloadProgressPhase } = {},
): Promise<ArrayBuffer> {
  if (
    opts.requireExactBytes &&
    (
      typeof opts.expectedBytes !== 'number' ||
      !Number.isSafeInteger(opts.expectedBytes) ||
      opts.expectedBytes <= 0 ||
      (
        typeof opts.maxCompressedBytes === 'number' &&
        opts.expectedBytes > opts.maxCompressedBytes
      )
    )
  ) {
    throw new Error(
      'exact compressed asset size requires a positive safe-integer expectedBytes within the compressed byte limit',
    );
  }
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

  if (hasAppHealthFetchGuard()) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30_000);
    try {
      const response = await globalThis.fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`asset HTTP ${response.status}`);
      const buf = await response.arrayBuffer();
      if (opts.maxCompressedBytes != null && buf.byteLength > opts.maxCompressedBytes) {
        throw new Error(`compressed asset exceeds ${opts.maxCompressedBytes} byte limit`);
      }
      if (opts.requireExactBytes && buf.byteLength !== opts.expectedBytes) {
        throw new Error(`compressed asset size mismatch (expected ${opts.expectedBytes}, got ${buf.byteLength})`);
      }
      emit(opts.onProgress, { phase, fileName, bytesReceived: buf.byteLength, totalBytes: buf.byteLength, startedAt });
      return buf;
    } finally {
      clearTimeout(timer);
    }
  }

  return new Promise((resolve, reject) => {
    let lastEmitAt = 0;
    const xhr = new XMLHttpRequest();
    xhr.open('GET', url);
    xhr.timeout = 30000;
    xhr.responseType = 'arraybuffer';
    xhr.ontimeout = () => reject(new Error('network timeout'));
    xhr.onprogress = (event) => {
      if (opts.maxCompressedBytes != null && event.loaded > opts.maxCompressedBytes) {
        xhr.abort();
        reject(new Error(`compressed asset exceeds ${opts.maxCompressedBytes} byte limit`));
        return;
      }
      const now = Date.now();
      const totalBytes = event.lengthComputable
        ? event.total
        : (opts.expectedBytes ?? null);
      const isFinal = totalBytes !== null && event.loaded >= totalBytes;
      if (!isFinal && now - lastEmitAt < 150) {
        return;
      }
      lastEmitAt = now;
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
        if (!buf) {
          reject(new Error('empty response'));
          return;
        }
        if (opts.maxCompressedBytes != null && buf.byteLength > opts.maxCompressedBytes) {
          reject(new Error(`compressed asset exceeds ${opts.maxCompressedBytes} byte limit`));
          return;
        }
        if (opts.requireExactBytes && buf.byteLength !== opts.expectedBytes) {
          reject(new Error(`compressed asset size mismatch (expected ${opts.expectedBytes}, got ${buf.byteLength})`));
          return;
        }
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
      logFetchHttpError(url, xhr.status, phase);
      reject(new Error(`asset HTTP ${xhr.status}`));
    };
    xhr.onerror = () => {
      debugLog.error('payload', `download failed url=${url}`);
      logFetchHttpError(url, 0, `${phase}:network_error`);
      reject(new Error('network error'));
    };
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
  expectedSha?: string,
): Promise<Manifest> {
  const buf = await downloadBytes(manifestFetchUrl(url), {
    maxCompressedBytes: 4 * 1024 * 1024,
    fileName: 'manifest.json',
    onProgress,
    phase: 'manifest',
  });
  // Stay on the manifest phase — never jump to "parse json" at 100% for this
  // tiny catalog while later finalize/download work is still outstanding.
  emit(onProgress, {
    phase: 'manifest',
    fileName: 'manifest.json',
    bytesReceived: buf.byteLength,
    totalBytes: buf.byteLength,
    startedAt: Date.now(),
    phaseComplete: true,
  });
  const text = strFromU8(new Uint8Array(buf));
  if (expectedSha && toHex(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, new Uint8Array(buf))) !== expectedSha) {
    throw new Error('Selected manifest sha256 mismatch');
  }
  const m = await parseJsonHeavy<Manifest>(text);
  if (typeof m.schema_version === 'number' && m.schema_version > SUPPORTED_SCHEMA) {
    throw new Error(`payload schema v${m.schema_version} unsupported (app supports v${SUPPORTED_SCHEMA}); update the app`);
  }
  const appVersion = Application.nativeApplicationVersion;
  if (m.app_min_version && appVersion && versionLt(appVersion, m.app_min_version)) {
    throw new Error(`payload requires app >= ${m.app_min_version} (have ${appVersion}); update the app`);
  }
  debugLog.info('payload', `manifest ok run_date=${m.run_date} schema=${m.schema_version ?? 'n/a'}`);
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
    phaseComplete: false,
  });
  if (expectedSha) {
    // expo-crypto on Android bridges Uint8Array → Kotlin ByteArray; raw ArrayBuffer fails.
    await yieldToUi();
    const digest = await Crypto.digest(
      Crypto.CryptoDigestAlgorithm.SHA256,
      new Uint8Array(buf),
    );
    const actual = toHex(digest);
    if (actual !== expectedSha) {
      throw new Error(`asset sha256 mismatch (expected ${expectedSha.slice(0, 12)}…, got ${actual.slice(0, 12)}…)`);
    }
  }
  opts.onVerifiedBytes?.(new Uint8Array(buf).slice());
  emit(opts.onProgress, {
    phase: 'verify',
    fileName,
    bytesReceived: byteLen,
    totalBytes: byteLen,
    startedAt: verifyStarted,
    phaseComplete: true,
  });

  const inflateStarted = Date.now();
  emit(opts.onProgress, {
    phase: 'inflate',
    fileName,
    bytesReceived: byteLen,
    totalBytes: byteLen,
    startedAt: inflateStarted,
    phaseComplete: false,
  });
  // Always yield before inflate/decrypt/gunzip — compressed byteLen can be well
  // under the parse threshold while the expanded JSON is multi-MB on the JS thread.
  await yieldToUi();
  let bytes: Uint8Array = new Uint8Array(buf);
  // Encrypted assets (ARE1 magic) are decrypted to the gzip layer first; the
  // sha256 above was computed over the ciphertext, matching the manifest.
  if (isEncryptedAsset(bytes)) {
    if (opts.allowEncrypted === false) throw new Error('encrypted asset is not allowed by this contract');
    bytes = decryptAsset(bytes, await resolvePayloadKeyHex());
  }
  // GitHub release assets are served raw; the bytes are our gzip. If a proxy
  // already decoded gzip transport, the bytes are plain JSON — handle both.
  const looksGzipped = bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
  if (opts.expectedEncoding === 'gzip' && !looksGzipped) {
    throw new Error('asset encoding mismatch (expected gzip)');
  }
  if (opts.expectedEncoding === 'identity' && looksGzipped) {
    throw new Error('asset encoding mismatch (expected identity)');
  }
  if (!looksGzipped) {
    if (opts.maxInflatedBytes != null && bytes.length > opts.maxInflatedBytes) {
      throw new Error(`inflated asset exceeds ${opts.maxInflatedBytes} byte limit`);
    }
    if (opts.requireExactBytes && opts.expectedInflatedBytes != null && bytes.length !== opts.expectedInflatedBytes) {
      throw new Error(`inflated asset size mismatch (expected ${opts.expectedInflatedBytes}, got ${bytes.length})`);
    }
    emit(opts.onProgress, {
      phase: 'inflate',
      fileName,
      bytesReceived: byteLen,
      totalBytes: byteLen,
      startedAt: inflateStarted,
      phaseComplete: true,
    });
    return strFromU8(bytes);
  }
  const inflated = bytes.length >= YIELD_BEFORE_HEAVY_BYTES || opts.maxInflatedBytes != null
    ? await gunzipCooperatively(bytes, INFLATE_CHUNK_BYTES, opts.maxInflatedBytes)
    : gunzipSync(bytes);
  if (opts.requireExactBytes && opts.expectedInflatedBytes != null && inflated.length !== opts.expectedInflatedBytes) {
    throw new Error(`inflated asset size mismatch (expected ${opts.expectedInflatedBytes}, got ${inflated.length})`);
  }
  emit(opts.onProgress, {
    phase: 'inflate',
    fileName,
    bytesReceived: byteLen,
    totalBytes: byteLen,
    startedAt: inflateStarted,
    phaseComplete: true,
  });
  return strFromU8(inflated);
}

export interface CoreResult {
  text: string;
  core: CorePayload;
  integrity: CoreIntegrityContext;
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
    bytesReceived: 0,
    totalBytes: text.length,
    startedAt: parseStarted,
    phaseComplete: false,
  });
  const normalized = normalizeCoreWithIntegrity(
    await parseJsonHeavy<CorePayload>(text),
    { coreSha256: expectedSha ?? null },
  );
  // Leave parse incomplete until the caller finishes cache install — otherwise
  // the bar hits 100% while writeBundle is still flushing multi-MB JSON.
  emit(opts.onProgress, {
    phase: 'install',
    fileName,
    bytesReceived: 0,
    totalBytes: text.length,
    startedAt: Date.now(),
    phaseComplete: false,
  });
  return { text, core: normalized.core, integrity: normalized.integrity };
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
    bytesReceived: 0,
    totalBytes: text.length,
    startedAt: parseStarted,
    phaseComplete: false,
  });
  const details = await parseJsonHeavy<DetailsPayload>(text);
  emit(opts.onProgress, {
    phase: 'parse',
    fileName,
    bytesReceived: text.length,
    totalBytes: text.length,
    startedAt: parseStarted,
    phaseComplete: true,
  });
  return { text, details: bindVerifiedDetails(details, expectedSha) };
}

export interface SearchIndexResult {
  text: string;
  searchIndex: import('./detailSearch').SearchIndexPayload;
}

export async function downloadSearchIndex(
  url: string,
  expectedSha?: string,
  opts: DownloadOpts = {},
): Promise<SearchIndexResult> {
  const text = await downloadInflate(url, expectedSha, opts);
  const searchIndex = await parseJsonHeavy<SearchIndexResult['searchIndex']>(text);
  return { text, searchIndex };
}

export interface BankInsightsResult {
  text: string;
  bankInsights: import('./bankInsights').BankInsightsPayload;
}

export async function downloadBankInsights(
  url: string,
  expectedSha?: string,
  opts: DownloadOpts = {},
): Promise<BankInsightsResult> {
  const text = await downloadInflate(url, expectedSha, opts);
  const parsed = await parseJsonHeavy<unknown>(text);
  const bankInsights = normalizeBankInsightsPayload(parsed);
  if (!bankInsights) {
    throw new Error('bank_history payload failed validation');
  }
  return { text, bankInsights };
}

export async function downloadBankSpreadHistory(
  url: string,
  expectedSha: string,
  opts: DownloadOpts = {},
): Promise<{
  text: string;
  bankSpreadHistory: import('./bankSpreadHistory').BankSpreadHistoryPayload;
  verifiedBytes: Uint8Array;
}> {
  if (!/^[0-9a-f]{64}$/.test(expectedSha)) {
    throw new Error('bank_spread_history requires a lowercase SHA-256 descriptor');
  }
  let verifiedBytes: Uint8Array | null = null;
  const callerVerifiedBytes = opts.onVerifiedBytes;
  const text = await downloadInflate(url, expectedSha, {
    ...opts,
    maxCompressedBytes: Math.min(
      opts.maxCompressedBytes ?? BANK_SPREAD_MAX_COMPRESSED_BYTES,
      BANK_SPREAD_MAX_COMPRESSED_BYTES,
    ),
    maxInflatedBytes: Math.min(
      opts.maxInflatedBytes ?? BANK_SPREAD_MAX_INFLATED_BYTES,
      BANK_SPREAD_MAX_INFLATED_BYTES,
    ),
    expectedEncoding: 'gzip',
    allowEncrypted: false,
    onVerifiedBytes(bytes) {
      verifiedBytes = bytes;
      callerVerifiedBytes?.(bytes.slice());
    },
  });
  if (!verifiedBytes) throw new Error('bank_spread_history raw bytes were not verified');
  const parsed = await parseJsonHeavy<unknown>(text);
  const bankSpreadHistory = normalizeBankSpreadHistoryPayload(parsed);
  if (!bankSpreadHistory) throw new Error('bank_spread_history payload failed validation');
  return { text, bankSpreadHistory, verifiedBytes };
}

export interface HistoryBanksResult {
  text: string;
  historyBanks: import('./historyPayload').HistoryBanksPayload;
}

export async function downloadHistoryBanks(
  url: string,
  expectedSha?: string,
  opts: DownloadOpts = {},
): Promise<HistoryBanksResult> {
  const text = await downloadInflate(url, expectedSha, opts);
  const parsed = await parseJsonHeavy<unknown>(text);
  const historyBanks = normalizeHistoryBanksPayload(parsed);
  if (!historyBanks) {
    throw new Error('history_banks payload failed validation');
  }
  return { text, historyBanks };
}

export interface RbaCalendarResult {
  text: string;
  rbaCalendar: import('./rbaCalendar').RbaCalendar;
}

export async function downloadRbaCalendar(
  url: string,
  expectedSha?: string,
  opts: DownloadOpts = {},
): Promise<RbaCalendarResult> {
  const text = await downloadInflate(url, expectedSha, opts);
  const parsed = await parseJsonHeavy<unknown>(text);
  const rbaCalendar = normalizeRbaCalendar(parsed);
  if (!rbaCalendar) {
    throw new Error('rba_calendar payload failed validation');
  }
  return { text, rbaCalendar };
}
