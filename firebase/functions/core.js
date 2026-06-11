// Pure decision logic for issueContentKeys — kept dependency-free so it can be
// unit-tested with `node --test` and reviewed without Firebase context.
import { createHash } from 'node:crypto';

/**
 * Until payment systems exist, every authenticated user gets the full-history
 * tier (owner decision, 2026-06-11). Flip ENFORCE_TIERS once paid claims are
 * being set; free tier then only receives the `current` scope.
 */
export const ENFORCE_TIERS = false;

export const DAILY_ISSUE_LIMIT = 20;

/** Tier from Firebase custom claims; unknown/missing claims are free. */
export function resolveTier(claims) {
  if (!ENFORCE_TIERS) return 'full';
  return claims && claims.tier === 'full' ? 'full' : 'free';
}

/** Key scopes a tier may decrypt. Mirrors the windowed-asset plan. */
export function scopesForTier(tier) {
  return tier === 'full' ? ['full'] : ['current'];
}

/** Same non-secret key id derivation as payload_crypto.py / payloadCrypto.ts. */
export function keyId(keyHex) {
  return createHash('sha256')
    .update(Buffer.concat([Buffer.from('ar-local-payload-key:'), Buffer.from(keyHex, 'hex')]))
    .digest('hex')
    .slice(0, 8);
}

export function isValidKeyHex(keyHex) {
  return typeof keyHex === 'string' && /^[0-9a-f]{64}$/.test(keyHex);
}

/**
 * Fixed-window daily rate limit over a per-uid Firestore doc
 * ({ day: 'YYYY-MM-DD', count: n }). Returns the updated doc to write, or
 * null when the caller is over the limit.
 */
export function evaluateRateLimit(doc, nowMs, limit = DAILY_ISSUE_LIMIT) {
  const day = new Date(nowMs).toISOString().slice(0, 10);
  const count = doc && doc.day === day ? doc.count : 0;
  if (count >= limit) return null;
  return { day, count: count + 1 };
}
