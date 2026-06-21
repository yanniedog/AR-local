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

function ymd(value: unknown): string {
  return typeof value === 'string' ? value.slice(0, 10) : '';
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
    if (Date.parse(meeting.announce_utc) > now) return meeting;
  }
  return null;
}

export interface RbaCountdown {
  meeting: RbaScheduledMeeting;
  /** Milliseconds until the announcement. */
  ms: number;
  days: number;
  hours: number;
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
  };
}

/** The prevailing cash-rate target (percent) — the most recent recorded decision. */
export function currentCashRate(calendar: RbaCalendar | null | undefined): number | null {
  const decisions = calendar?.decisions;
  if (!decisions?.length) return null;
  return decisions[decisions.length - 1].rate;
}
