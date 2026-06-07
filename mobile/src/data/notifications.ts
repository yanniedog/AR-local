import * as BackgroundFetch from 'expo-background-fetch';
import * as Notifications from 'expo-notifications';

import { SECTIONS, SECTION_ORDER } from '../constants';
import type { CorePayload, RateRow, SectionKey } from '../types';
import { bpsBetween, formatRate, toFraction } from './format';
import { bestRow } from './selectors';

export const BACKGROUND_TASK = 'ar-rates-daily-refresh';

// Foreground presentation. (shouldShowAlert is the SDK 52 field.)
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
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

function findRate(core: CorePayload, productKey: string): { row: RateRow; fraction: number | null } | null {
  for (const section of SECTION_ORDER) {
    const row = (core.sections[section]?.rates ?? []).find((r) => r.product_key === productKey);
    if (row) return { row, fraction: toFraction(row.rate) };
  }
  return null;
}

/**
 * Pure diff: compare two payloads and produce user-facing change messages.
 * Exposed (and unit-tested) separately from the scheduling side-effect.
 */
export function computeChanges(
  oldCore: CorePayload | null,
  newCore: CorePayload,
  favorites: string[],
  thresholdBps: number,
): NotifyMessage[] {
  if (!oldCore) return [];
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

  // Watchlisted products.
  for (const key of favorites) {
    const before = findRate(oldCore, key);
    const after = findRate(newCore, key);
    if (!before || !after || before.fraction === null || after.fraction === null) continue;
    const bps = Math.abs(bpsBetween(after.fraction, before.fraction) ?? 0);
    if (bps < thresholdBps) continue;
    messages.push({
      title: `${after.row.provider} rate changed`,
      body: `${after.row.product_name}: ${formatRate(before.fraction)} → ${formatRate(after.fraction)}.`,
    });
  }

  return messages;
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
