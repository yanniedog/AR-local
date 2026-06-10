import core from '../assets/sample/core.json';
import {
  chartModelFromPrebuiltHistory,
  normalizeHistoryBanksPayload,
  type HistoryBanksPayload,
} from '../src/data/historyPayload';
import * as bankHistoryTransform from '../src/data/bankHistoryTransform';
import { selectBankHistoryChartModel } from '../src/data/historySelectors';
import { debugLog } from '../src/lib/debugLog';
import type { CorePayload } from '../src/types';

const sample = core as CorePayload;

describe('historyPayload', () => {
  const prebuilt: HistoryBanksPayload = {
    schema_version: 1,
    run_date: sample.run_date,
    run_dates: ['2026-04-01', '2026-05-01', sample.run_date],
    sections: {
      Mortgage: {
        points: [
          { date: '2026-04-01', min: 0.03, max: 0.08, mean: 0.05, median: 0.049, count: 900 },
          { date: '2026-05-01', min: 0.031, max: 0.081, mean: 0.051, median: 0.05, count: 910 },
          {
            date: sample.run_date,
            min: 0.032,
            max: 0.082,
            mean: 0.052,
            median: 0.051,
            count: 920,
          },
        ],
      },
    },
  };

  test('chartModelFromPrebuiltHistory returns sliced series without row aggregation', () => {
    const model = chartModelFromPrebuiltHistory(prebuilt, 'Mortgage', 'All');
    expect(model?.dates).toEqual(prebuilt.run_dates);
    expect(model?.points).toHaveLength(3);
  });

  test('selectBankHistoryChartModel uses prebuilt history when provided', () => {
    const model = selectBankHistoryChartModel({ core: sample, historyBanks: prebuilt }, 'Mortgage', 'All');
    expect(model?.dates.length).toBe(3);
  });

  test('falls back to single-day ribbon without prebuilt asset', () => {
    const model = selectBankHistoryChartModel({ core: sample }, 'Mortgage');
    expect(model?.dates).toEqual([sample.run_date]);
  });

  test('normalizeHistoryBanksPayload rejects corrupt points shape', () => {
    expect(
      normalizeHistoryBanksPayload({
        schema_version: 1,
        run_date: sample.run_date,
        run_dates: [],
        sections: { Mortgage: { points: 'not-an-array' } },
      }),
    ).toBeNull();
    expect(
      chartModelFromPrebuiltHistory(
        {
          schema_version: 1,
          run_date: sample.run_date,
          run_dates: [],
          sections: { Mortgage: { points: 'bad' as never } },
        },
        'Mortgage',
        'All',
      ),
    ).toBeNull();
  });

  test('normalizeHistoryBanksPayload accepts valid section points', () => {
    const normalized = normalizeHistoryBanksPayload(prebuilt);
    expect(normalized?.sections.Mortgage?.points).toHaveLength(3);
  });

  test('selectBankHistoryChartModel sanitizes corrupt ribbon fallback (no throw)', () => {
    const corrupt = JSON.parse(JSON.stringify(sample)) as CorePayload;
    corrupt.sections.Mortgage.ribbon = {
      range: { min: Number.NaN, max: 'not-a-rate' as unknown as number, mean: Infinity, median: null },
      counts: { rates: 1, products: 0, providers: 1 },
      providers: [],
    };
    const model = selectBankHistoryChartModel({ core: corrupt }, 'Mortgage');
    expect(model).toBeNull();
  });

  test('chartModelFromPrebuiltHistory logs and returns null on internal failure', () => {
    const errorSpy = jest.spyOn(debugLog, 'error').mockImplementation(() => {});
    jest.spyOn(bankHistoryTransform, 'sliceChartTimeline').mockImplementationOnce(() => {
      throw new Error('slice blew up');
    });

    const result = chartModelFromPrebuiltHistory(prebuilt, 'Mortgage', '30D');
    expect(result).toBeNull();
    expect(errorSpy).toHaveBeenCalledWith(
      'historyPayload',
      expect.stringContaining('chartModelFromPrebuiltHistory failed'),
    );

    errorSpy.mockRestore();
    jest.restoreAllMocks();
  });
});

