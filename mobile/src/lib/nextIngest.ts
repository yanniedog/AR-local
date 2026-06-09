/**
 * Daily rates refresh schedule — mirrors ar_local_ingest_schedule.py and
 * deploy/pi/ar-local-daily.timer (01:00 Australia/Hobart).
 */

import type { PayloadSource } from '../types';

export const DAILY_INGEST_TZ_KEY = 'Australia/Hobart';
export const DAILY_INGEST_LOCAL_HOUR = 1;
export const DAILY_INGEST_SCHEDULE_LABEL = `${String(DAILY_INGEST_LOCAL_HOUR).padStart(2, '0')}:00 ${DAILY_INGEST_TZ_KEY} daily`;

export interface IngestCountdownSnapshot {
  remainingMs: number;
  nextDueMs: number;
  countdownLabel: string;
  nextDueLocalLabel: string;
  scheduleLabel: string;
}

interface HobartParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const HOBART_PARTS_OPTIONS: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
};

const PROBE_OPTIONS: Intl.DateTimeFormatOptions = {
  ...HOBART_PARTS_OPTIONS,
  second: '2-digit',
};

let hobartPartsFmt: Intl.DateTimeFormat | null = null;
let probeFmt: Intl.DateTimeFormat | null = null;

function getFormatters(): { hobartPartsFmt: Intl.DateTimeFormat; probeFmt: Intl.DateTimeFormat } {
  if (!hobartPartsFmt || !probeFmt) {
    try {
      hobartPartsFmt = new Intl.DateTimeFormat('en-US', { ...HOBART_PARTS_OPTIONS, timeZone: DAILY_INGEST_TZ_KEY });
      probeFmt = new Intl.DateTimeFormat('en-US', { ...PROBE_OPTIONS, timeZone: DAILY_INGEST_TZ_KEY });
    } catch {
      const fallbackTz = 'UTC';
      hobartPartsFmt = new Intl.DateTimeFormat('en-US', { ...HOBART_PARTS_OPTIONS, timeZone: fallbackTz });
      probeFmt = new Intl.DateTimeFormat('en-US', { ...PROBE_OPTIONS, timeZone: fallbackTz });
    }
  }
  return { hobartPartsFmt, probeFmt };
}

function hobartParts(ms: number): HobartParts {
  const { HOBART_PARTS_FMT } = getFormatters();
  const map: Record<string, string> = {};
  for (const part of HOBART_PARTS_FMT.formatToParts(new Date(ms))) {
    if (part.type !== 'literal') map[part.type] = part.value;
  }
  const year = Number(map.year);
  const month = Number(map.month);
  const day = Number(map.day);
  const hour = Number(map.hour);
  const minute = Number(map.minute);
  if (Number.isNaN(year) || Number.isNaN(month) || Number.isNaN(day) || Number.isNaN(hour) || Number.isNaN(minute)) {
    const d = new Date(ms);
    return {
      year: d.getUTCFullYear(),
      month: d.getUTCMonth() + 1,
      day: d.getUTCDate(),
      hour: d.getUTCHours(),
      minute: d.getUTCMinutes(),
    };
  }
  return { year, month, day, hour, minute };
}

function hobartLocalToUtcMs(year: number, month: number, day: number, hour: number, minute = 0): number {
  const target = Date.UTC(year, month - 1, day, hour, minute, 0);
  const { PROBE_FMT } = getFormatters();
  let utc = target;
  for (let i = 0; i < 4; i += 1) {
    const map: Record<string, number> = {};
    for (const part of PROBE_FMT.formatToParts(new Date(utc))) {
      if (part.type !== 'literal') map[part.type] = Number(part.value);
    }
    const actual = Date.UTC(map.year, map.month - 1, map.day, map.hour, map.minute, map.second ?? 0);
    if (Number.isNaN(actual)) {
      return target;
    }
    utc += target - actual;
  }
  return utc;
}

function addDays(year: number, month: number, day: number, delta: number): HobartParts {
  const utc = Date.UTC(year, month - 1, day + delta, 12, 0, 0);
  return hobartParts(utc);
}

export function latestDailyDueUtcMs(nowMs: number): number {
  const local = hobartParts(nowMs);
  let dueMs = hobartLocalToUtcMs(local.year, local.month, local.day, DAILY_INGEST_LOCAL_HOUR, 0);
  if (nowMs < dueMs) {
    const prev = addDays(local.year, local.month, local.day, -1);
    dueMs = hobartLocalToUtcMs(prev.year, prev.month, prev.day, DAILY_INGEST_LOCAL_HOUR, 0);
  }
  return dueMs;
}

export function nextDailyDueUtcMs(nowMs: number): number {
  const last = hobartParts(latestDailyDueUtcMs(nowMs));
  const next = addDays(last.year, last.month, last.day, 1);
  return hobartLocalToUtcMs(next.year, next.month, next.day, DAILY_INGEST_LOCAL_HOUR, 0);
}

export function formatCountdown(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const sec = String(seconds).padStart(2, '0');
  const min = String(minutes).padStart(2, '0');
  const hr = String(hours).padStart(2, '0');
  if (days > 0) return `${days}d ${hr}h ${min}m ${sec}s`;
  if (hours > 0) return `${hours}h ${min}m ${sec}s`;
  return `${minutes}m ${sec}s`;
}

export function formatNextDueLocal(nextDueMs: number): string {
  return new Date(nextDueMs).toLocaleString(undefined, {
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export function getNextIngestCountdown(nowMs = Date.now(), nextDueMs?: number): IngestCountdownSnapshot {
  const dueMs = nextDueMs ?? nextDailyDueUtcMs(nowMs);
  const remainingMs = Math.max(0, dueMs - nowMs);
  return {
    remainingMs,
    nextDueMs: dueMs,
    countdownLabel: formatCountdown(remainingMs),
    nextDueLocalLabel: formatNextDueLocal(dueMs),
    scheduleLabel: DAILY_INGEST_SCHEDULE_LABEL,
  };
}

export function dataSourceLabel(source: PayloadSource): string {
  switch (source) {
    case 'remote':
      return 'Live';
    case 'cache':
      return 'Cached';
    case 'sample':
      return 'Sample';
  }
}
