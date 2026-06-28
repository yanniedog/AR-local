// RBA decision calendar consumed from the daily `rba-calendar` payload asset
// (built by rba_decisions.calendar_payload on the Pi). The asset carries the
// recorded decisions + the forward meeting schedule with NO wall-clock fields, so
// the live countdown is computed here on-device from `schedule`.

export type RbaOutcome = 'hike' | 'cut' | 'hold';

const OUTCOMES: readonly RbaOutcome[] = ['hike', 'cut', 'hold'];

export interface RbaScheduledMeeting {
  /** Announcement date (meeting day 2), YYYY-MM-DD. */
  date: string;
  /** ISO instant of the 14:30 Sydney announcement. */
  announce_utc: string;
}

export interface RbaDecisionEntry {
  /** Announcement date, YYYY-MM-DD. */
  date: string;
  /** Effective date (null for a held meeting). */
  effective: string | null;
  /** Resulting cash-rate target, percent. */
  rate: number;
  /** Change announced, basis points (0 = hold). */
  delta_bps: number;
  outcome: RbaOutcome;
}

export interface RbaCalendar {
  timezone: string;
  decisions: RbaDecisionEntry[];
  schedule: RbaScheduledMeeting[];
}

const YMD_RE = /^\d{4}-\d{2}-\d{2}$/;

function ymd(value: unknown): string {
  if (typeof value !== 'string') return '';
  const s = value.slice(0, 10);
  return YMD_RE.test(s) ? s : '';
}

function ymdToUtcMs(value: string): number {
  const [y, m, d] = value.split('-').map((part) => Number.parseInt(part, 10));
  return Date.UTC(y, m - 1, d);
}

/** Whole calendar days from `from` to `to` (both YYYY-MM-DD). */
function ymdDiffDays(from: string, to: string): number {
  return Math.round((ymdToUtcMs(to) - ymdToUtcMs(from)) / 86_400_000);
}

function finiteNumber(value: unknown): number | null {
  if (value == null || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Drop corrupt rba-calendar JSON before it reaches the countdown/UI. */
export function normalizeRbaCalendar(raw: unknown): RbaCalendar | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;

  const schedule: RbaScheduledMeeting[] = [];
  if (Array.isArray(obj.schedule)) {
    for (const item of obj.schedule) {
      if (!item || typeof item !== 'object') continue;
      const m = item as Record<string, unknown>;
      const date = ymd(m.date);
      const announce = typeof m.announce_utc === 'string' ? m.announce_utc : '';
      if (!date || !Number.isFinite(Date.parse(announce))) continue;
      schedule.push({ date, announce_utc: announce });
    }
  }
  schedule.sort((a, b) => a.announce_utc.localeCompare(b.announce_utc));

  const decisions: RbaDecisionEntry[] = [];
  if (Array.isArray(obj.decisions)) {
    for (const item of obj.decisions) {
      if (!item || typeof item !== 'object') continue;
      const d = item as Record<string, unknown>;
      const date = ymd(d.date);
      const rate = finiteNumber(d.rate);
      const delta = finiteNumber(d.delta_bps);
      const outcome = typeof d.outcome === 'string' ? d.outcome : '';
      if (!date || rate == null || delta == null || !(OUTCOMES as readonly string[]).includes(outcome)) continue;
      const effective = ymd(d.effective);
      decisions.push({
        date,
        effective: effective || null,
        rate,
        delta_bps: Math.round(delta),
        outcome: outcome as RbaOutcome,
      });
    }
  }
  decisions.sort((a, b) => a.date.localeCompare(b.date));

  if (!schedule.length && !decisions.length) return null;
  return {
    timezone: typeof obj.timezone === 'string' ? obj.timezone : 'Australia/Sydney',
    decisions,
    schedule,
  };
}

/** The next scheduled meeting whose announcement is still in the future. */
export function nextMeeting(
  calendar: RbaCalendar | null | undefined,
  now: number = Date.now(),
): RbaScheduledMeeting | null {
  if (!calendar?.schedule?.length) return null;
  for (const meeting of calendar.schedule) {
    const ts = Date.parse(meeting.announce_utc);
    if (Number.isFinite(ts) && ts > now) return meeting;
  }
  return null;
}

export interface RbaCountdown {
  meeting: RbaScheduledMeeting;
  /** Milliseconds until the announcement. */
  ms: number;
  /** 24-hour blocks remaining (duration). */
  days: number;
  hours: number;
  /** Whole Sydney calendar days from today to the announcement date — use this for
   * "today / tomorrow / in N days" labels (a sub-24h gap across midnight is 1 day). */
  calendarDays: number;
}

/** Live countdown to the next decision, computed on-device. Null once the
 * schedule is exhausted (the asset needs the next year's dates appended). */
export function rbaCountdown(
  calendar: RbaCalendar | null | undefined,
  now: number = Date.now(),
): RbaCountdown | null {
  const meeting = nextMeeting(calendar, now);
  if (!meeting) return null;
  const ms = Date.parse(meeting.announce_utc) - now;
  return {
    meeting,
    ms,
    days: Math.floor(ms / 86_400_000),
    hours: Math.floor((ms % 86_400_000) / 3_600_000),
    calendarDays: ymdDiffDays(sydneyYmd(now), meeting.date),
  };
}

function firstSundayUtc(year: number, monthIndex: number): number {
  const dow = new Date(Date.UTC(year, monthIndex, 1)).getUTCDay(); // 0 = Sunday
  return Date.UTC(year, monthIndex, 1 + ((7 - dow) % 7));
}

/** Sydney calendar date (YYYY-MM-DD) for a UTC instant — the RBA's frame of
 * reference. AEDT (+11) from the first Sunday in October to the first Sunday in
 * April, else AEST (+10); computed without a tzdata dependency, mirroring the Pi. */
function sydneyYmd(ms: number): string {
  const year = new Date(ms).getUTCFullYear();
  const dstStart = firstSundayUtc(year, 9); // October
  const dstEnd = firstSundayUtc(year, 3); // April
  const offsetH = ms >= dstStart || ms < dstEnd ? 11 : 10;
  return new Date(ms + offsetH * 3_600_000).toISOString().slice(0, 10);
}

/** The prevailing cash-rate target (percent) as of `now`, by EFFECTIVE date in the
 * RBA's Sydney frame — so on an announcement day it does not jump to the new target
 * before it takes effect (a held meeting takes effect on its announcement date). */
export function currentCashRate(
  calendar: RbaCalendar | null | undefined,
  now: number = Date.now(),
): number | null {
  const decisions = calendar?.decisions;
  if (!decisions?.length) return null;
  const asof = sydneyYmd(now);
  let rate: number | null = null;
  for (const decision of decisions) {
    const effective = decision.effective ?? decision.date;
    if (effective <= asof) rate = decision.rate;
  }
  return rate;
}

/** The most recent recorded decisions, newest first — for the countdown card's
 * tiered "recent decisions" disclosure. */
export function recentDecisions(
  calendar: RbaCalendar | null | undefined,
  limit = 4,
): RbaDecisionEntry[] {
  const decisions = calendar?.decisions;
  if (!decisions?.length || limit <= 0) return []; // slice(-0) === slice(0) returns all
  return decisions.slice(-limit).reverse();
}

const RBA_MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** 'YYYY-MM-DD' -> 'D Mon' (e.g. '2026-08-11' -> '11 Aug'). */
export function formatRbaDate(ymd: string): string {
  const [y, m, d] = ymd.split('-').map((part) => Number.parseInt(part, 10));
  if (!y || !m || !d || m < 1 || m > 12) return ymd;
  return `${d} ${RBA_MONTHS[m - 1]}`;
}

/** One-line decision summary: 'Held · 4.35%' or '+25 bps · 4.35%'. */
export function decisionLine(decision: RbaDecisionEntry): string {
  if (decision.outcome === 'hold') return `Held · ${decision.rate.toFixed(2)}%`;
  const sign = decision.outcome === 'hike' ? '+' : '−';
  return `${sign}${Math.abs(decision.delta_bps)} bps · ${decision.rate.toFixed(2)}%`;
}

export interface RbaTrendModel {
  /** Current cash-rate target (percent) — the most recent recorded decision. */
  rate: number | null;
  direction: 'tightening' | 'easing' | 'steady' | 'unknown';
  hikes: number;
  cuts: number;
  holds: number;
  /** Earliest decision date in the lookback window. */
  sinceDate: string | null;
  /** Plain-English read of the recent rate path (not a forecast). */
  summary: string;
}

/** A rules-based read of the RBA's recent rate PATH (its decision history) — the
 * macro "Why rates move" gauge. Not driver-based (inflation/jobs) yet. */
export function rbaTrend(
  calendar: RbaCalendar | null | undefined,
  lookback = 8,
): RbaTrendModel {
  const all = calendar?.decisions ?? [];
  if (!all.length) {
    return { rate: null, direction: 'unknown', hikes: 0, cuts: 0, holds: 0, sinceDate: null, summary: '' };
  }
  const window = lookback > 0 ? all.slice(-lookback) : all.slice();
  let hikes = 0;
  let cuts = 0;
  let holds = 0;
  for (const decision of window) {
    if (decision.outcome === 'hike') hikes += 1;
    else if (decision.outcome === 'cut') cuts += 1;
    else holds += 1;
  }
  const rate = all[all.length - 1].rate;
  const direction: RbaTrendModel['direction'] =
    hikes > cuts ? 'tightening' : cuts > hikes ? 'easing' : 'steady';
  const n = window.length;
  const hikeWord = `${hikes} hike${hikes === 1 ? '' : 's'}`;
  const cutWord = `${cuts} cut${cuts === 1 ? '' : 's'}`;
  let summary: string;
  if (direction === 'tightening') {
    summary = `Tightening — ${hikeWord} (and ${cutWord}) across the last ${n} meetings.`;
  } else if (direction === 'easing') {
    summary = `Easing — ${cutWord} (and ${hikeWord}) across the last ${n} meetings.`;
  } else if (hikes === 0 && cuts === 0) {
    summary = `On hold — no change across the last ${n} meetings.`;
  } else {
    summary = `Steady — ${hikeWord} and ${cutWord} net out across the last ${n} meetings.`;
  }
  return { rate, direction, hikes, cuts, holds, sinceDate: window[0].date, summary };
}
