import type { DetailsPayload } from '../types';
import * as Crypto from 'expo-crypto';

// Provenance belongs to the parsed object, not merely the current store manifest.
const identities = new WeakMap<DetailsPayload, string>();
export function bindVerifiedDetails(details: DetailsPayload, assetSha256?: string | null): DetailsPayload {
  if (assetSha256 && /^[a-f0-9]{64}$/.test(assetSha256)) identities.set(details, assetSha256);
  return details;
}
export function verifiedDetailsSha(details: DetailsPayload): string | null { return identities.get(details) ?? null; }
export async function detailsCacheIdentity(text: string, assetSha256: string) {
  return { schemaVersion: 1, assetSha256, contentSha256: await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, text) };
}
export async function bindCachedDetails(details: DetailsPayload, text: string, identity: unknown, expectedSha?: string | null): Promise<DetailsPayload> {
  const saved = identity as { schemaVersion?: unknown; assetSha256?: unknown; contentSha256?: unknown } | null;
  if (expectedSha && saved?.schemaVersion === 1 && saved.assetSha256 === expectedSha &&
      typeof saved.contentSha256 === 'string' && /^[a-f0-9]{64}$/.test(saved.contentSha256) &&
      saved.contentSha256 === await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, text)) bindVerifiedDetails(details, expectedSha);
  return details;
}
