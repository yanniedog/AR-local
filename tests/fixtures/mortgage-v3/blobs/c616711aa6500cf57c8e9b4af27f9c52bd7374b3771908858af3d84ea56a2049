import type { AppHealthSourceContract } from './types';

const DAY_MS = 24 * 60 * 60 * 1_000;

/**
 * The app-health contract deliberately follows the app's shipping v1 reader.
 * It must not switch the consumer to a speculative producer or v3 endpoint.
 */
export function publishedV1SourceContract(config: { repo: string; rollingTag: string; manifestUrl: string; datesIndexUrl: string; datedTagPrefix: string; schema: number }): AppHealthSourceContract {
  return Object.freeze({
  contract: 'v1',
  repo: config.repo,
  rollingTag: config.rollingTag,
  manifestUrl: config.manifestUrl,
  datesIndexUrl: config.datesIndexUrl,
  datedTagPrefix: config.datedTagPrefix,
  supportedManifestSchemas: Object.freeze([config.schema] as const),
  supportedCoreSchemas: Object.freeze([config.schema] as const),
  requiredSections: Object.freeze(['Mortgage', 'Savings', 'TD'] as const),
  taxonomyRoots: Object.freeze({
    Mortgage: 'HOME_LOAN',
    Savings: 'SAVINGS',
    TD: 'TERM_DEPOSIT',
  }),
  requiredAssets: Object.freeze(['core', 'details'] as const),
  optionalAssets: Object.freeze([
    'search_index',
    'history_banks',
    'bank_history',
    'bank_spread_history',
    'rba_calendar',
  ] as const),
  freshnessGraceMs: DAY_MS,
  });
}
