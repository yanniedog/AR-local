import { visibleAccountRows } from './format';
import { statsFor, type RateStats } from './taxonomy';
import type { RateRow, Ribbon, SectionData } from '../types';

export function ribbonToRateStats(ribbon: Ribbon): RateStats {
  const { range, counts } = ribbon;
  return {
    min: range.min ?? null,
    max: range.max ?? null,
    mean: range.mean ?? null,
    median: range.median ?? null,
    count: counts.rates,
    products: counts.products,
    providers: counts.providers,
  };
}

export function hasPayloadRibbon(ribbon: Ribbon | undefined): ribbon is Ribbon {
  return ribbon != null && ribbon.range.min != null && ribbon.range.max != null;
}

/**
 * Section-level ribbon stats for Home / Trends / Browse root.
 * Prefer stats from visible hierarchy rows (matches non-standard toggle).
 * Fall back to payload ribbon when client-side stats are empty but payload has range data.
 */
export function resolveSectionRibbonStats(
  sectionData: SectionData | undefined,
  hierarchyRows: RateRow[],
  includeNonStandard: boolean,
): RateStats {
  const filtered = includeNonStandard
    ? hierarchyRows
    : visibleAccountRows(hierarchyRows, false);

  const computed = statsFor(filtered, true);
  if (computed.min != null) return computed;

  if (sectionData && hasPayloadRibbon(sectionData.ribbon)) {
    return ribbonToRateStats(sectionData.ribbon);
  }
  return computed;
}
