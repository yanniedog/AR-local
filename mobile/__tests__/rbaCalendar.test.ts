import {
  normalizeRbaCalendar,
  nextMeeting,
  rbaCountdown,
  currentCashRate,
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

  it('is null once the schedule is exhausted', () => {
    const after = Date.parse('2027-01-01T00:00:00Z');
    expect(nextMeeting(cal, after)).toBeNull();
    expect(rbaCountdown(cal, after)).toBeNull();
  });

  it('computes days and hours to the announcement', () => {
    const cd = rbaCountdown(cal, JUN21)!;
    expect(cd.meeting.date).toBe('2026-08-11');
    expect(cd.days).toBe(51);
    expect(cd.ms).toBeGreaterThan(0);
    expect(cd.hours).toBeGreaterThanOrEqual(0);
  });
});

describe('currentCashRate', () => {
  it('returns the most recent decision rate', () => {
    expect(currentCashRate(normalizeRbaCalendar(CAL))).toBe(4.35);
  });

  it('is null when there are no decisions', () => {
    expect(currentCashRate(null)).toBeNull();
  });
});
