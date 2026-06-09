import type { Subscription } from './subscriptions';

export interface OptionalFeaturePrefs {
  enableDeepSearch: boolean;
  showHistoryRibbon: boolean;
  notificationsEnabled: boolean;
}

/** True when refresh/background should download the bulk details payload. */
export function shouldWarmDetails(prefs: OptionalFeaturePrefs, subscriptions: Subscription[]): boolean {
  if (prefs.enableDeepSearch) return true;
  if (!prefs.notificationsEnabled) return false;
  return subscriptions.some(
    (s) =>
      s.kind === 'search' &&
      ((s.filters.accountFeatures?.length ?? 0) > 0 ||
        (s.filters.eligibilityCriteria?.length ?? 0) > 0),
  );
}
