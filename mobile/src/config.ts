import Constants from 'expo-constants';

type Extra = {
  repo?: string;
  releaseTag?: string;
  manifestUrl?: string;
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

/** Schema version this build understands. Older payloads still load best-effort. */
export const SUPPORTED_SCHEMA = 1;

/** Local-notification defaults. */
export const RATE_MOVE_BPS_THRESHOLD = 5; // notify when a category best rate moves >= 5bps
