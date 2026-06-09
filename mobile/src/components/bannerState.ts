import type { PayloadProgressSnapshot } from '../data/downloadProgress';

/** Resolved offline / sample-connect banner visibility and copy. */
export type OfflineBannerMode = 'hidden' | 'connecting' | 'offline-cached' | 'offline-sample';

export interface OfflineBannerViewModel {
  mode: OfflineBannerMode;
  showLiveProgress: boolean;
  message: string;
}

export function resolveOfflineBanner(
  source: string,
  offline: boolean,
  refreshing: boolean,
  payloadProgress: PayloadProgressSnapshot | null,
): OfflineBannerViewModel {
  const sample = source === 'sample';

  if (!offline && !sample) {
    return { mode: 'hidden', showLiveProgress: false, message: '' };
  }

  if (sample && !refreshing && !offline) {
    return { mode: 'hidden', showLiveProgress: false, message: '' };
  }

  if (sample && refreshing) {
    const showLiveProgress = payloadProgress != null;
    return {
      mode: 'connecting',
      showLiveProgress,
      message: 'Showing bundled sample data — connecting for the latest…',
    };
  }

  if (sample && offline) {
    return {
      mode: 'offline-sample',
      showLiveProgress: false,
      message: 'Offline — showing bundled sample data.',
    };
  }

  return {
    mode: 'offline-cached',
    showLiveProgress: false,
    message: 'Offline — showing the last downloaded rates.',
  };
}
