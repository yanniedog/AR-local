import * as SecureStore from 'expo-secure-store';

import { PAYLOAD_DEC_KEY_HEX } from '../config';
import { debugLog } from './debugLog';

/**
 * Hardware-backed custody for the payload decryption key (Phase C of
 * docs/SECURITY_CDR_PIPELINE.md). Resolution order: SecureStore (set after
 * sign-in, and by the Phase D key service later) → bundled config key.
 * Stored AFTER_FIRST_UNLOCK (not biometric-per-read) so scheduled background
 * payload refreshes keep working; interactive access is gated by the app lock.
 */

const STORE_KEY = 'ar.payload.deckey';

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

export async function storePayloadKeyHex(hex: string): Promise<void> {
  await SecureStore.setItemAsync(STORE_KEY, hex, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK,
  });
  cached = hex;
}

/** Mirror the bundled config key into SecureStore once a user signs in. */
export async function adoptConfigKey(): Promise<void> {
  if (!PAYLOAD_DEC_KEY_HEX) return;
  try {
    if (!(await SecureStore.getItemAsync(STORE_KEY))) {
      await storePayloadKeyHex(PAYLOAD_DEC_KEY_HEX);
    }
  } catch (err) {
    debugLog.warn('keyVault', `adopt failed: ${String((err as Error)?.message ?? err)}`);
  }
}

export function clearKeyCacheForTests(): void {
  cached = null;
}
