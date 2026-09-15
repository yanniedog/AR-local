/**
 * Expo SecureStore accepts only non-empty ASCII alphanumeric keys plus `.`,
 * `-`, and `_`. Keep the app's complete static key registry here so a new key
 * cannot silently bypass the shared contract.
 */
export const SECURE_STORE_KEY_PATTERN = /^[A-Za-z0-9._-]+$/;

export const SECURE_STORE_KEY_ERROR_MESSAGE =
  'Invalid key provided to SecureStore. Keys must not be empty and contain only alphanumeric characters, ".", "-", and "_".';

declare const secureStoreKeyBrand: unique symbol;

export type SecureStoreKey = string & {
  readonly [secureStoreKeyBrand]: true;
};

export function defineSecureStoreKey<const T extends string>(value: T): T & SecureStoreKey {
  if (!SECURE_STORE_KEY_PATTERN.test(value)) {
    throw new Error(SECURE_STORE_KEY_ERROR_MESSAGE);
  }
  return value as T & SecureStoreKey;
}

export const SECURE_STORE_KEYS = Object.freeze({
  customerProfile: defineSecureStoreKey('ar.customer-profile.v1'),
  debugLogUploadReceipt: defineSecureStoreKey('ar.debug-log.public-upload-receipt.v1'),
  payloadDecryptionKey: defineSecureStoreKey('ar.payload.deckey'),
  performanceAuditRollbackScenario: defineSecureStoreKey(
    'performance-audit-rollback-scenario-v1',
  ),
  trackedRateAuditRollbackMetadata: defineSecureStoreKey(
    'ar-rates.performance-audit.tracked-rate-metadata.v1',
  ),
  trackedRateMetadata: defineSecureStoreKey('ar-rates.tracked-rate-metadata.v1'),
  userRateScenario: defineSecureStoreKey('user-rate-scenario-v1'),
});
