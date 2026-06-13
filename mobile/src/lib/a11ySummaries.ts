import { SECTIONS } from '../constants';
import { formatRate } from '../data/format';
import type { RateStats } from '../data/taxonomy';
import type { BankHistoryPoint, HistoryWindow, RbaEntry, SectionKey } from '../types';

/** Visible label prefix so rate color is not the only cue. */
export function rateValueLabel(section: SectionKey, context: 'product' | 'best' = 'product'): string {
  if (context === 'best') return 'Best';
  return SECTIONS[section].lowerIsBetter ? 'Interest rate' : 'Rate';
}

/** Plain-language TalkBack summary for the rate-distribution ribbon. */
export function ribbonA11ySummary(
  stats: RateStats,
  section: SectionKey,
  rbaRate?: number | null,
): string {
  const title = SECTIONS[section].title;
  if (stats.min === null || stats.max === null) {
    return `${title}: no rate data`;
  }
  const parts = [
    `${title} rate distribution`,
    `minimum ${formatRate(stats.min)}`,
    stats.median != null ? `median ${formatRate(stats.median)}` : null,
    stats.mean != null ? `mean ${formatRate(stats.mean)}` : null,
    `maximum ${formatRate(stats.max)}`,
    `${stats.count} rates from ${stats.providers} lenders`,
  ].filter(Boolean) as string[];
  if (rbaRate != null) {
    parts.push(`RBA cash rate ${formatRate(rbaRate)}`);
  }
  return parts.join(', ');
}

/** Plain-language TalkBack summary for the RBA cash-rate step chart. */
export function rbaChartA11ySummary(data: RbaEntry[]): string {
  if (!data.length) return 'RBA cash rate chart: no data';
  const rates = data.map((d) => d.rate);
  const minR = Math.min(...rates);
  const maxR = Math.max(...rates);
  const first = data[0];
  const last = data[data.length - 1];
  return [
    'RBA cash rate chart',
    `from ${first.date} to ${last.date}`,
    `current ${last.rate.toFixed(2)} percent`,
    `range ${minR.toFixed(2)} to ${maxR.toFixed(2)} percent`,
  ].join(', ');
}

function pct(v: number): string {
  return `${(v * 100).toFixed(2)}%`;
}

/** Plain-language TalkBack summary for the bank history ribbon chart. */
export function bankHistoryChartA11ySummary(opts: {
  section: SectionKey;
  window: HistoryWindow;
  activeDate: string;
  activePoint?: BankHistoryPoint;
  showRba: boolean;
  /** Emphasized series value at the selected date (e.g. the product's own rate). */
  highlight?: { label: string; value: number | null };
}): string {
  const { section, window, activeDate, activePoint, showRba, highlight } = opts;
  const title = SECTIONS[section].title;
  const parts = [`${title} history chart`, `${window} window`, `selected ${activeDate}`];
  if (highlight && highlight.value != null) {
    parts.push(`${highlight.label} ${pct(highlight.value)}`);
  }
  if (activePoint) {
    if (activePoint.min != null && activePoint.max != null) {
      parts.push(`range ${pct(activePoint.min)} to ${pct(activePoint.max)}`);
    }
    if (activePoint.median != null) {
      parts.push(`median ${pct(activePoint.median)}`);
    }
    if (activePoint.mean != null) {
      parts.push(`mean ${pct(activePoint.mean)}`);
    }
  }
  if (showRba) {
    parts.push('RBA cash rate overlay shown');
  }
  return parts.join(', ');
}

/** RBA decision row label for TalkBack (direction + values). */
export function rbaDecisionA11yLabel(prior: number, rate: number, date: string): string {
  const direction = rate > prior ? 'Increased' : rate < prior ? 'Decreased' : 'Unchanged';
  return `${direction} on ${date}, from ${prior.toFixed(2)} percent to ${rate.toFixed(2)} percent`;
}
