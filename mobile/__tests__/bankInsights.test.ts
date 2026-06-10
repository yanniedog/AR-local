import {
  bankTrendChartModel,
  marketPulse,
  normalizeBankInsightsPayload,
  rbaPassThrough,
  recentBankEvents,
  topMovers,
  type BankInsightsPayload,
} from '../src/data/bankInsights';
import type { RbaEntry } from '../src/types';

const payload: BankInsightsPayload = {
  schema_version: 1,
  run_date: '2026-06-01',
  run_dates: ['2026-05-01', '2026-05-15', '2026-06-01'],
  banks: {
    AlphaBank: {
      Mortgage: {
        median: [0.06, 0.0595, 0.057],
        best: [0.055, 0.0545, 0.052],
        count: [10, 10, 10],
      },
    },
    BetaBank: {
      Mortgage: {
        median: [0.062, null, 0.062],
        best: [0.058, null, 0.058],
        count: [5, null, 5],
      },
    },
    GammaBank: {
      Savings: {
        median: [0.045, 0.046, 0.047],
        best: [0.05, 0.051, 0.052],
        count: [3, 3, 3],
      },
    },
  },
  events: [
    { date: '2026-05-15', provider: 'AlphaBank', section: 'Mortgage', dir: 'cut', moved: 4, total: 10, avg_bps: -5 },
    { date: '2026-06-01', provider: 'AlphaBank', section: 'Mortgage', dir: 'cut', moved: 8, total: 10, avg_bps: -25 },
    { date: '2026-06-01', provider: 'GammaBank', section: 'Savings', dir: 'hike', moved: 1, total: 3, avg_bps: 10 },
  ],
};

// RBA series is in PERCENT (dashboard parity); a 4.35 -> 4.10 step is a 25 bps cut.
const rba: RbaEntry[] = [
  { date: '2026-04-01', rate: 4.35 },
  { date: '2026-05-10', rate: 4.1 },
];

describe('normalizeBankInsightsPayload', () => {
  test('accepts a valid payload and keeps series aligned to run_dates', () => {
    const normalized = normalizeBankInsightsPayload(JSON.parse(JSON.stringify(payload)));
    expect(normalized).not.toBeNull();
    expect(normalized!.run_dates).toEqual(payload.run_dates);
    expect(normalized!.banks.BetaBank.Mortgage!.median).toEqual([0.062, null, 0.062]);
    expect(normalized!.events).toHaveLength(3);
  });

  test('pads short series and drops invalid events', () => {
    const normalized = normalizeBankInsightsPayload({
      schema_version: 1,
      run_date: '2026-06-01',
      run_dates: ['2026-05-01', '2026-06-01'],
      banks: { AlphaBank: { Mortgage: { median: [0.06], best: [0.055], count: [1] } } },
      events: [
        { date: '2026-06-01', provider: 'AlphaBank', section: 'NotASection', dir: 'cut', moved: 1, total: 1, avg_bps: -10 },
        { date: 'garbage', provider: 'AlphaBank', section: 'Mortgage', dir: 'cut', moved: 1, total: 1, avg_bps: -10 },
        { date: '2026-06-01', provider: 'AlphaBank', section: 'Mortgage', dir: 'sideways', moved: 1, total: 1, avg_bps: -10 },
      ],
    });
    expect(normalized!.banks.AlphaBank.Mortgage!.median).toEqual([0.06, null]);
    expect(normalized!.events).toEqual([]);
  });

  test('rejects payloads without usable bank series', () => {
    expect(normalizeBankInsightsPayload(null)).toBeNull();
    expect(normalizeBankInsightsPayload({ run_date: '2026-06-01', run_dates: [], banks: {} })).toBeNull();
    expect(
      normalizeBankInsightsPayload({
        run_date: '2026-06-01',
        run_dates: ['2026-06-01'],
        banks: { AlphaBank: { Mortgage: { median: [null], best: [null], count: [null] } } },
      }),
    ).toBeNull();
  });
});

describe('recentBankEvents', () => {
  test('sorts newest first, then provider', () => {
    const events = recentBankEvents(payload);
    expect(events.map((e) => `${e.date}:${e.provider}`)).toEqual([
      '2026-06-01:AlphaBank',
      '2026-06-01:GammaBank',
      '2026-05-15:AlphaBank',
    ]);
  });

  test('filters by section, provider, and limit', () => {
    expect(recentBankEvents(payload, { sections: ['Savings'] })).toHaveLength(1);
    expect(recentBankEvents(payload, { provider: 'AlphaBank' })).toHaveLength(2);
    expect(recentBankEvents(payload, { limit: 1 })[0].provider).toBe('AlphaBank');
    expect(recentBankEvents(null)).toEqual([]);
  });
});

describe('topMovers', () => {
  test('computes net median change over the window, cuts first', () => {
    const movers = topMovers(payload, 'Mortgage', 30);
    expect(movers[0]).toEqual({ provider: 'AlphaBank', netBps: -25, current: 0.057 });
    expect(movers[1]).toEqual({ provider: 'BetaBank', netBps: 0, current: 0.062 });
  });

  test('skips sections with no series', () => {
    expect(topMovers(payload, 'TD', 30)).toEqual([]);
    expect(topMovers(null, 'Mortgage', 30)).toEqual([]);
  });
});

describe('bankTrendChartModel', () => {
  test('band spans best to median with correct ordering for loans', () => {
    const model = bankTrendChartModel(payload, 'AlphaBank', 'Mortgage');
    expect(model!.dates).toEqual(payload.run_dates);
    expect(model!.points[0]).toMatchObject({ min: 0.055, max: 0.06, mean: 0.06 });
  });

  test('orders band correctly when best is above median (deposits)', () => {
    const model = bankTrendChartModel(payload, 'GammaBank', 'Savings');
    expect(model!.points[0]).toMatchObject({ min: 0.045, max: 0.05 });
  });

  test('drops all-null days but keeps the full timeline for window slicing', () => {
    const model = bankTrendChartModel(payload, 'BetaBank', 'Mortgage');
    expect(model!.dates).toEqual(['2026-05-01', '2026-06-01']);
    expect(model!.allDates).toEqual(payload.run_dates);
  });

  test('returns null for unknown providers', () => {
    expect(bankTrendChartModel(payload, 'NoSuchBank', 'Mortgage')).toBeNull();
  });
});

describe('rbaPassThrough', () => {
  test('scores best-rate movement since the latest in-window decision', () => {
    const model = rbaPassThrough(payload, rba);
    expect(model!.decision).toEqual({ date: '2026-05-10', bps: -25 });
    expect(model!.rows[0]).toEqual({ provider: 'AlphaBank', passedBps: -30, daysToFirstMove: 5 });
    expect(model!.rows[1]).toEqual({ provider: 'BetaBank', passedBps: 0, daysToFirstMove: null });
  });

  test('returns null when no decision falls inside the tracked window', () => {
    expect(rbaPassThrough(payload, [{ date: '2026-04-01', rate: 4.35 }])).toBeNull();
    expect(
      rbaPassThrough(payload, [
        { date: '2026-01-01', rate: 4.35 },
        { date: '2026-02-01', rate: 4.1 },
      ]),
    ).toBeNull();
  });
});

describe('marketPulse', () => {
  test('counts distinct movers, cuts, and hikes in the window', () => {
    const pulse = marketPulse(payload, 7);
    expect(pulse).toMatchObject({ banksMoved: 2, cuts: 1, hikes: 1 });
  });

  test('handles a quiet window', () => {
    const pulse = marketPulse({ ...payload, events: [] }, 7);
    expect(pulse).toMatchObject({ banksMoved: 0, cuts: 0, hikes: 0 });
  });
});
