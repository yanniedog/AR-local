import core from '../assets/sample/core.json';
import { resolveSectionRibbonStats, ribbonToRateStats, hasPayloadRibbon } from '../src/data/ribbonStats';
import { rowsUnder, statsFor } from '../src/data/taxonomy';
import type { CorePayload, SectionKey } from '../src/types';

const sample = core as CorePayload;

describe('ribbonStats', () => {
  it('maps payload ribbon range and counts to RateStats', () => {
    const ribbon = sample.sections.Mortgage.ribbon;
    expect(hasPayloadRibbon(ribbon)).toBe(true);
    const stats = ribbonToRateStats(ribbon);
    expect(stats.min).toBeCloseTo(0.0279, 4);
    expect(stats.max).toBeCloseTo(0.1177, 4);
    expect(stats.count).toBe(5346);
    expect(stats.providers).toBe(51);
  });

  it('recomputes from visible hierarchy rows when non-standard is excluded', () => {
    const section = 'Mortgage' as SectionKey;
    const data = sample.sections[section];
    const hierRows = rowsUnder(data.rates, section, []);
    const stats = resolveSectionRibbonStats(data, hierRows, false);
    const expected = statsFor(hierRows, false);
    expect(stats.min).toBe(expected.min);
    expect(stats.max).toBe(expected.max);
  });

  it('recomputes from rows when non-standard accounts are included', () => {
    const section = 'Mortgage' as SectionKey;
    const data = sample.sections[section];
    const hierRows = rowsUnder(data.rates, section, []);
    const stats = resolveSectionRibbonStats(data, hierRows, true);
    const expected = statsFor(hierRows, true);
    expect(stats.min).toBe(expected.min);
    expect(stats.max).toBe(expected.max);
  });

  it('falls back to payload ribbon when filtered rows yield no stats', () => {
    const stats = resolveSectionRibbonStats(
      sample.sections.Mortgage,
      [],
      false,
    );
    expect(stats.min).toBe(sample.sections.Mortgage.ribbon.range.min);
  });
});
