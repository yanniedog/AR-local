import {
  alignPointsToTimeline,
  chartYDomain,
  historyDatesInWindow,
  normalizeTimelineDates,
  rbaChangesInWindow,
  rbaRateAsOf,
  rbaStepForDates,
  sanitizeRibbonPoint,
  sliceChartTimeline,
  sliceIndexFromPlotX,
} from '../src/data/bankHistoryTransform';
import type { RbaEntry } from '../src/types';

describe('bankHistoryTransform', () => {
  it('normalizes and dedupes timeline dates', () => {
    expect(normalizeTimelineDates(['2026-03-01', '2026-01-15', '2026-03-01', 'bad'])).toEqual([
      '2026-01-15',
      '2026-03-01',
    ]);
  });

  it('sanitizes ribbon points and clamps mean/median', () => {
    const point = sanitizeRibbonPoint('2026-02-01', { min: 0.08, max: 0.04, mean: 0.2, median: 0.01 });
    expect(point.min).toBe(0.04);
    expect(point.max).toBe(0.08);
    expect(point.mean).toBe(0.08);
    expect(point.median).toBe(0.04);
  });

  it('aligns sparse points to a sorted timeline', () => {
    const dates = ['2026-01-01', '2026-02-01', '2026-03-01'];
    const raw = [
      { date: '2026-03-01', min: 0.07, max: 0.09, mean: 0.08, median: 0.08 },
      { date: '2026-01-01', min: 0.05, max: 0.06, mean: 0.055, median: 0.055 },
    ];
    const aligned = alignPointsToTimeline(dates, raw);
    expect(aligned).toHaveLength(3);
    expect(aligned[0].min).toBe(0.05);
    expect(aligned[1].min).toBeNull();
    expect(aligned[2].max).toBe(0.09);
  });

  it('slices history windows from the anchor date', () => {
    const dates = [
      '2025-12-01',
      '2026-01-01',
      '2026-02-01',
      '2026-03-01',
      '2026-04-01',
      '2026-05-01',
    ];
    const points = dates.map((date, i) => ({
      date,
      min: 0.05 + i * 0.001,
      max: 0.07 + i * 0.001,
      mean: 0.06 + i * 0.001,
      median: 0.06 + i * 0.001,
    }));

    const d30 = sliceChartTimeline(dates, points, '30D');
    expect(d30.dates.length).toBeGreaterThan(0);
    expect(d30.dates[d30.dates.length - 1]).toBe('2026-05-01');

    const all = historyDatesInWindow(dates, 'All');
    expect(all).toEqual(dates);

    const y1 = historyDatesInWindow(dates, '1Y');
    expect(y1.length).toBe(dates.length);
  });

  it('maps plot X to nearest slice index', () => {
    expect(sliceIndexFromPlotX(0, 100, 5)).toBe(0);
    expect(sliceIndexFromPlotX(100, 100, 5)).toBe(4);
    expect(sliceIndexFromPlotX(50, 100, 5)).toBe(2);
    expect(sliceIndexFromPlotX(25, 100, 3)).toBe(1);
    expect(sliceIndexFromPlotX(10, 100, 1)).toBe(0);
  });

  it('builds RBA step values and change marks for mortgage overlay', () => {
    const rba: RbaEntry[] = [
      { date: '2026-01-01', rate: 4.0 },
      { date: '2026-03-01', rate: 4.25 },
      { date: '2026-05-01', rate: 4.5 },
    ];
    const dates = ['2026-02-15', '2026-03-01', '2026-04-15', '2026-05-01'];
    expect(rbaRateAsOf(rba, '2026-02-15')).toBe(4.0);
    expect(rbaRateAsOf(rba, '2026-05-01')).toBe(4.5);
    expect(rbaStepForDates(dates, rba)).toEqual([0.04, 0.0425, 0.0425, 0.045]);
    const marks = rbaChangesInWindow(dates, rba);
    expect(marks.map((m) => m.snap)).toEqual(['2026-03-01', '2026-05-01']);
    expect(marks[0].bp).toBe(25);
    expect(rbaChangesInWindow(['2026-06-01', '2026-06-15'], rba)).toHaveLength(1);
    expect(rbaChangesInWindow(['2026-06-01', '2026-06-15'], rba, false)).toEqual([]);
  });

  it('chartYDomain includes median points and extra (highlight) values', () => {
    const points = [{ date: '2026-01-01', min: null, max: null, mean: 0.06, median: 0.1, count: 1 }];
    const domain = chartYDomain(points, [], [0.02]);
    // Without median the top would track mean (~0.063); without the extra highlight
    // value the bottom would track mean (~0.057). Both must widen the domain.
    expect(domain.max).toBeGreaterThan(0.1); // median (0.10) considered
    expect(domain.min).toBeLessThan(0.03); // extra highlight value (0.02) considered
  });
});
