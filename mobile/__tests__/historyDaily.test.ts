import core from '../assets/sample/core.json';
import {
  dailyHistorySha,
  historyBanksCoversDates,
  historyDatesUpTo,
  mergeHistoryFromCores,
  parseDatesIndex,
} from '../src/data/historyDaily';
import type { CorePayload } from '../src/types';

const sample = core as CorePayload;

describe('historyDaily', () => {
  const index = parseDatesIndex({
    schema_version: 1,
    dates: ['2026-05-13', '2026-05-19', '2026-06-10'],
    count: 3,
    min_date: '2026-05-13',
    latest_date: '2026-06-10',
  })!;

  it('parseDatesIndex normalizes and sorts dates', () => {
    const parsed = parseDatesIndex({
      dates: ['2026-06-10', '2026-05-13', '2026-05-19'],
      count: 3,
      min_date: '2026-05-13',
    });
    expect(parsed?.dates).toEqual(['2026-05-13', '2026-05-19', '2026-06-10']);
  });

  it('historyDatesUpTo caps at target run_date', () => {
    expect(historyDatesUpTo(index, '2026-05-19')).toEqual(['2026-05-13', '2026-05-19']);
  });

  it('mergeHistoryFromCores builds multi-day section ribbon points', () => {
    const older = JSON.parse(JSON.stringify(sample)) as CorePayload;
    older.run_date = '2026-05-13';
    const latest = JSON.parse(JSON.stringify(sample)) as CorePayload;
    latest.run_date = '2026-06-10';
    const cores = new Map<string, CorePayload>([
      ['2026-05-13', older],
      ['2026-06-10', latest],
    ]);
    const built = mergeHistoryFromCores(null, cores, ['2026-05-13', '2026-06-10'], '2026-06-10');
    expect(built?.run_dates).toEqual(['2026-05-13', '2026-06-10']);
    expect(built?.sections.Mortgage?.points).toHaveLength(2);
    expect(built?.sections.Mortgage?.points[0].date).toBe('2026-05-13');
  });

  it('historyBanksCoversDates checks full timeline coverage', () => {
    const payload = {
      schema_version: 1,
      run_date: '2026-06-10',
      run_dates: ['2026-05-13', '2026-06-10'],
      sections: { Mortgage: { points: [] } },
    };
    expect(historyBanksCoversDates(payload, ['2026-05-13', '2026-06-10'])).toBe(true);
    expect(historyBanksCoversDates(payload, ['2026-05-13', '2026-05-19', '2026-06-10'])).toBe(false);
  });

  it('dailyHistorySha is stable for a date list', () => {
    expect(dailyHistorySha(['2026-05-13', '2026-06-10'])).toBe('daily:2026-05-13,2026-06-10');
  });
});
