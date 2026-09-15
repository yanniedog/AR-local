import type { CorePayload, RateRow, Ribbon, RibbonProvider, RibbonStats, SectionKey } from '../types';
import { sha256 } from '@noble/hashes/sha256';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils';

const coreContents = new WeakMap<CoreIntegrityContext, string>();
function contentDigest(core: CorePayload) { return bytesToHex(sha256(utf8ToBytes(JSON.stringify(core)))); }
/** Checked only at calculation boundaries, never by rendering selectors. */
export function verifiedCoreContents(integrity: CoreIntegrityContext | null | undefined): boolean {
  return !!integrity && coreContents.get(integrity) === contentDigest(integrity.core);
}

export interface CoreIntegrityContext {
  schemaVersion: 1;
  /** The exact normalized object consumed by selectors and aggregates. */
  core: CorePayload;
  contract: 'v1' | 'v3';
  runDate: string;
  generationDigest: string | null;
  coreSha256: string | null;
  normalizationVersion: string;
  quarantines: {
    bankHistoryPairs: ReadonlySet<string>;
    rowsByReason: Readonly<Record<string, number>>;
    /** Exact changes to manifest summary dimensions caused by normalization. */
    countImpacts: Readonly<{
      rates: number;
      products: number;
      providers: number;
    }>;
  };
}

export interface CoreIntegrityProvenance {
  contract?: CoreIntegrityContext['contract'];
  generationDigest?: string | null;
  coreSha256?: string | null;
  normalizationVersion?: string;
}

export function bankHistoryPairKey(provider: string, section: SectionKey): string {
  return `${section}\u0000${provider}`;
}

/** Provider/section aggregates that cannot be separated safely after download. */
export function quarantinedBankHistoryPairs(
  integrity: CoreIntegrityContext | null | undefined,
): ReadonlySet<string> {
  return integrity?.quarantines.bankHistoryPairs ?? new Set<string>();
}

/**
 * Some data holders publish products explicitly named "Term Deposit" under the
 * broad TRANS_AND_SAVINGS_ACCOUNTS CDR category. The producer currently carries
 * that category through to the Savings section. Keep this rule deliberately
 * narrow: product names must begin with the product identity, so references to a
 * term deposit (for example, a loan "secured by a Term Deposit") and specialist
 * Farm Management Deposits are not reclassified.
 */
export function isExplicitTermDepositProduct(row: Pick<RateRow, 'product_name'>): boolean {
  const name = String(row.product_name || '')
    .trim()
    .replace(/\s+/g, ' ');
  return /^(?:fixed )?term deposit(?:\b|$)/i.test(name);
}

function stats(values: number[]): RibbonStats {
  if (!values.length) return { min: null, max: null, mean: null, median: null };
  const sorted = values.slice().sort((left, right) => left - right);
  const middle = sorted.length >> 1;
  return {
    min: sorted[0],
    max: sorted[sorted.length - 1],
    mean: sorted.reduce((sum, value) => sum + value, 0) / sorted.length,
    median: sorted.length % 2
      ? sorted[middle]
      : (sorted[middle - 1] + sorted[middle]) / 2,
  };
}

function finiteRate(row: RateRow): number | null {
  if (row.rate == null || row.rate === '') return null;
  const value = Number(row.rate);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Rebuild the complete producer-shaped ribbon after quarantining rows. */
export function rebuildSectionRibbon(rows: readonly RateRow[]): Ribbon {
  const providerRows = new Map<string, RateRow[]>();
  const products = new Set<string>();
  const rates: number[] = [];

  for (const row of rows) {
    const rate = finiteRate(row);
    if (rate === null) continue;
    products.add(row.product_key);
    rates.push(rate);
    const provider = String(row.provider || 'Unknown');
    const grouped = providerRows.get(provider);
    if (grouped) grouped.push(row);
    else providerRows.set(provider, [row]);
  }

  const providers: RibbonProvider[] = [...providerRows.entries()]
    .map(([provider, grouped]) => ({
      provider,
      rates: grouped.length,
      products: new Set(grouped.map((row) => row.product_key)).size,
      ...stats(grouped.map(finiteRate).filter((value): value is number => value !== null)),
    }))
    .sort((left, right) => left.provider.localeCompare(right.provider));

  return {
    counts: {
      rates: rates.length,
      products: products.size,
      providers: providerRows.size,
    },
    range: stats(rates),
    providers,
  };
}

/**
 * Quarantine explicit term-deposit identities from Savings at the shared core
 * trust boundary. We intentionally do not move them into TD: their producer
 * taxonomy and term facets are also Savings-shaped, so presenting them as a
 * trustworthy TD record would invent data. A corrected producer payload can add
 * them back to TD later without any client migration.
 *
 * Returns the original object when no correction is needed. This keeps the hot
 * path cheap and makes repeated normalization idempotent by reference.
 */
export function normalizeCoreWithIntegrity(
  core: CorePayload,
  provenance: CoreIntegrityProvenance = {},
): { core: CorePayload; integrity: CoreIntegrityContext } {
  const savings = core?.sections?.Savings;
  const contaminated = savings && Array.isArray(savings.rates)
    ? savings.rates.filter(isExplicitTermDepositProduct)
    : [];
  const rates = savings && Array.isArray(savings.rates)
    ? savings.rates.filter((row) => !isExplicitTermDepositProduct(row))
    : null;

  const quarantinedPairs = new Set<string>(
    contaminated
      .map((row) => bankHistoryPairKey(row.provider, 'Savings')),
  );

  const normalized: CorePayload = savings && rates && rates.length !== savings.rates.length
    ? {
        ...core,
        sections: {
          ...core.sections,
          Savings: {
            ...savings,
            rates,
            ribbon: rebuildSectionRibbon(rates),
          },
        },
      }
    : core;
  const rawRows = Object.values(core.sections ?? {}).flatMap((section) => section.rates ?? []);
  const normalizedRows = Object.values(normalized.sections ?? {})
    .flatMap((section) => section.rates ?? []);
  const uniqueCount = (rowsToCount: readonly RateRow[], key: 'product_key' | 'provider') =>
    new Set(rowsToCount.map((row) => row[key]).filter(Boolean)).size;
  const integrity: CoreIntegrityContext = {
    schemaVersion: 1,
    core: normalized,
    contract: provenance.contract ?? 'v1',
    runDate: normalized.run_date,
    generationDigest: provenance.generationDigest ?? null,
    coreSha256: provenance.coreSha256 ?? null,
    normalizationVersion: provenance.normalizationVersion ?? 'app-section-integrity-v1',
    quarantines: {
      bankHistoryPairs: quarantinedPairs,
      rowsByReason: Object.freeze({
        explicit_term_deposit_in_savings: contaminated.length,
      }),
      countImpacts: Object.freeze({
        rates: rawRows.length - normalizedRows.length,
        products: uniqueCount(rawRows, 'product_key') - uniqueCount(normalizedRows, 'product_key'),
        providers: uniqueCount(rawRows, 'provider') - uniqueCount(normalizedRows, 'provider'),
      }),
    },
  };
  coreContents.set(integrity, contentDigest(normalized));
  return { core: normalized, integrity };
}

/**
 * Legacy adapter retained for fixtures and callers that only need normalized
 * rows. Trust-sensitive consumers must use `normalizeCoreWithIntegrity` and
 * carry its context explicitly.
 */
export function normalizeCoreSectionIntegrity(core: CorePayload): CorePayload {
  return normalizeCoreWithIntegrity(core).core;
}

/** Preserve trust evidence when a non-catalogue field creates a new core object. */
export function rebindCoreIntegrity(
  integrity: CoreIntegrityContext,
  core: CorePayload,
): CoreIntegrityContext {
  const rebound: CoreIntegrityContext = {
    ...integrity,
    core,
    runDate: core.run_date,
  };
  if (verifiedCoreContents(integrity)) coreContents.set(rebound, contentDigest(core));
  return rebound;
}
