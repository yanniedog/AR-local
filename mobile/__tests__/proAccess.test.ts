import { DEFAULT_PREFS } from '../src/data/store';
import type { Subscription } from '../src/data/subscriptions';
import {
  canAddAlertSubscription,
  effectiveBankInsights,
  effectiveDeepSearch,
  effectiveHistoryRibbon,
  FREE_ALERT_SLOTS,
  hasProAccess,
  proGateCopy,
} from '../src/lib/proAccess';

const productSub: Subscription = {
  id: 'product:a:1',
  kind: 'product',
  productKey: 'a',
  rateIndex: 1,
  label: 'Test',
  createdAt: '2026-01-01T00:00:00.000Z',
};

describe('proAccess', () => {
  it('defaults to free tier', () => {
    expect(DEFAULT_PREFS.rateIntelligencePro).toBe(false);
    expect(hasProAccess(DEFAULT_PREFS)).toBe(false);
    expect(FREE_ALERT_SLOTS).toBe(1);
  });

  it('gates optional features until Pro', () => {
    const prefs = { ...DEFAULT_PREFS, enableDeepSearch: true, showHistoryRibbon: true };
    expect(effectiveDeepSearch(prefs)).toBe(false);
    expect(effectiveHistoryRibbon(prefs)).toBe(false);
    expect(effectiveDeepSearch({ ...prefs, rateIntelligencePro: true })).toBe(true);
    expect(effectiveHistoryRibbon({ ...prefs, rateIntelligencePro: true })).toBe(true);
  });

  it('bank insights ship with Pro, no extra pref required', () => {
    expect(effectiveBankInsights(DEFAULT_PREFS)).toBe(false);
    expect(effectiveBankInsights({ ...DEFAULT_PREFS, rateIntelligencePro: true })).toBe(true);
  });

  it('allows one alert on free tier', () => {
    expect(canAddAlertSubscription([], DEFAULT_PREFS)).toBe(true);
    expect(canAddAlertSubscription([productSub], DEFAULT_PREFS)).toBe(false);
    expect(canAddAlertSubscription([productSub], { ...DEFAULT_PREFS, rateIntelligencePro: true })).toBe(true);
  });

  it('returns paywall copy for each intent', () => {
    expect(proGateCopy('alert_limit').bullets.length).toBeGreaterThan(0);
    expect(proGateCopy('deep_search').title).toMatch(/Pro/);
    expect(proGateCopy('history_ribbon').bullets.some((b) => /history/i.test(b))).toBe(true);
    expect(proGateCopy('bank_insights').bullets.some((b) => /RBA pass-through/i.test(b))).toBe(true);
  });
});
