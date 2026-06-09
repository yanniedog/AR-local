import Constants from 'expo-constants';

type Extra = {
  repo?: string;
  releaseTag?: string;
  manifestUrl?: string;
  apkReleaseTag?: string;
  apkManifestUrl?: string;
};

const extra = (Constants.expoConfig?.extra ?? {}) as Extra;

export const REPO = extra.repo ?? 'yanniedog/AR-local';
export const RELEASE_TAG = extra.releaseTag ?? 'app-payload-latest';

/**
 * URL of the rolling manifest the Pi publishes each day. The manifest in turn
 * points at the (date-stamped) core/details asset URLs, so the app only needs a
 * single stable URL baked in here.
 */
export const MANIFEST_URL =
  extra.manifestUrl ??
  `https://github.com/${REPO}/releases/download/${RELEASE_TAG}/manifest.json`;

export const APK_RELEASE_TAG = extra.apkReleaseTag ?? 'app-apk-latest';

/** Rolling APK manifest published after preview EAS builds (see mobile-eas-build.yml). */
export const APK_MANIFEST_URL =
  extra.apkManifestUrl ??
  `https://github.com/${REPO}/releases/download/${APK_RELEASE_TAG}/app-apk-latest.json`;

/** Schema version this build understands. Older payloads still load best-effort. */
export const SUPPORTED_SCHEMA = 1;

/** Local-notification defaults. */
export const RATE_MOVE_BPS_THRESHOLD = 5; // notify when a category best rate moves >= 5bps
