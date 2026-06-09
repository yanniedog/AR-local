import * as BackgroundFetch from 'expo-background-fetch';
import * as Notifications from 'expo-notifications';

import { SECTIONS, SECTION_ORDER } from '../constants';
import type { CorePayload, ProductDetail, RateRow, SectionKey } from '../types';
import { bpsBetween, formatRate, toFraction } from './format';
import { bestRow } from './selectors';
import { computeSubscriptionChanges, type Subscription } from './subscriptions';

export const BACKGROUND_TASK = 'ar-rates-daily-refresh';

// Foreground presentation. (SDK 53+ replaced shouldShowAlert with shouldShowBanner/List.)
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

export interface NotifyMessage {
  title: string;
  body: string;
}

function bestFraction(core: CorePayload, section: SectionKey): number | null {
  const rows = core.sections[section]?.rates ?? [];
  const best = bestRow(rows, section);
  return best ? toFraction(best.rate) : null;
}

/** All rate rows for a product, keyed by rate_index, so changes can be matched
 *  row-for-row (a product can have many rows; comparing only the first misses
 *  changes and a row-order change would create false alerts). */
function ratesByIndex(core: CorePayload, productKey: string): Map<number, { row: RateRow; fraction: number | null }> {
  const out = new Map<number, { row: RateRow; fraction: number | null }>();
  for (const section of SECTION_ORDER) {
    for (const row of core.sections[section]?.rates ?? []) {
      if (row.product_key !== productKey) continue;
      out.set(row.rate_index ?? out.size, { row, fraction: toFraction(row.rate) });
    }
  }
  return out;
}

/**
 * Pure diff: compare two payloads and produce user-facing change messages.
 * Exposed (and unit-tested) separately from the scheduling side-effect.
 */

function dedupeNotifyMessages(messages: NotifyMessage[]): NotifyMessage[] {
  const seen = new Set<string>();
  return messages.filter((m) => {
    const key = `${m.title}\0${m.body}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function computeChanges(
  oldCore: CorePayload | null,
  newCore: CorePayload,
  favorites: string[],
  thresholdBps: number,
  subscriptions: Subscription[] = [],
  oldDetailsProducts?: Record<string, ProductDetail> | null,
  newDetailsProducts?: Record<string, ProductDetail> | null,
): NotifyMessage[] {
  if (!oldCore) return [];
  const subscriptionMessages = computeSubscriptionChanges(
    oldCore,
    newCore,
    subscriptions,
    thresholdBps,
    oldDetailsProducts,
    newDetailsProducts,
  );
  const messages: NotifyMessage[] = [];

  // Per-category best-rate moves.
  for (const section of SECTION_ORDER) {
    const before = bestFraction(oldCore, section);
    const after = bestFraction(newCore, section);
    if (before === null || after === null) continue;
    const bps = Math.abs(bpsBetween(after, before) ?? 0);
    if (bps < thresholdBps) continue;
    const meta = SECTIONS[section];
    const improved = meta.lowerIsBetter ? after < before : after > before;
    messages.push({
      title: `${meta.title}: best rate ${improved ? 'improved' : 'changed'}`,
      body: `Now ${formatRate(after)} (was ${formatRate(before)}).`,
    });
  }

  // RBA cash-rate change.
  const oldRba = oldCore.rba.at(-1);
  const newRba = newCore.rba.at(-1);
  if (oldRba && newRba && newRba.date !== oldRba.date && newRba.rate !== oldRba.rate) {
    messages.push({
      title: 'RBA cash rate changed',
      body: `Cash rate is now ${newRba.rate.toFixed(2)}% (was ${oldRba.rate.toFixed(2)}%).`,
    });
  }

  // Watchlisted products — compare row-for-row by rate_index and report the largest
  // qualifying move (order-independent; catches changes to any rate row, not just the first).
  for (const key of favorites) {
    const before = ratesByIndex(oldCore, key);
    const after = ratesByIndex(newCore, key);
    let biggest: { row: RateRow; from: number; to: number; bps: number } | null = null;
    for (const [index, nw] of after) {
      const od = before.get(index);
      if (!od || od.fraction === null || nw.fraction === null) continue;
      const bps = Math.abs(bpsBetween(nw.fraction, od.fraction) ?? 0);
      if (bps >= thresholdBps && (!biggest || bps > biggest.bps)) {
        biggest = { row: nw.row, from: od.fraction, to: nw.fraction, bps };
      }
    }
    if (biggest) {
      messages.push({
        title: `${biggest.row.provider} rate changed`,
        body: `${biggest.row.product_name}: ${formatRate(biggest.from)} → ${formatRate(biggest.to)}.`,
      });
    }
  }

  return dedupeNotifyMessages([...subscriptionMessages, ...messages]);
}

export async function ensurePermissions(): Promise<boolean> {
  try {
    const current = await Notifications.getPermissionsAsync();
    if (current.granted) return true;
    const req = await Notifications.requestPermissionsAsync();
    return req.granted;
  } catch {
    return false;
  }
}

export async function notify(messages: NotifyMessage[]): Promise<void> {
  if (!messages.length) return;
  if (!(await ensurePermissions())) return;
  // Collapse a flurry into at most a few notifications.
  for (const msg of messages.slice(0, 3)) {
    await Notifications.scheduleNotificationAsync({
      content: { title: msg.title, body: msg.body },
      trigger: null, // immediate
    });
  }
}

// --- Background refresh ---------------------------------------------------- //
// The OS-scheduled task is defined in store.ts (where it can rehydrate persisted
// state and call refresh() directly, even on a headless/terminated launch).
export async function registerBackgroundRefresh(): Promise<void> {
  try {
    await BackgroundFetch.registerTaskAsync(BACKGROUND_TASK, {
      minimumInterval: 60 * 60 * 6, // ~ every 6h (OS decides actual cadence)
      stopOnTerminate: false,
      startOnBoot: true,
    });
  } catch {
    // Background fetch may be unavailable (e.g. web / simulator) — non-fatal.
  }
}

export async function unregisterBackgroundRefresh(): Promise<void> {
  try {
    await BackgroundFetch.unregisterTaskAsync(BACKGROUND_TASK);
  } catch {
    // ignore
  }
}
