import * as BackgroundFetch from 'expo-background-fetch';
import * as Notifications from 'expo-notifications';
import type { Href } from 'expo-router';

import { SECTIONS, SECTION_ORDER } from '../constants';
import { debugLog } from '../lib/debugLog';
import type { CorePayload, ProductDetail, RateRow, SectionKey } from '../types';
import { bpsBetween, formatRate, toFraction } from './format';
import { bestRow } from './selectors';
import {
  computeSubscriptionChanges,
  largestRateChange,
  rowsForSearchSubscription,
  type Subscription,
} from './subscriptions';

export const BACKGROUND_TASK = 'ar-rates-daily-refresh';
export const DEEP_LINK_SCHEME = 'arrates';

// Foreground presentation. (SDK 53+ replaced shouldShowAlert with shouldShowBanner/List.)
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

export interface NotifySearchRoute {
  section: SectionKey;
  path?: string[];
  hierarchyScoped?: boolean;
  query?: string;
  sort?: string;
  scope?: string;
}

export interface NotifyMessage {
  title: string;
  body: string;
  productKey?: string;
  rateIndex?: number | null;
  search?: NotifySearchRoute;
}

export interface NotificationRoutePayload {
  productKey?: string;
  rateIndex?: string;
  url?: string;
  section?: string;
  path?: string;
  query?: string;
  scope?: string;
  sort?: string;
}

export function productDeepLink(productKey: string, rateIndex?: number | null): string {
  const path = `product/${encodeURIComponent(productKey)}`;
  if (rateIndex != null) return `${DEEP_LINK_SCHEME}://${path}?ri=${rateIndex}`;
  return `${DEEP_LINK_SCHEME}://${path}`;
}

export function searchDeepLink(route: NotifySearchRoute): string {
  const params = new URLSearchParams();
  params.set('section', route.section);
  if (route.path?.length) params.set('path', route.path.join('.'));
  if (route.hierarchyScoped) params.set('scope', 'hierarchy');
  else if (route.scope) params.set('scope', route.scope);
  if (route.query) params.set('query', route.query);
  if (route.sort) params.set('sort', route.sort);
  return `${DEEP_LINK_SCHEME}://search?${params.toString()}`;
}

export function notificationDataFromMessage(msg: NotifyMessage): NotificationRoutePayload {
  const data: NotificationRoutePayload = {};
  if (msg.productKey) {
    data.productKey = msg.productKey;
    if (msg.rateIndex != null) data.rateIndex = String(msg.rateIndex);
    data.url = productDeepLink(msg.productKey, msg.rateIndex);
    return data;
  }
  if (msg.search) {
    data.section = msg.search.section;
    if (msg.search.path?.length) data.path = msg.search.path.join('.');
    if (msg.search.query) data.query = msg.search.query;
    if (msg.search.sort) data.sort = msg.search.sort;
    if (msg.search.hierarchyScoped) data.scope = 'hierarchy';
    else if (msg.search.scope) data.scope = msg.search.scope;
    data.url = searchDeepLink(msg.search);
  }
  return data;
}

export function hrefFromNotificationData(
  raw: Record<string, unknown> | null | undefined,
): Href | null {
  if (!raw) return null;

  const url = typeof raw.url === 'string' ? raw.url : null;
  if (url?.startsWith(`${DEEP_LINK_SCHEME}://`)) {
    const pathAndQuery = url.slice(`${DEEP_LINK_SCHEME}://`.length);
    return `/${pathAndQuery}` as Href;
  }

  const productKey = typeof raw.productKey === 'string' ? raw.productKey : null;
  if (productKey) {
    const riRaw = raw.rateIndex;
    const ri = riRaw != null && riRaw !== '' ? Number(riRaw) : undefined;
    return {
      pathname: '/product/[key]',
      params: {
        key: productKey,
        ...(ri != null && !Number.isNaN(ri) ? { ri: String(ri) } : {}),
      },
    } as Href;
  }

  const section = typeof raw.section === 'string' ? raw.section : null;
  if (section) {
    const params: Record<string, string> = { section };
    if (typeof raw.path === 'string' && raw.path) params.path = raw.path;
    if (typeof raw.query === 'string' && raw.query) params.query = raw.query;
    if (typeof raw.sort === 'string' && raw.sort) params.sort = raw.sort;
    if (typeof raw.scope === 'string' && raw.scope) params.scope = raw.scope;
    return { pathname: '/search', params } as Href;
  }

  return null;
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

function productRatesByIndex(
  core: CorePayload,
  productKey: string,
  rateIndex: number | null,
): Map<number, { row: RateRow; fraction: number | null }> {
  const out = new Map<number, { row: RateRow; fraction: number | null }>();
  for (const section of Object.keys(core.sections) as SectionKey[]) {
    for (const row of core.sections[section]?.rates ?? []) {
      if (row.product_key !== productKey) continue;
      if (rateIndex != null && row.rate_index !== rateIndex) continue;
      out.set(row.rate_index ?? out.size, { row, fraction: toFraction(row.rate) });
    }
  }
  return out;
}

function ratesMap(rows: RateRow[]): Map<string, { row: RateRow; fraction: number | null }> {
  const out = new Map<string, { row: RateRow; fraction: number | null }>();
  for (const row of rows) {
    out.set(`${row.product_key}#${row.rate_index ?? 0}`, { row, fraction: toFraction(row.rate) });
  }
  return out;
}

function subscriptionWouldNotify(
  sub: Subscription,
  oldCore: CorePayload,
  newCore: CorePayload,
  thresholdBps: number,
  oldDetailsProducts?: Record<string, ProductDetail> | null,
  newDetailsProducts?: Record<string, ProductDetail> | null,
): boolean {
  if (sub.kind === 'product') {
    return (
      largestRateChange(
        productRatesByIndex(oldCore, sub.productKey, sub.rateIndex),
        productRatesByIndex(newCore, sub.productKey, sub.rateIndex),
        thresholdBps,
      ) != null
    );
  }
  const oldDetails = oldDetailsProducts;
  const newDetails = newDetailsProducts ?? oldDetailsProducts;
  return (
    largestRateChange(
      ratesMap(rowsForSearchSubscription(oldCore, sub, oldDetails)),
      ratesMap(rowsForSearchSubscription(newCore, sub, newDetails)),
      thresholdBps,
    ) != null
  );
}

function enrichSubscriptionRouting(
  raw: Array<{ title: string; body: string }>,
  subscriptions: Subscription[],
  oldCore: CorePayload,
  newCore: CorePayload,
  thresholdBps: number,
  oldDetailsProducts?: Record<string, ProductDetail> | null,
  newDetailsProducts?: Record<string, ProductDetail> | null,
): NotifyMessage[] {
  const enriched: NotifyMessage[] = [];
  let rawIdx = 0;

  for (const sub of subscriptions) {
    if (
      !subscriptionWouldNotify(
        sub,
        oldCore,
        newCore,
        thresholdBps,
        oldDetailsProducts,
        newDetailsProducts,
      )
    ) {
      continue;
    }
    if (rawIdx >= raw.length) break;
    const base = raw[rawIdx++];
    if (sub.kind === 'product') {
      enriched.push({
        ...base,
        productKey: sub.productKey,
        rateIndex: sub.rateIndex,
      });
      continue;
    }
    enriched.push({
      ...base,
      search: {
        section: sub.section,
        path: sub.path,
        hierarchyScoped: sub.hierarchyScoped,
        query: sub.query,
      },
    });
  }

  while (rawIdx < raw.length) enriched.push(raw[rawIdx++]);
  return enriched;
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
      search: { section },
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
        productKey: key,
        rateIndex: biggest.row.rate_index ?? null,
      });
    }
  }

  const combined = [...subscriptionMessages, ...messages];
  const enriched = enrichSubscriptionRouting(
    combined,
    subscriptions,
    oldCore,
    newCore,
    thresholdBps,
    oldDetailsProducts,
    newDetailsProducts,
  );
  return dedupeNotifyMessages(enriched);
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
  debugLog.debug('notify', `scheduling ${messages.length} notification(s)`);
  if (!(await ensurePermissions())) {
    debugLog.warn('notify', 'permissions denied — skipped');
    return;
  }
  // Collapse a flurry into at most a few notifications.
  for (const msg of messages.slice(0, 3)) {
    const data = notificationDataFromMessage(msg);
    await Notifications.scheduleNotificationAsync({
      content: { title: msg.title, body: msg.body, data: data as Record<string, unknown> },
      trigger: null, // immediate
    });
  }
}

export function routeFromNotificationResponse(
  response: Notifications.NotificationResponse | null | undefined,
): Href | null {
  const data = response?.notification?.request?.content?.data as Record<string, unknown> | undefined;
  return hrefFromNotificationData(data);
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
    debugLog.info('notify', 'background refresh registered');
  } catch (err) {
    debugLog.warn('notify', `background register failed: ${String((err as Error)?.message ?? err)}`);
    // Background fetch may be unavailable (e.g. web / simulator) — non-fatal.
  }
}

export async function unregisterBackgroundRefresh(): Promise<void> {
  try {
    await BackgroundFetch.unregisterTaskAsync(BACKGROUND_TASK);
    debugLog.info('notify', 'background refresh unregistered');
  } catch (err) {
    debugLog.debug('notify', `background unregister failed: ${String((err as Error)?.message ?? err)}`);
    // ignore
  }
}
