import { bankSnapshotAt, type BankInsightsPayload } from '../src/data/bankInsights';

const payload: BankInsightsPayload = {
  schema_version: 1,
  run_date: '2026-06-03',
  run_dates: ['2026-06-01', '2026-06-02', '2026-06-03'],
  banks: {
    'Alpha Bank': {
      Mortgage: {
        best: [5.99, 5.74, 5.74],
        median: [6.2, 6.0, 6.0],
        count: [10, 10, 10],
      },
    },
    'Beta Bank': {
      Mortgage: {
        best: [6.1, null, 6.1],
        median: [6.3, null, 6.3],
        count: [5, null, 5],
      },
    },
    'Gamma Bank': {
      Savings: {
        best: [5.0, 5.1, null],
        median: [4.5, 4.6, null],
        count: [3, 3, null],
      },
    },
  },
  events: [],
};

describe('bankSnapshotAt', () => {
  it('returns lender rates as of the scrubbed date with their latest move', () => {
    const rows = bankSnapshotAt(payload, 'Mortgage', '2026-06-03', true);
    expect(rows.map((r) => r.provider)).toEqual(['Alpha Bank', 'Beta Bank']);
    expect(rows[0]).toMatchObject({
      best: 5.74,
      changeBps: -25,
      changedOn: '2026-06-02',
    });
    expect(rows[1]).toMatchObject({ best: 6.1, changeBps: null, changedOn: null });
  });

  it('rewinds to earlier dates without later data leaking in', () => {
    const rows = bankSnapshotAt(payload, 'Mortgage', '2026-06-01', true);
    expect(rows[0]).toMatchObject({ provider: 'Alpha Bank', best: 5.99, changeBps: null });
  });

  it('carries deposit values forward and sorts higher-is-better first', () => {
    const rows = bankSnapshotAt(payload, 'Savings', '2026-06-03', false);
    expect(rows[0]).toMatchObject({
      provider: 'Gamma Bank',
      best: 5.1,
      changeBps: 10,
      changedOn: '2026-06-02',
    });
  });

  it('returns nothing before the first run date or without a payload', () => {
    expect(bankSnapshotAt(payload, 'Mortgage', '2026-05-31', true)).toEqual([]);
    expect(bankSnapshotAt(null, 'Mortgage', '2026-06-03', true)).toEqual([]);
  });
});
