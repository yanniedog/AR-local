import {
  DAILY_INGEST_SCHEDULE_LABEL,
  formatCountdown,
  getNextIngestCountdown,
  latestDailyDueUtcMs,
  nextDailyDueUtcMs,
} from '../src/lib/nextIngest';

describe('nextIngest', () => {
  test('schedule label matches Pi ingest timer', () => {
    expect(DAILY_INGEST_SCHEDULE_LABEL).toBe('01:00 Australia/Hobart daily');
  });

  test('nextDailyDueUtcMs matches ar_local_ingest_schedule.py vectors', () => {
    const cases: Array<{ now: string; nextIso: string; remainingSec: number }> = [
      { now: '2026-06-09T14:00:00Z', nextIso: '2026-06-09T15:00:00.000Z', remainingSec: 3600 },
      { now: '2026-06-09T15:30:00Z', nextIso: '2026-06-10T15:00:00.000Z', remainingSec: 84600 },
      { now: '2026-06-10T00:30:00Z', nextIso: '2026-06-10T15:00:00.000Z', remainingSec: 52200 },
      { now: '2026-06-10T15:00:00Z', nextIso: '2026-06-11T15:00:00.000Z', remainingSec: 86400 },
    ];
    for (const { now, nextIso, remainingSec } of cases) {
      const nowMs = Date.parse(now);
      const nextMs = nextDailyDueUtcMs(nowMs);
      expect(new Date(nextMs).toISOString()).toBe(nextIso);
      expect(nextMs - nowMs).toBe(remainingSec * 1000);
    }
  });

  test('latestDailyDueUtcMs is the prior slot when before today due', () => {
    const nowMs = Date.parse('2026-06-10T00:30:00Z');
    expect(new Date(latestDailyDueUtcMs(nowMs)).toISOString()).toBe('2026-06-09T15:00:00.000Z');
  });

  test('formatCountdown renders compact segments', () => {
    expect(formatCountdown(0)).toBe('0m 00s');
    expect(formatCountdown(65_000)).toBe('1m 05s');
    expect(formatCountdown(3_661_000)).toBe('1h 01m 01s');
    expect(formatCountdown(90_061_000)).toBe('1d 01h 01m 01s');
  });

  test('getNextIngestCountdown bundles labels', () => {
    const snap = getNextIngestCountdown(Date.parse('2026-06-09T14:00:00Z'));
    expect(snap.remainingMs).toBe(3_600_000);
    expect(snap.countdownLabel).toBe('1h 00m 00s');
    expect(snap.scheduleLabel).toBe(DAILY_INGEST_SCHEDULE_LABEL);
    expect(snap.nextDueLocalLabel.length).toBeGreaterThan(0);
  });

  test('getNextIngestCountdown reuses cached nextDueMs', () => {
    const nowMs = Date.parse('2026-06-09T14:30:00Z');
    const dueMs = Date.parse('2026-06-09T15:00:00.000Z');
    const snap = getNextIngestCountdown(nowMs, dueMs);
    expect(snap.nextDueMs).toBe(dueMs);
    expect(snap.remainingMs).toBe(1_800_000);
    expect(snap.countdownLabel).toBe('30m 00s');
  });
});
