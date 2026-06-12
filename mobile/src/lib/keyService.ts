import { KEY_SERVICE_URL } from '../config';
import { debugLog } from './debugLog';
import { resolvePayloadKeyHex, storePayloadKeyHex } from './keyVault';

/**
 * Client for the issueContentKeys callable (Phase D of
 * docs/SECURITY_CDR_PIPELINE.md). Speaks the Firebase callable HTTP protocol
 * directly ({data} → {result|error}) with the signed-in user's ID token, so no
 * extra native module is needed. Dormant until `extra.keyServiceUrl` is set.
 */

export interface IssuedKey {
  scope: string;
  alg: string;
  key_id: string;
  key_hex: string;
}

export interface IssuedKeys {
  tier: string;
  keys: IssuedKey[];
}

export function isKeyServiceConfigured(): boolean {
  return KEY_SERVICE_URL.length > 0;
}

async function currentIdToken(): Promise<string> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- lazy native module
  const { getAuth } = require('@react-native-firebase/auth') as typeof import('@react-native-firebase/auth');
  const user = getAuth().currentUser;
  if (!user) throw new Error('sign in before requesting content keys');
  return user.getIdToken();
}

export async function fetchContentKeys(url: string = KEY_SERVICE_URL): Promise<IssuedKeys> {
  if (!url) {
    throw new Error('key service is not configured for this build');
  }
  const token = await currentIdToken();
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ data: {} }),
  });
  const body = (await res.json().catch(() => null)) as
    | { result?: IssuedKeys; error?: { message?: string; status?: string } }
    | null;
  if (!res.ok || !body?.result) {
    throw new Error(body?.error?.message ?? `key service HTTP ${res.status}`);
  }
  return body.result;
}

/**
 * Fetch and persist the best usable key into the secure vault. Returns true
 * when a key was stored. Failures only log — payload decryption falls back to
 * the previously stored or bundled key.
 *
 * Skips the network call when the vault already holds a key (unless `force`),
 * so routine app starts don't burn the service's per-user daily issue limit;
 * key rotation will force-refresh on decrypt failure (Phase E).
 */
export async function syncContentKeys(
  url: string = KEY_SERVICE_URL,
  { force = false }: { force?: boolean } = {},
): Promise<boolean> {
  if (!url) return false;
  if (!force && (await resolvePayloadKeyHex())) return false;
  try {
    const issued = await fetchContentKeys(url);
    // Hex keys are normalized to lowercase so a copy-pasted uppercase secret
    // still validates and matches the Pi/app key-id derivation.
    const usable = (issued?.keys ?? [])
      .map((k) => ({ ...k, key_hex: String(k?.key_hex ?? '').trim().toLowerCase() }))
      .find((k) => k?.alg === 'aes-256-gcm' && /^[0-9a-f]{64}$/.test(k?.key_hex));
    if (!usable) {
      debugLog.warn('keyService', `no usable key in response (tier=${issued.tier})`);
      return false;
    }
    await storePayloadKeyHex(usable.key_hex);
    debugLog.info('keyService', `stored ${usable.scope} key id=${usable.key_id} tier=${issued.tier}`);
    return true;
  } catch (err) {
    debugLog.warn('keyService', `sync failed: ${String((err as Error)?.message ?? err)}`);
    return false;
  }
}
