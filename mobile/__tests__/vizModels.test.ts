import type { BankInsightsPayload } from '../src/data/bankInsights';
import {
  lenderRaceModel,
  marketActivityModel,
  rateHeatmapModel,
  spreadGapModel,
} from '../src/data/vizModels';
import type { BankHistoryPoint } from '../src/types';

function point(date: string, min: number, max: number, median: number): BankHistoryPoint {
  return { date, min, max, mean: median, median, count: 10 };
}

const insights: BankInsightsPayload = {
  schema_version: 1,
  run_date: '2026-06-03',
  run_dates: ['2026-06-01', '2026-06-02', '2026-06-03'],
  banks: {
    AlphaBank: {
      Mortgage: { median: [0.06, 0.0595, 0.057], best: [0.055, 0.0545, 0.052], count: [10, 10, 10] },
    },
    BetaBank: {
      Mortgage: { median: [0.062, null, 0.062], best: [0.053, null, 0.053], count: [5, null, 5] },
    },
    GammaBank: {
      Savings: { median: [0.045, 0.046, 0.047], best: [0.05, 0.051, 0.052], count: [3, 3, 3] },
    },
  },
  events: [
    { date: '2026-06-02', provider: 'AlphaBank', section: 'Mortgage', dir: 'cut', moved: 4, total: 10, avg_bps: -5 },
    { date: '2026-06-03', provider: 'AlphaBank', section: 'Mortgage', dir: 'cut', moved: 8, total: 10, avg_bps: -25 },
    { date: '2026-06-03', provider: 'BetaBank', section: 'Mortgage', dir: 'hike', moved: 2, total: 5, avg_bps: 10 },
    { date: '2026-06-03', provider: 'GammaBank', section: 'Savings', dir: 'hike', moved: 1, total: 3, avg_bps: 10 },
  ],
};

describe('rateHeatmapModel', () => {
  const dates = ['2026-06-01', '2026-06-02', '2026-06-03'];
  const points = [
    point('2026-06-01', 0.05, 0.07, 0.06),
    point('2026-06-02', 0.05, 0.07, 0.0595),
    point('2026-06-03', 0.05, 0.07, 0.057),
  ];

  test('computes day-over-day median deltas in bps against the previous observation', () => {
    const model = rateHeatmapModel(dates, points, 2);
    expect(model).not.toBeNull();
    const cells = model!.weeks.flat().filter((c) => c?.hasData);
    const byDate = Object.fromEntries(cells.map((c) => [c!.date, c!]));
    expect(byDate['2026-06-01'].deltaBps).toBeNull(); // first observation has no prior
    expect(byDate['2026-06-02'].deltaBps).toBeCloseTo(-5);
    expect(byDate['2026-06-03'].deltaBps).toBeCloseTo(-25);
    expect(byDate['2026-06-03'].intensity).toBe(1); // biggest move in window
  });

  test('skips deltas across missing days without zeroing the signal', () => {
    const sparse = [point('2026-06-01', 0.05, 0.07, 0.06), point('2026-06-05', 0.05, 0.07, 0.059)];
    const model = rateHeatmapModel(['2026-06-01', '2026-06-05'], sparse, 2);
    const cells = model!.weeks.flat().filter((c) => c?.hasData);
    expect(cells).toHaveLength(2);
    expect(cells[1]!.deltaBps).toBeCloseTo(-10); // vs 2026-06-01, not vs an empty day
  });

  test('returns null with fewer than two observations', () => {
    expect(rateHeatmapModel(['2026-06-01'], [point('2026-06-01', 0.05, 0.07, 0.06)])).toBeNull();
  });
});

describe('lenderRaceModel', () => {
  test('ranks lenders by best rate ascending for loans and follows the leaders', () => {
    const model = lenderRaceModel(insights, 'Mortgage', true, 'All', 6);
    expect(model).not.toBeNull();
    expect(model!.dates).toEqual(insights.run_dates);
    expect(model!.series.map((s) => s.provider)).toEqual(['AlphaBank', 'BetaBank']);
    // Day 1: Beta (0.053) beats Alpha (0.055); day 3: Alpha (0.052) leads.
    const alpha = model!.series[0];
    expect(alpha.ranks).toEqual([2, 2, 1]);
    expect(alpha.climbed).toBe(1);
    expect(alpha.current).toBeCloseTo(0.052);
  });

  test('carries the last known value forward through gaps', () => {
    const model = lenderRaceModel(insights, 'Mortgage', true, 'All', 6);
    const beta = model!.series.find((s) => s.provider === 'BetaBank')!;
    expect(beta.ranks[1]).toBe(1); // 0.053 carried into the null day still beats 0.0545
  });

  test('ranks descending for deposit sections', () => {
    const model = lenderRaceModel(insights, 'Savings', false, 'All', 6);
    expect(model).toBeNull(); // a single lender is not a race
  });
});

describe('spreadGapModel', () => {
  test('measures the median-to-best gap in bps for loans (best = min)', () => {
    const dates = ['2026-06-01', '2026-06-02'];
    const points = [point('2026-06-01', 0.05, 0.07, 0.06), point('2026-06-02', 0.05, 0.07, 0.062)];
    const model = spreadGapModel(dates, points, true);
    expect(model).not.toBeNull();
    expect(model!.points[0].gapBps).toBeCloseTo(100);
    expect(model!.currentBps).toBeCloseTo(120);
    expect(model!.maxBps).toBeCloseTo(120);
    expect(model!.widestDate).toBe('2026-06-02');
  });

  test('uses max as best for deposit sections', () => {
    const model = spreadGapModel(['2026-06-01'], [point('2026-06-01', 0.04, 0.055, 0.045)], false);
    expect(model!.points[0].gapBps).toBeCloseTo(100);
  });

  test('returns null when no point has both median and best', () => {
    const empty: BankHistoryPoint = { date: '2026-06-01', min: null, max: null, mean: null, median: null, count: 0 };
    expect(spreadGapModel(['2026-06-01'], [empty], true)).toBeNull();
  });
});

describe('marketActivityModel', () => {
  test('mirrors hikes and cuts per day with section filtering', () => {
    const model = marketActivityModel(insights, 'Mortgage', 'All');
    expect(model).not.toBeNull();
    expect(model!.totalMoves).toBe(3);
    const last = model!.days[2];
    expect(last.cutBps).toBeCloseTo(25);
    expect(last.hikeBps).toBeCloseTo(10);
    expect(last.cuts).toBe(1);
    expect(last.hikes).toBe(1);
    expect(model!.maxBps).toBeCloseTo(25);
  });

  test('null section aggregates all sections', () => {
    const model = marketActivityModel(insights, null, 'All');
    expect(model!.totalMoves).toBe(4);
    expect(model!.days[2].hikeBps).toBeCloseTo(20);
  });

  test('reports a quiet market when no events land in the window', () => {
    const model = marketActivityModel({ ...insights, events: [] }, 'Mortgage', 'All');
    expect(model!.totalMoves).toBe(0);
    expect(model!.maxBps).toBe(0);
  });
});
