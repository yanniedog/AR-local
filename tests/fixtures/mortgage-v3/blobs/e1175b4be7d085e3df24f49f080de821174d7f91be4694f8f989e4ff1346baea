import Constants from 'expo-constants';

type Extra = {
  payloadRepo?: string;
  payloadReleaseTag?: string;
  repo?: string;
  releaseTag?: string;
  manifestUrl?: string;
  datesIndexUrl?: string;
  apkRepo?: string;
  apkReleaseTag?: string;
  apkManifestUrl?: string;
  apkArmReleaseTag?: string;
  apkArmManifestUrl?: string;
  iosInstallUrl?: string;
  payloadDecKeyHex?: string;
  selfUpdateEnabled?: boolean;
};

const extra = (Constants.expoConfig?.extra ?? {}) as Extra;

export const PAYLOAD_REPO = extra.payloadRepo ?? extra.repo ?? 'yanniedog/AR-local';
export const RELEASE_TAG = extra.payloadReleaseTag ?? extra.releaseTag ?? 'app-payload-latest';
export const APK_REPO = extra.apkRepo ?? extra.repo ?? 'yanniedog/AR-app';
export const REPO = APK_REPO;

/** Immutable per-run_date snapshot tags: ``app-payload-YYYY-MM-DD``. */
export const DATED_TAG_PREFIX = 'app-payload-';

/**
 * URL of the rolling manifest the Pi publishes each day. The manifest in turn
 * points at the (date-stamped) core/details asset URLs, so the app only needs a
 * single stable URL baked in here.
 */
export const MANIFEST_URL =
  extra.manifestUrl ??
  `https://github.com/${PAYLOAD_REPO}/releases/download/${RELEASE_TAG}/manifest.json`;

/** Index of published history dates (refreshed after ingest / backfill). */
export const DATES_INDEX_URL =
  extra.datesIndexUrl ??
  MANIFEST_URL.replace(/\/manifest\.json$/i, '/dates-index.json');

/** Manifest URL for one immutable dated snapshot release. */
export function datedManifestUrl(runDate: string): string {
  return `https://github.com/${PAYLOAD_REPO}/releases/download/${DATED_TAG_PREFIX}${runDate}/manifest.json`;
}

export const APK_RELEASE_TAG = extra.apkReleaseTag ?? 'app-apk-latest';
export const APK_ARM_RELEASE_TAG = extra.apkArmReleaseTag ?? 'app-apk-arm-latest';
/** Both rolling tags intentionally use the same asset name; the tag selects the channel. */
export const APK_MANIFEST_ASSET = 'app-apk-latest.json';

/** Rolling APK manifest published after preview EAS builds (see mobile-eas-build.yml). */
export const APK_MANIFEST_URL =
  extra.apkManifestUrl ??
  `https://github.com/${APK_REPO}/releases/download/${APK_RELEASE_TAG}/${APK_MANIFEST_ASSET}`;

/** ARM-only rolling channel used only by ABI-aware clients; universal remains the fallback. */
export const APK_ARM_MANIFEST_URL =
  extra.apkArmManifestUrl ??
  `https://github.com/${APK_REPO}/releases/download/${APK_ARM_RELEASE_TAG}/${APK_MANIFEST_ASSET}`;

/** False in Google Play builds, whose updates are exclusively Play-managed. */
export const SELF_UPDATE_ENABLED = extra.selfUpdateEnabled !== false;
export const PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=com.eyex.australianrates';
/** App Store or public TestFlight URL. Null until an iOS install destination is published. */
export const IOS_INSTALL_URL = String(extra.iosInstallUrl ?? '').trim() || null;

/** Schema version this build understands. Older payloads still load best-effort. */
export const SUPPORTED_SCHEMA = 1;

/**
 * AES-256-GCM key (64 hex chars) retained only for compatibility with legacy
 * encrypted payload assets. Empty means legacy decryption is unavailable.
 * New payload contracts must not depend on an account or remote key service.
 */
export const PAYLOAD_DEC_KEY_HEX: string = extra.payloadDecKeyHex ?? '';

/** Local-notification defaults. */
export const RATE_MOVE_BPS_THRESHOLD = 5; // notify when a category best rate moves >= 5bps

/**
 * Minimum deposit rate (fraction) treated as a real savings/TD interest offer.
 *
 * CDR payloads include many transaction, offset, and FX accounts at ~0.01% (1bp)
 * — token rates that are not savings products users want when hunting for the
 * best interest rate. 0.10% (10bp) drops that junk class while keeping low-but-
 * intentional savers (sample AR-local cores show genuine-ish floors from ~0.25%+).
 * Mortgages are never gated by this floor.
 */
export const MIN_MEANINGFUL_DEPOSIT_RATE_FRACTION = 0.001; // 0.10%

/** True when `fraction` clears the deposit token-rate floor (mortgages always pass). */
export function isMeaningfulDepositRate(
  fraction: number,
  section: 'Mortgage' | 'Savings' | 'TD' | string,
): boolean {
  if (section === 'Mortgage') return true;
  return fraction >= MIN_MEANINGFUL_DEPOSIT_RATE_FRACTION;
}
