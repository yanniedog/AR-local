import { buildBandPath } from '../src/lib/chartSvgPaths';

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
});
