import * as Crypto from 'expo-crypto';
import { gunzipSync, strFromU8 } from 'fflate';

import { MANIFEST_URL } from '../config';
import type { CorePayload, DetailsPayload, Manifest } from '../types';

/** Fetch and parse the rolling manifest. Throws on network/HTTP errors. */
export async function fetchManifest(url: string = MANIFEST_URL): Promise<Manifest> {
  const res = await fetch(url, { cache: 'no-store' as RequestCache });
  if (!res.ok) throw new Error(`manifest HTTP ${res.status}`);
  return (await res.json()) as Manifest;
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
export async function downloadInflate(url: string, expectedSha?: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`asset HTTP ${res.status}`);
  const buf = await res.arrayBuffer();
  if (expectedSha) {
    const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, buf);
    const actual = toHex(digest);
    if (actual !== expectedSha) {
      throw new Error(`asset sha256 mismatch (expected ${expectedSha.slice(0, 12)}…, got ${actual.slice(0, 12)}…)`);
    }
  }
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

export async function downloadCore(url: string, expectedSha?: string): Promise<CoreResult> {
  const text = await downloadInflate(url, expectedSha);
  return { text, core: JSON.parse(text) as CorePayload };
}

export interface DetailsResult {
  text: string;
  details: DetailsPayload;
}

export async function downloadDetails(url: string, expectedSha?: string): Promise<DetailsResult> {
  const text = await downloadInflate(url, expectedSha);
  return { text, details: JSON.parse(text) as DetailsPayload };
}
