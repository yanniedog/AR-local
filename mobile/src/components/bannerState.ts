import type { PayloadProgressSnapshot } from '../data/downloadProgress';

/** Transient refresh feedback shown after pull-to-refresh, manual refresh, or background sync. */
export type RefreshOutcomeKind = 'success' | 'failure' | 'wifi-skip';

export interface RefreshOutcomeViewModel {
  kind: RefreshOutcomeKind;
  message: string;
  actionLabel?: string;
  action: 'retry' | 'settings' | 'dismiss';
}

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
    return {
      mode: 'offline-sample',
      showLiveProgress: false,
      message: 'Showing bundled sample data.',
    };
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

/** Snackbar copy and action for a completed refresh attempt. */
export function resolveRefreshOutcomeSnackbar(
  kind: RefreshOutcomeKind,
  runDateLabel: string | null | undefined,
): RefreshOutcomeViewModel {
  switch (kind) {
    case 'success':
      return {
        kind,
        message: runDateLabel ? `Rates updated · ${runDateLabel}` : 'Rates updated',
        action: 'dismiss',
      };
    case 'failure':
      return {
        kind,
        message: 'Couldn\u2019t reach the server. Showing cached data.',
        actionLabel: 'Retry',
        action: 'retry',
      };
    case 'wifi-skip':
      return {
        kind,
        message: 'Skipped update \u2014 Wi\u2011Fi only is on',
        actionLabel: 'Settings',
        action: 'settings',
      };
  }
}
