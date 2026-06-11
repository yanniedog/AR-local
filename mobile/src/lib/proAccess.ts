import type { Prefs } from '../data/store';
import type { Subscription } from '../data/subscriptions';

export const RATE_INTELLIGENCE_PRO = 'Rate Intelligence Pro';

/** Free tier: one product or search alert; additional alerts require Pro. */
export const FREE_ALERT_SLOTS = 1;

export type ProGateIntent = 'alert_limit' | 'deep_search' | 'history_ribbon' | 'bank_insights';

export function hasProAccess(prefs: Pick<Prefs, 'rateIntelligencePro'>): boolean {
  return prefs.rateIntelligencePro;
}

export function effectiveDeepSearch(prefs: Pick<Prefs, 'enableDeepSearch' | 'rateIntelligencePro'>): boolean {
  return prefs.enableDeepSearch && hasProAccess(prefs);
}

export function effectiveHistoryRibbon(prefs: Pick<Prefs, 'showHistoryRibbon' | 'rateIntelligencePro'>): boolean {
  return prefs.showHistoryRibbon && hasProAccess(prefs);
}

/** Bank intelligence (per-bank history + rate-move events) ships with Pro — no extra pref. */
export function effectiveBankInsights(prefs: Pick<Prefs, 'rateIntelligencePro'>): boolean {
  return hasProAccess(prefs);
}

export function canAddAlertSubscription(
  subscriptions: Subscription[],
  prefs: Pick<Prefs, 'rateIntelligencePro'>,
): boolean {
  if (hasProAccess(prefs)) return true;
  return subscriptions.length < FREE_ALERT_SLOTS;
}

export function proGateCopy(intent: ProGateIntent): { title: string; body: string; bullets: string[] } {
  switch (intent) {
    case 'alert_limit':
      return {
        title: RATE_INTELLIGENCE_PRO,
        body: 'Your first rate alert is free. Upgrade for unlimited product and search alerts.',
        bullets: [
          'Unlimited product rate alerts',
          'Unlimited saved-search alerts',
          'Deep product search (fees & features)',
          'Multi-day history ribbon chart',
        ],
      };
    case 'deep_search':
      return {
        title: RATE_INTELLIGENCE_PRO,
        body: 'Search fees, features, and eligibility across the full product catalogue.',
        bullets: [
          'Full-text deep product search',
          'Filter by account features & eligibility',
          'Unlimited rate alerts',
          'History ribbon in Charts & trends',
        ],
      };
    case 'history_ribbon':
      return {
        title: RATE_INTELLIGENCE_PRO,
        body: 'See how section rate ranges moved over recent ingest runs.',
        bullets: [
          'Multi-day min/median/max ribbon history',
          'RBA overlay on mortgage history',
          'Deep product search',
          'Unlimited rate alerts',
        ],
      };
    case 'bank_insights':
      return {
        title: RATE_INTELLIGENCE_PRO,
        body: 'Only Australian Rates tracks every bank, every day. See who moved rates which way, and who passes RBA changes on.',
        bullets: [
          'Daily rate-move feed across every tracked lender',
          'Biggest movers leaderboards',
          'RBA pass-through scorecard',
          'Per-bank rate history charts',
        ],
      };
  }
}
