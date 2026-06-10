import { effectiveDeepSearch } from '../lib/proAccess';
import type { Subscription } from './subscriptions';

export interface OptionalFeaturePrefs {
  enableDeepSearch: boolean;
  showHistoryRibbon: boolean;
  notificationsEnabled: boolean;
  rateIntelligencePro: boolean;
}

/** True when refresh/background should download the bulk details payload. */
export function shouldWarmDetails(prefs: OptionalFeaturePrefs, subscriptions: Subscription[]): boolean {
  if (effectiveDeepSearch(prefs)) return true;

  if (!prefs.notificationsEnabled) return false;

  return subscriptions.some(
    (s) =>
      s.kind === 'search' &&
      ((s.filters?.accountFeatures?.length ?? 0) > 0 ||
        (s.filters?.eligibilityCriteria?.length ?? 0) > 0),
  );
}
