import {
  normalizeRbaCalendar,
  nextMeeting,
  rbaCountdown,
  currentCashRate,
  recentDecisions,
} from '../src/data/rbaCalendar';

const CAL = {
  timezone: 'Australia/Sydney',
  decisions: [
    { date: '2026-05-05', effective: '2026-05-06', rate: 4.35, delta_bps: 25, outcome: 'hike' },
    { date: '2026-06-16', effective: null, rate: 4.35, delta_bps: 0, outcome: 'hold' },
  ],
  schedule: [
    { date: '2026-08-11', announce_utc: '2026-08-11T04:30:00+00:00' },
    { date: '2026-09-29', announce_utc: '2026-09-29T04:30:00+00:00' },
  ],
};

const JUN21 = Date.parse('2026-06-21T00:00:00Z');

describe('normalizeRbaCalendar', () => {
  it('parses a well-formed calendar', () => {
    const cal = normalizeRbaCalendar(CAL);
    expect(cal).not.toBeNull();
    expect(cal!.schedule).toHaveLength(2);
    expect(cal!.decisions).toHaveLength(2);
    expect(cal!.timezone).toBe('Australia/Sydney');
  });

  it('drops malformed entries and sorts schedule ascending', () => {
    const cal = normalizeRbaCalendar({
      schedule: [
        { date: '2026-09-29', announce_utc: '2026-09-29T04:30:00+00:00' },
        { date: '2026-08-11', announce_utc: '2026-08-11T04:30:00+00:00' },
        { date: 'bad', announce_utc: 'not-a-date' },
        { date: '2026-10-01' }, // no announce_utc
      ],
      decisions: [{ date: '2026-05-05', rate: 4.35, delta_bps: 25, outcome: 'hike' }],
    });
    expect(cal!.schedule.map((m) => m.date)).toEqual(['2026-08-11', '2026-09-29']);
  });

  it('returns null for garbage or empty input', () => {
    expect(normalizeRbaCalendar(null)).toBeNull();
    expect(normalizeRbaCalendar({ schedule: [], decisions: [] })).toBeNull();
  });

  it('drops decisions with a malformed date or invalid outcome and rounds delta', () => {
    const cal = normalizeRbaCalendar({
      schedule: [{ date: '2026-08-11', announce_utc: '2026-08-11T04:30:00+00:00' }],
      decisions: [
        { date: '2026-05-05', effective: '2026-05-06', rate: 4.35, delta_bps: 24.7, outcome: 'hike' },
        { date: 'not-a-date', rate: 4.35, delta_bps: 0, outcome: 'hold' },
        { date: '2026-03-17', rate: 4.1, delta_bps: 25, outcome: 'nope' },
      ],
    });
    expect(cal!.decisions.map((d) => d.date)).toEqual(['2026-05-05']);
    expect(cal!.decisions[0].delta_bps).toBe(25);
  });
});

describe('nextMeeting / rbaCountdown', () => {
  const cal = normalizeRbaCalendar(CAL)!;

  it('finds the next future meeting', () => {
    expect(nextMeeting(cal, JUN21)!.date).toBe('2026-08-11');
  });

  it('rolls to the following meeting once the announcement passes', () => {
    const justAfter = Date.parse('2026-08-11T04:30:00.001Z');
    expect(nextMeeting(cal, justAfter)!.date).toBe('2026-09-29');
  });

  it('treats the exact announcement instant as no longer upcoming', () => {
    expect(nextMeeting(cal, Date.parse('2026-08-11T04:30:00+00:00'))!.date).toBe('2026-09-29');
  });

  it('returns null for a null or structurally empty schedule', () => {
    expect(nextMeeting(null)).toBeNull();
    expect(nextMeeting({ timezone: 'x', decisions: [], schedule: [] })).toBeNull();
    expect(rbaCountdown(null)).toBeNull();
  });

  it('is null once the schedule is exhausted', () => {
    const after = Date.parse('2027-01-01T00:00:00Z');
    expect(nextMeeting(cal, after)).toBeNull();
    expect(rbaCountdown(cal, after)).toBeNull();
  });

  it('computes days and hours to the announcement', () => {
    const cd = rbaCountdown(cal, JUN21)!;
    expect(cd.meeting.date).toBe('2026-08-11');
    expect(cd.days).toBe(51);
    expect(cd.calendarDays).toBe(51);
    expect(cd.ms).toBeGreaterThan(0);
    expect(cd.hours).toBeGreaterThanOrEqual(0);
  });

  it('calendarDays counts calendar days, not 24h blocks (fixes today vs tomorrow)', () => {
    // 2026-08-10T10:00Z is 2026-08-10 20:00 Sydney; the 2026-08-11 14:30 Sydney
    // meeting is ~18.5h away -> 24h-blocks = 0, but it is calendar 'tomorrow'.
    const cd = rbaCountdown(cal, Date.parse('2026-08-10T10:00:00Z'))!;
    expect(cd.days).toBe(0);
    expect(cd.calendarDays).toBe(1);
  });
});

describe('currentCashRate', () => {
  const TWO = normalizeRbaCalendar({
    schedule: [],
    decisions: [
      { date: '2026-03-17', effective: '2026-03-18', rate: 4.1, delta_bps: 25, outcome: 'hike' },
      { date: '2026-05-05', effective: '2026-05-06', rate: 4.35, delta_bps: 25, outcome: 'hike' },
    ],
  });

  it('respects effective dates (no jump to the new target on announcement day)', () => {
    expect(currentCashRate(TWO, Date.parse('2026-05-05T12:00:00Z'))).toBe(4.1); // pre-effective
    expect(currentCashRate(TWO, Date.parse('2026-05-06T12:00:00Z'))).toBe(4.35); // effective
  });

  it('uses the Sydney date for the as-of boundary, not UTC', () => {
    // 2026-05-05T20:00Z is already 2026-05-06 in Sydney (AEST +10), so the 05-05
    // hike (effective 05-06) is in effect — UTC would still read 4.1.
    expect(currentCashRate(TWO, Date.parse('2026-05-05T20:00:00Z'))).toBe(4.35);
  });

  it('is null before the first effective date and when there are no decisions', () => {
    expect(currentCashRate(TWO, Date.parse('2026-01-01T00:00:00Z'))).toBeNull();
    expect(currentCashRate(null)).toBeNull();
    expect(
      currentCashRate(
        normalizeRbaCalendar({
          timezone: 'Australia/Sydney',
          decisions: [],
          schedule: [{ date: '2026-08-11', announce_utc: '2026-08-11T04:30:00+00:00' }],
        }),
      ),
    ).toBeNull();
  });
});

describe('recentDecisions', () => {
  it('returns the most recent decisions, newest first', () => {
    const cal = normalizeRbaCalendar(CAL)!;
    expect(recentDecisions(cal, 1).map((d) => d.date)).toEqual(['2026-06-16']);
    expect(recentDecisions(cal, 5).map((d) => d.date)).toEqual(['2026-06-16', '2026-05-05']);
  });

  it('returns [] for a non-positive limit (slice(-0) would otherwise return all)', () => {
    const cal = normalizeRbaCalendar(CAL)!;
    expect(recentDecisions(cal, 0)).toEqual([]);
    expect(recentDecisions(cal, -2)).toEqual([]);
  });

  it('returns [] for a null or decision-less calendar', () => {
    expect(recentDecisions(null)).toEqual([]);
    expect(
      recentDecisions(
        normalizeRbaCalendar({
          timezone: 'Australia/Sydney',
          decisions: [],
          schedule: [{ date: '2026-08-11', announce_utc: '2026-08-11T04:30:00+00:00' }],
        }),
      ),
    ).toEqual([]);
  });
});
