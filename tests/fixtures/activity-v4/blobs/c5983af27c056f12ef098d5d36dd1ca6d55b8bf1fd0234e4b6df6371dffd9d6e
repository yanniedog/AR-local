import * as SecureStore from 'expo-secure-store';

import { PAYLOAD_DEC_KEY_HEX } from '../config';
import { debugLog } from './debugLog';
import { SECURE_STORE_KEYS } from './secureStoreKey';

/**
 * Compatibility custody for legacy payload decryption keys. Resolution order:
 * SecureStore, then the optional bundled compatibility key.
 * Existing values were stored AFTER_FIRST_UNLOCK, so scheduled background
 * refreshes can still read legacy assets; interactive access is app-lock gated.
 */

const STORE_KEY = SECURE_STORE_KEYS.payloadDecryptionKey;

let cached: string | null = null;

export async function resolvePayloadKeyHex(): Promise<string> {
  if (cached) return cached;
  try {
    const stored = await SecureStore.getItemAsync(STORE_KEY);
    if (stored) {
      cached = stored;
      return stored;
    }
  } catch (err) {
    debugLog.warn('keyVault', `read failed: ${String((err as Error)?.message ?? err)}`);
  }
  return PAYLOAD_DEC_KEY_HEX;
}

export function clearKeyCacheForTests(): void {
  cached = null;
}
