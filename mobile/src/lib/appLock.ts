import * as LocalAuthentication from 'expo-local-authentication';

import { debugLog } from './debugLog';

/**
 * Biometric app lock (fingerprint / Face ID) — Phase C of
 * docs/SECURITY_CDR_PIPELINE.md. The OS prompt falls back to the device
 * PIN/pattern, so an unenrolled finger can't soft-lock the user out.
 */

export async function biometricsAvailable(): Promise<boolean> {
  try {
    return (await LocalAuthentication.hasHardwareAsync()) && (await LocalAuthentication.isEnrolledAsync());
  } catch {
    return false;
  }
}

export async function authenticateBiometric(promptMessage: string): Promise<boolean> {
  try {
    const res = await LocalAuthentication.authenticateAsync({
      promptMessage,
      cancelLabel: 'Cancel',
    });
    if (!res.success) debugLog.info('appLock', `auth failed: ${res.error ?? 'unknown'}`);
    return res.success;
  } catch (err) {
    debugLog.warn('appLock', `auth error: ${String((err as Error)?.message ?? err)}`);
    return false;
  }
}
