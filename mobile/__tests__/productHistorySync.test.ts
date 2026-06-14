import { syncProductHistoryFromDailyPayloads, type ProductHistoryPayload } from '../src/data/productHistory';
import type { CorePayload, RateRow, SectionKey } from '../src/types';
import { downloadDatedCore, fetchDatesIndexJson, historyDatesUpTo } from '../src/data/historyDaily';

jest.mock('../src/data/historyDaily', () => ({
  downloadDatedCore: jest.fn(),
  fetchDatesIndexJson: jest.fn(),
  historyDatesUpTo: jest.fn(),
}));

const mockedDownload = jest.mocked(downloadDatedCore);
const mockedFetchIndex = jest.mocked(fetchDatesIndexJson);
const mockedHistoryDates = jest.mocked(historyDatesUpTo);

const EMPTY_RIBBON = {
  counts: { rates: 0, products: 0, providers: 0 },
  range: { min: null, max: null, mean: null, median: null },
  providers: [],
};

function rateRow(productKey: string, rate: string): RateRow {
  return { provider: 'Bank', product_key: productKey, product_name: productKey, rate };
}

function core(runDate: string, rowsBySection: Partial<Record<SectionKey, RateRow[]>>): CorePayload {
  return {
    schema_version: 1,
    run_date: runDate,
    sections: {
      Mortgage: { rates: rowsBySection.Mortgage ?? [], ribbon: EMPTY_RIBBON },
      Savings: { rates: rowsBySection.Savings ?? [], ribbon: EMPTY_RIBBON },
      TD: { rates: rowsBySection.TD ?? [], ribbon: EMPTY_RIBBON },
    },
    brands: {},
    rba: [],
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockedFetchIndex.mockResolvedValue({} as never);
});

test('always includes the current core date and records its revision', async () => {
  mockedHistoryDates.mockReturnValue(['2026-06-10']);

  const result = await syncProductHistoryFromDailyPayloads({
    targetRunDate: '2026-06-11',
    currentCore: core('2026-06-11', { Mortgage: [rateRow('P|1', '0.055')] }),
    coreSha: 'sha-new',
  });

  expect(result.run_dates).toEqual(['2026-06-11']);
  expect(result.products['P|1']).toEqual([0.055]);
  expect(result.core_sha).toBe('sha-new');
});

test('does not cache a failed date and retries it on the next sync', async () => {
  mockedHistoryDates.mockReturnValue(['2026-06-10', '2026-06-11']);
  mockedDownload.mockRejectedValueOnce(new Error('temporary'));
  const current = core('2026-06-11', { Mortgage: [rateRow('P|1', '0.055')] });

  const first = await syncProductHistoryFromDailyPayloads({
    targetRunDate: '2026-06-11',
    currentCore: current,
  });
  expect(first.run_dates).toEqual(['2026-06-11']);

  mockedDownload.mockResolvedValueOnce(core('2026-06-10', { Mortgage: [rateRow('P|1', '0.06')] }));
  const second = await syncProductHistoryFromDailyPayloads({
    targetRunDate: '2026-06-11',
    currentCore: current,
    existing: first,
  });
  expect(second.run_dates).toEqual(['2026-06-10', '2026-06-11']);
  expect(second.products['P|1']).toEqual([0.06, 0.055]);
  expect(mockedDownload).toHaveBeenCalledTimes(2);
});

test('refetches prior dates when the current catalog changes', async () => {
  mockedHistoryDates.mockReturnValue(['2026-06-10', '2026-06-11']);
  const existing: ProductHistoryPayload = {
    schema_version: 2,
    run_date: '2026-06-10',
    run_dates: ['2026-06-10'],
    products: { 'P|1': [0.06] },
  };
  mockedDownload.mockResolvedValueOnce(
    core('2026-06-10', { Mortgage: [rateRow('P|1', '0.06'), rateRow('Q|2', '0.07')] }),
  );

  const result = await syncProductHistoryFromDailyPayloads({
    targetRunDate: '2026-06-11',
    currentCore: core('2026-06-11', { Mortgage: [rateRow('P|1', '0.055'), rateRow('Q|2', '0.065')] }),
    existing,
  });

  expect(mockedDownload).toHaveBeenCalledWith('2026-06-10');
  expect(result.products['Q|2']).toEqual([0.07, 0.065]);
});
