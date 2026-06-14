import { buildBandPath, buildLinePath } from '../src/lib/chartSvgPaths';

describe('buildLinePath', () => {
  const xAt = (i: number) => i * 10;
  const yAt = (v: number) => v * 100;

  test('restarts after gaps when requested', () => {
    expect(buildLinePath([0.01, null, 0.03], xAt, yAt, true)).toBe('M 0 1 M 20 3');
  });

  test('keeps context lines continuous by default', () => {
    expect(buildLinePath([0.01, null, 0.03], xAt, yAt)).toBe('M 0 1 L 20 3');
  });
});

const BARE_LINE_CMD = /\bL\s+L\b/;

describe('buildBandPath', () => {
  const xAt = (i: number) => 100 + i * 50;
  const yAt = (v: number) => 200 - v * 1000;

  it('returns null when no valid points', () => {
    expect(buildBandPath(['2026-01-01'], [null], [null], xAt, yAt)).toBeNull();
  });

  it('builds a valid single-point vertical band (no bare L commands)', () => {
    const path = buildBandPath(['2026-01-01'], [0.15], [0.05], xAt, yAt);
    expect(path).toBe(`M 100,150 L 100,50 Z`);
    expect(path).not.toMatch(BARE_LINE_CMD);
  });

  it('builds single-point band when only one of many dates has finite min/max', () => {
    const dates = ['2026-01-01', '2026-02-01', '2026-03-01'];
    const mins = [null, 0.15, null];
    const maxs = [null, 0.05, null];
    const path = buildBandPath(dates, mins, maxs, xAt, yAt);
    expect(path).toBe(`M 150,150 L 150,50 Z`);
    expect(path).not.toMatch(BARE_LINE_CMD);
  });

  it('builds a multi-point closed band', () => {
    const dates = ['2026-01-01', '2026-02-01', '2026-03-01'];
    const mins = [0.15, 0.14, 0.13];
    const maxs = [0.05, 0.06, 0.07];
    const path = buildBandPath(dates, mins, maxs, xAt, yAt);
    expect(path).toMatch(/^M /);
    expect(path).toMatch(/ Z$/);
    expect(path).not.toMatch(BARE_LINE_CMD);
  });

  it('skips non-finite coordinates without emitting invalid segments', () => {
    const dates = ['2026-01-01', '2026-02-01', '2026-03-01'];
    const mins = [0.15, null, 0.13];
    const maxs = [0.05, 0.06, 0.07];
    const path = buildBandPath(dates, mins, maxs, xAt, yAt);
    expect(path).not.toMatch(BARE_LINE_CMD);
    if (path) expect(path.endsWith(' Z')).toBe(true);
  });

  it('skips non-finite xAt/yAt outputs and returns null when none remain', () => {
    const badXAt = () => Number.NaN;
    const badYAt = () => Number.POSITIVE_INFINITY;
    expect(buildBandPath(['2026-01-01'], [0.15], [0.05], badXAt, yAt)).toBeNull();
    expect(buildBandPath(['2026-01-01'], [0.15], [0.05], xAt, badYAt)).toBeNull();
  });

  it('skips indices with non-finite xAt/yAt but keeps valid points', () => {
    const dates = ['2026-01-01', '2026-02-01', '2026-03-01'];
    const mins = [0.15, 0.14, 0.13];
    const maxs = [0.05, 0.06, 0.07];
    const xAtSkipMid = (i: number) => (i === 1 ? Number.NaN : xAt(i));
    const path = buildBandPath(dates, mins, maxs, xAtSkipMid, yAt);
    expect(path).not.toMatch(BARE_LINE_CMD);
    expect(path).toMatch(/^M /);
    expect(path).toMatch(/ Z$/);
  });
});
