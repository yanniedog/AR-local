import Constants from 'expo-constants';

type Extra = {
  repo?: string;
  releaseTag?: string;
  manifestUrl?: string;
  datesIndexUrl?: string;
  apkReleaseTag?: string;
  apkManifestUrl?: string;
  payloadDecKeyHex?: string;
};

const extra = (Constants.expoConfig?.extra ?? {}) as Extra;

export const REPO = extra.repo ?? 'yanniedog/AR-local';
export const RELEASE_TAG = extra.releaseTag ?? 'app-payload-latest';

/** Immutable per-run_date snapshot tags: ``app-payload-YYYY-MM-DD``. */
export const DATED_TAG_PREFIX = 'app-payload-';

/**
 * URL of the rolling manifest the Pi publishes each day. The manifest in turn
 * points at the (date-stamped) core/details asset URLs, so the app only needs a
 * single stable URL baked in here.
 */
export const MANIFEST_URL =
  extra.manifestUrl ??
  `https://github.com/${REPO}/releases/download/${RELEASE_TAG}/manifest.json`;

/** Index of published history dates (refreshed after ingest / backfill). */
export const DATES_INDEX_URL =
  extra.datesIndexUrl ??
  MANIFEST_URL.replace(/\/manifest\.json$/i, '/dates-index.json');

/** Manifest URL for one immutable dated snapshot release. */
export function datedManifestUrl(runDate: string): string {
  return `https://github.com/${REPO}/releases/download/${DATED_TAG_PREFIX}${runDate}/manifest.json`;
}

export const APK_RELEASE_TAG = extra.apkReleaseTag ?? 'app-apk-latest';

/** Rolling APK manifest published after preview EAS builds (see mobile-eas-build.yml). */
export const APK_MANIFEST_URL =
  extra.apkManifestUrl ??
  `https://github.com/${REPO}/releases/download/${APK_RELEASE_TAG}/app-apk-latest.json`;

/** Schema version this build understands. Older payloads still load best-effort. */
export const SUPPORTED_SCHEMA = 1;

/**
 * AES-256-GCM key (64 hex chars) for encrypted payload assets — Phase B of
 * docs/SECURITY_CDR_PIPELINE.md. Interim static key (obfuscation, not security);
 * Phase D replaces this with auth-gated key issuance. Empty = decryption
 * unavailable; the Pi must keep AR_LOCAL_PAYLOAD_ENC off until this is set in a
 * shipped build. Override via app.json extra.payloadDecKeyHex.
 */
export const PAYLOAD_DEC_KEY_HEX: string = extra.payloadDecKeyHex ?? '';

/** Local-notification defaults. */
export const RATE_MOVE_BPS_THRESHOLD = 5; // notify when a category best rate moves >= 5bps
