import type { ManifestFile, RateRow, SectionData, SectionKey } from '../../types';
import { versionLt } from '../versionCompare';
import { isValidCalendarDate } from '../calendarDate';
import { validatePayloadAccounting } from './payloadAccounting';
import { revisionTag } from '../../data/payloadRevision';
import {
  APP_HEALTH_ASSET_KEYS,
  APP_HEALTH_CHECK_CODES,
  type AppHealthAssetKey,
  type AppHealthCheck,
  type AppHealthDataSnapshot,
  type AppHealthSourceContract,
  type AppHealthStatus,
} from './types';

const SHA256_RE = /^[a-f0-9]{64}$/i;

function check(
  code: AppHealthCheck['code'],
  label: string,
  domain: AppHealthCheck['domain'],
  status: AppHealthStatus,
  metrics: AppHealthCheck['metrics'],
  summary?: string,
  localEvidence?: AppHealthCheck['localEvidence'],
): AppHealthCheck {
  return { id: code, code, label, domain, status, metrics, summary, localEvidence };
}

function rowsFor(
  snapshot: AppHealthDataSnapshot,
  section: SectionKey,
): readonly RateRow[] {
  const sectionData = snapshot.core?.sections?.[section] as SectionData | undefined;
  return Array.isArray(sectionData?.rates) ? sectionData.rates : [];
}

function allRows(snapshot: AppHealthDataSnapshot): [SectionKey, RateRow][] {
  if (!snapshot.core) return [];
  const result: [SectionKey, RateRow][] = [];
  for (const section of Object.keys(snapshot.core.sections ?? {}) as SectionKey[]) {
    for (const row of rowsFor(snapshot, section)) result.push([section, row]);
  }
  return result;
}

function manifestFile(
  snapshot: AppHealthDataSnapshot,
  asset: AppHealthAssetKey,
): ManifestFile | undefined {
  return snapshot.manifest?.files?.[asset];
}

function parseTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function isReleaseAssetUrl(url: string, contract: AppHealthSourceContract): boolean {
  try {
    const parsed = new URL(url);
    return (
      parsed.protocol === 'https:' &&
      parsed.hostname.toLowerCase() === 'github.com' &&
      parsed.username === '' &&
      parsed.password === '' &&
      parsed.port === '' &&
      parsed.hash === '' &&
      parsed.search === '' &&
      parsed.pathname.startsWith(`/${contract.repo}/releases/download/`)
    );
  } catch {
    return false;
  }
}

function isBundledSampleAssetUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return (
      parsed.protocol === 'bundled:' &&
      parsed.hostname === 'sample' &&
      parsed.username === '' &&
      parsed.password === '' &&
      parsed.port === '' &&
      parsed.search === '' &&
      parsed.hash === '' &&
      parsed.pathname.length > 1
    );
  } catch {
    return false;
  }
}

function validDescriptor(
  descriptor: ManifestFile | undefined,
  contract: AppHealthSourceContract,
  allowBundledSample: boolean,
): boolean {
  let urlNameMatches = false;
  if (descriptor) {
    try {
      const parsed = new URL(descriptor.url);
      urlNameMatches = decodeURIComponent(parsed.pathname.split('/').pop() ?? '') === descriptor.name;
    } catch {
      urlNameMatches = false;
    }
  }
  return Boolean(
    descriptor &&
      typeof descriptor.name === 'string' &&
      /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(descriptor.name) &&
      urlNameMatches &&
      Number.isSafeInteger(descriptor.bytes) &&
      descriptor.bytes > 0 &&
      SHA256_RE.test(descriptor.sha256) &&
      (isReleaseAssetUrl(descriptor.url, contract) ||
        (allowBundledSample && isBundledSampleAssetUrl(descriptor.url))),
  );
}

function evaluateSourceState(snapshot: AppHealthDataSnapshot): AppHealthCheck {
  let status: AppHealthStatus = 'pass';
  let summary = 'The active core payload is available from the live source.';
  if (!snapshot.core) {
    status = 'fail';
    summary = snapshot.source === 'unavailable'
      ? 'The requested live publication could not be acquired for this audit.'
      : 'No core payload is available to audit.';
  } else if (snapshot.source === 'sample') {
    status = 'warn';
    summary = 'The app is showing bundled sample data, not published rate data.';
  } else if (snapshot.source === 'cache') {
    status = 'warn';
    summary = 'The app is showing a cached payload; freshness is assessed separately.';
  }
  return check(
    APP_HEALTH_CHECK_CODES.SOURCE_STATE,
    'Data source state',
    'data-completeness',
    status,
    { source: snapshot.source, coreAvailable: snapshot.core != null },
    summary,
  );
}

function evaluateManifest(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
): AppHealthCheck {
  const manifest = snapshot.manifest;
  if (!manifest) {
    return check(
      APP_HEALTH_CHECK_CODES.MANIFEST_CONTRACT,
      'Manifest contract',
      'data-integrity',
      snapshot.source === 'remote' ? 'fail' : 'unavailable',
      { manifestAvailable: false },
      snapshot.source === 'remote'
        ? 'The live payload has no manifest evidence.'
        : 'No manifest is available in this local snapshot.',
    );
  }

  const expectedTag =
    manifest.tag === contract.rollingTag ||
    manifest.tag === `${contract.datedTagPrefix}${manifest.run_date}` ||
    (manifest.payload_revision?.schema_version === 1 && Number.isSafeInteger(manifest.payload_revision.revision) &&
      manifest.payload_revision.revision > 0 && manifest.tag === revisionTag(manifest.run_date, manifest.payload_revision.revision)) ||
    (snapshot.source === 'sample' && manifest.tag === 'bundled-sample');
  const schemaSupported = contract.supportedManifestSchemas.includes(manifest.schema_version);
  const appCompatible = Boolean(
    !snapshot.appVersion ||
      !manifest.app_min_version ||
      !versionLt(snapshot.appVersion, manifest.app_min_version),
  );
  const validRunDate = isValidCalendarDate(manifest.run_date);
  const validGeneratedAt = parseTimestamp(manifest.generated_at) != null;
  const violations = [
    !schemaSupported,
    manifest.repo !== contract.repo,
    !expectedTag,
    !appCompatible,
    !validRunDate,
    !validGeneratedAt,
  ].filter(Boolean).length;

  return check(
    APP_HEALTH_CHECK_CODES.MANIFEST_CONTRACT,
    'Manifest contract',
    'data-integrity',
    violations ? 'fail' : 'pass',
    {
      manifestAvailable: true,
      schemaSupported,
      repoMatches: manifest.repo === contract.repo,
      tagMatches: expectedTag,
      appCompatible,
      validRunDate,
      validGeneratedAt,
      violations,
    },
    violations ? 'The manifest violates the shipping v1 source contract.' : undefined,
  );
}

function evaluateCoreSchema(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
): AppHealthCheck {
  if (!snapshot.core) {
    return check(
      APP_HEALTH_CHECK_CODES.CORE_SCHEMA,
      'Core payload schema',
      'data-integrity',
      'unavailable',
      { coreAvailable: false, schemaSupported: false },
      'The core payload schema cannot be checked because no core payload is loaded.',
    );
  }
  const schemaSupported = contract.supportedCoreSchemas.includes(snapshot.core.schema_version);
  return check(
    APP_HEALTH_CHECK_CODES.CORE_SCHEMA,
    'Core payload schema',
    'data-integrity',
    schemaSupported ? 'pass' : 'fail',
    {
      coreAvailable: true,
      schemaVersion: snapshot.core.schema_version,
      schemaSupported,
    },
    schemaSupported
      ? undefined
      : 'The loaded core payload uses a schema this app does not support.',
  );
}

function evaluateAssetDescriptors(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
): AppHealthCheck {
  if (!snapshot.manifest) {
    return check(
      APP_HEALTH_CHECK_CODES.ASSET_DESCRIPTORS,
      'Asset descriptors',
      'data-integrity',
      'unavailable',
      { manifestAvailable: false },
      'Asset descriptors cannot be checked without a manifest.',
    );
  }

  let invalidRequired = 0;
  let missingOptional = 0;
  let invalidOptional = 0;
  for (const asset of contract.requiredAssets) {
    if (!validDescriptor(manifestFile(snapshot, asset), contract, snapshot.source === 'sample')) {
      invalidRequired += 1;
    }
  }
  for (const asset of contract.optionalAssets) {
    const descriptor = manifestFile(snapshot, asset);
    if (!descriptor) missingOptional += 1;
    else if (!validDescriptor(descriptor, contract, snapshot.source === 'sample')) invalidOptional += 1;
  }
  const status: AppHealthStatus = invalidRequired || invalidOptional ? 'fail' : 'pass';
  return check(
    APP_HEALTH_CHECK_CODES.ASSET_DESCRIPTORS,
    'Asset descriptors',
    'data-integrity',
    status,
    {
      requiredAssets: contract.requiredAssets.length,
      invalidRequired,
      optionalAssets: contract.optionalAssets.length,
      missingOptional,
      invalidOptional,
    },
    status === 'fail' ? 'One or more published asset descriptors are unsafe or incomplete.' : undefined,
  );
}

function evaluateRunIdentity(snapshot: AppHealthDataSnapshot): AppHealthCheck {
  if (!snapshot.core) {
    return check(
      APP_HEALTH_CHECK_CODES.RUN_IDENTITY,
      'Payload run identity',
      'data-integrity',
      'fail',
      { coreAvailable: false, comparisons: 0, mismatches: 0 },
      'A run identity cannot be established without the core payload.',
    );
  }

  let comparisons = 0;
  let mismatches = 0;
  let indexLag = false;
  const coreRunDate = snapshot.core.run_date;
  const validCoreRunDate = isValidCalendarDate(coreRunDate);
  if (snapshot.manifest) {
    comparisons += 1;
    if (snapshot.manifest.run_date !== coreRunDate) mismatches += 1;
  }
  if (snapshot.details) {
    comparisons += 1;
    if (!isValidCalendarDate(snapshot.details.runDate) || snapshot.details.runDate !== coreRunDate) {
      mismatches += 1;
    }
  }
  if (snapshot.datesIndex) {
    comparisons += 1;
    const invalidIndexDates = snapshot.datesIndex.dates.filter(
      (date) => !isValidCalendarDate(date),
    ).length;
    const latest =
      snapshot.datesIndex.latestRunDate ??
      snapshot.datesIndex.dates[snapshot.datesIndex.dates.length - 1] ??
      null;
    const validLatest = latest != null && isValidCalendarDate(latest);
    const coreIncluded = snapshot.datesIndex.dates.includes(coreRunDate);
    if (invalidIndexDates > 0 || !validLatest) {
      mismatches += 1;
    } else if (!coreIncluded || latest !== coreRunDate) {
      if (validCoreRunDate && !coreIncluded && coreRunDate > latest) indexLag = true;
      else mismatches += 1;
    }
  }
  const status: AppHealthStatus = !validCoreRunDate || mismatches
    ? 'fail'
    : indexLag
      ? 'warn'
      : comparisons
        ? 'pass'
        : 'unavailable';
  return check(
    APP_HEALTH_CHECK_CODES.RUN_IDENTITY,
    'Payload run identity',
    'data-integrity',
    status,
    { validCoreRunDate, comparisons, mismatches, indexLag },
    status === 'fail'
      ? 'Loaded assets do not describe one complete publication run.'
      : indexLag
        ? 'The loaded publication is ahead of the dates index; finalization may still be propagating.'
        : undefined,
  );
}

function evaluateRequiredSections(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
): AppHealthCheck {
  let missingSections = 0;
  let emptySections = 0;
  let rateRows = 0;
  for (const section of contract.requiredSections) {
    const sectionData = snapshot.core?.sections?.[section] as SectionData | undefined;
    if (!sectionData || !Array.isArray(sectionData.rates)) missingSections += 1;
    else if (sectionData.rates.length === 0) emptySections += 1;
    else rateRows += sectionData.rates.length;
  }
  const status: AppHealthStatus = missingSections || emptySections ? 'fail' : 'pass';
  return check(
    APP_HEALTH_CHECK_CODES.REQUIRED_SECTIONS,
    'Required rate sections',
    'data-completeness',
    status,
    {
      requiredSections: contract.requiredSections.length,
      missingSections,
      emptySections,
      rateRows,
    },
    status === 'fail' ? 'At least one required rate section is missing or empty.' : undefined,
  );
}

function invalidRate(value: unknown, required: boolean): boolean {
  if (value == null || value === '') return required;
  const parsed = Number(value);
  // CDR RateString permits negative rates and rates above 100%.
  return !Number.isFinite(parsed);
}

function evaluateRateValues(snapshot: AppHealthDataSnapshot): AppHealthCheck {
  const rows = allRows(snapshot);
  let invalidHeadlineRates = 0;
  let invalidOptionalRates = 0;
  for (const [, row] of rows) {
    if (invalidRate(row.rate, true)) invalidHeadlineRates += 1;
    if (row.ongoing_rate != null && row.ongoing_rate !== '' && invalidRate(row.ongoing_rate, false)) {
      invalidOptionalRates += 1;
    }
    if (
      row.comparison_rate != null &&
      row.comparison_rate !== '' &&
      invalidRate(row.comparison_rate, false)
    ) {
      invalidOptionalRates += 1;
    }
  }
  const status: AppHealthStatus = invalidHeadlineRates || invalidOptionalRates ? 'fail' : rows.length ? 'pass' : 'unavailable';
  return check(
    APP_HEALTH_CHECK_CODES.RATE_VALUES,
    'Finite rate values',
    'data-integrity',
    status,
    { rows: rows.length, invalidHeadlineRates, invalidOptionalRates },
    status === 'fail' ? 'One or more displayed rate values are missing, malformed, or non-finite.' : undefined,
  );
}

function evaluateExactTierIdentities(snapshot: AppHealthDataSnapshot): AppHealthCheck {
  const rows = allRows(snapshot);
  const groups = new Map<string, (number | undefined)[]>();
  let missingProductKeys = 0;
  let missingRowIdentity = 0;
  let ineligibleExactRows = 0;
  for (const [section, row] of rows) {
    const productKey = String(row.product_key ?? '').trim();
    if (!String(row.provider ?? '').trim() || !String(row.product_name ?? '').trim()) {
      missingRowIdentity += 1;
    }
    if (!productKey) {
      missingProductKeys += 1;
      continue;
    }
    const key = `${section}\u0000${productKey}`;
    const values = groups.get(key) ?? [];
    values.push(row.rate_index);
    groups.set(key, values);
    if (
      row.exact_alert_eligible === true &&
      (!Number.isInteger(row.rate_index) || Number(row.rate_index) < 0)
    ) {
      ineligibleExactRows += 1;
    }
  }

  let ambiguousMultiTierProducts = 0;
  let duplicateExactTiers = 0;
  for (const indexes of groups.values()) {
    if (indexes.length <= 1) continue;
    const finite = indexes.filter(
      (value): value is number => Number.isInteger(value) && Number(value) >= 0,
    );
    if (finite.length !== indexes.length) ambiguousMultiTierProducts += 1;
    duplicateExactTiers += finite.length - new Set(finite).size;
  }
  const violations =
    missingProductKeys +
    missingRowIdentity +
    ineligibleExactRows +
    ambiguousMultiTierProducts +
    duplicateExactTiers;
  return check(
    APP_HEALTH_CHECK_CODES.EXACT_TIER_IDENTITIES,
    'Exact tier identities',
    'data-integrity',
    violations ? 'fail' : rows.length ? 'pass' : 'unavailable',
    {
      products: groups.size,
      missingProductKeys,
      missingRowIdentity,
      ineligibleExactRows,
      ambiguousMultiTierProducts,
      duplicateExactTiers,
    },
    violations ? 'Some rate tiers cannot be identified uniquely and safely.' : undefined,
  );
}

function evaluateTaxonomyRoots(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
): AppHealthCheck {
  let missingTaxonomy = 0;
  let wrongRoot = 0;
  let rows = 0;
  for (const section of contract.requiredSections) {
    for (const row of rowsFor(snapshot, section)) {
      rows += 1;
      const taxonomy = String(row.taxonomy_path ?? '').trim();
      if (!taxonomy) missingTaxonomy += 1;
      else if (taxonomy.split('.')[0] !== contract.taxonomyRoots[section]) wrongRoot += 1;
    }
  }
  const status: AppHealthStatus = wrongRoot || missingTaxonomy ? 'warn' : rows ? 'pass' : 'unavailable';
  return check(
    APP_HEALTH_CHECK_CODES.TAXONOMY_ROOTS,
    'Taxonomy roots',
    'data-integrity',
    status,
    { rows, missingTaxonomy, wrongRoot },
    wrongRoot
      ? 'Some rate rows are available to flat search but excluded from the section hierarchy.'
      : missingTaxonomy
        ? 'Some rate rows cannot appear in the hierarchy because taxonomy is absent.'
        : undefined,
  );
}

function finiteOrNull(value: unknown): boolean {
  return value == null || (typeof value === 'number' && Number.isFinite(value));
}

function evaluateRibbonReconciliation(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
): AppHealthCheck {
  let invalidSections = 0;
  let checkedSections = 0;
  let nonPositiveRateRows = 0;
  for (const section of contract.requiredSections) {
    // Producer ribbons summarize positive rates. Zero-rate tiers remain real
    // catalogue rows and are checked by RATE_VALUES, not missing ribbon rows.
    const allSectionRows = rowsFor(snapshot, section);
    const rows = allSectionRows.filter((row) => Number.isFinite(Number(row.rate)) && Number(row.rate) > 0);
    nonPositiveRateRows += allSectionRows.length - rows.length;
    const ribbon = snapshot.core?.sections?.[section]?.ribbon;
    if (!ribbon) {
      invalidSections += 1;
      continue;
    }
    checkedSections += 1;
    const productCount = new Set(rows.map((row) => row.product_key).filter(Boolean)).size;
    const rowsByProvider = new Map<string, RateRow[]>();
    for (const row of rows) {
      const provider = String(row.provider ?? '').trim();
      if (!provider) continue;
      const providerRows = rowsByProvider.get(provider) ?? [];
      providerRows.push(row);
      rowsByProvider.set(provider, providerRows);
    }
    const providerCount = rowsByProvider.size;
    const counts = ribbon.counts;
    const range = ribbon.range;
    const countInvalid =
      !Number.isInteger(counts?.rates) ||
      counts.rates !== rows.length ||
      !Number.isInteger(counts?.products) ||
      counts.products !== productCount ||
      !Number.isInteger(counts?.providers) ||
      counts.providers !== providerCount ||
      !Array.isArray(ribbon.providers) ||
      ribbon.providers.length !== counts.providers;
    const rangeInvalid =
      !finiteOrNull(range?.min) ||
      !finiteOrNull(range?.max) ||
      !finiteOrNull(range?.mean) ||
      !finiteOrNull(range?.median) ||
      (typeof range?.min === 'number' && typeof range?.max === 'number' && range.min > range.max);
    const ribbonProviderNames = new Set<string>();
    const providerStatsInvalid = Array.isArray(ribbon.providers) && ribbon.providers.some((provider) => {
      const providerName = String(provider.provider ?? '').trim();
      const providerRows = rowsByProvider.get(providerName) ?? [];
      const providerProducts = new Set(
        providerRows.map((row) => row.product_key).filter(Boolean),
      ).size;
      const duplicate = ribbonProviderNames.has(providerName);
      ribbonProviderNames.add(providerName);
      return !providerName ||
        duplicate ||
        !rowsByProvider.has(providerName) ||
        !Number.isInteger(provider.rates) ||
        provider.rates !== providerRows.length ||
        !Number.isInteger(provider.products) ||
        provider.products !== providerProducts ||
        !finiteOrNull(provider.min) ||
        !finiteOrNull(provider.max) ||
        !finiteOrNull(provider.mean) ||
        !finiteOrNull(provider.median) ||
        (typeof provider.min === 'number' &&
          typeof provider.max === 'number' &&
          provider.min > provider.max);
    });
    const providerSetInvalid = ribbonProviderNames.size !== rowsByProvider.size ||
      [...rowsByProvider.keys()].some((provider) => !ribbonProviderNames.has(provider));
    const providerRates = Array.isArray(ribbon.providers)
      ? ribbon.providers.reduce((sum, provider) => sum + provider.rates, 0)
      : -1;
    if (
      countInvalid ||
      rangeInvalid ||
      providerStatsInvalid ||
      providerSetInvalid ||
      providerRates !== counts.rates
    ) {
      invalidSections += 1;
    }
  }
  const rows = allRows(snapshot).map(([, row]) => row);
  const actualManifestCounts: Record<'rates' | 'products' | 'providers', number> = {
    rates: rows.length,
    products: new Set(rows.map((row) => row.product_key).filter(Boolean)).size,
    providers: new Set(rows.map((row) => row.provider).filter(Boolean)).size,
  };
  let declaredCountComparisons = 0;
  let declaredCountMismatches = 0;
  let declaredCountAdjustments = 0;
  const quarantinedRows = Object.values(snapshot.quarantine?.rowsByReason ?? {}).reduce(
    (sum, value) => sum + (Number.isFinite(value) && value > 0 ? value : 0),
    0,
  );
  const quarantineImpacts = snapshot.quarantine?.countImpacts;
  const accounting = validatePayloadAccounting(snapshot);
  for (const [name, actual] of Object.entries(actualManifestCounts) as
    ['rates' | 'products' | 'providers', number][]) {
    if (!snapshot.manifest || !(name in snapshot.manifest.counts)) continue;
    declaredCountComparisons += 1;
    const declared = snapshot.manifest.counts[name];
    if (!Number.isInteger(declared) || declared < 0) {
      declaredCountMismatches += 1;
    } else if (declared !== actual) {
      const positiveDelta = declared - actual;
      const sourceExclusion = accounting.valid
        ? name === 'rates' ? accounting.excludedRates : name === 'products' ? accounting.productsWithoutRates : 0
        : 0;
      if (positiveDelta > 0 && positiveDelta === sourceExclusion + (quarantineImpacts?.[name] ?? 0)) {
        declaredCountAdjustments += 1;
      } else {
        declaredCountMismatches += 1;
      }
    }
  }
  const status: AppHealthStatus = invalidSections || declaredCountMismatches || (accounting.present && !accounting.valid)
    ? 'fail'
    : checkedSections
      ? 'pass'
      : 'unavailable';
  return check(
    APP_HEALTH_CHECK_CODES.RIBBON_RECONCILIATION,
    'Rate summary reconciliation',
    'data-integrity',
    status,
    {
      checkedSections,
      invalidSections,
      nonPositiveRateRows,
      accountingPresent: accounting.present,
      accountingValid: accounting.valid,
      explainedSourceRateExclusions: accounting.excludedRates,
      explainedProductsWithoutRates: accounting.productsWithoutRates,
      declaredCountComparisons,
      declaredCountAdjustments,
      declaredCountMismatches,
      quarantinedRows,
      quarantineImpactsAvailable: Boolean(quarantineImpacts),
      quarantineRateImpact: quarantineImpacts?.rates ?? null,
      quarantineProductImpact: quarantineImpacts?.products ?? null,
      quarantineProviderImpact: quarantineImpacts?.providers ?? null,
    },
    status === 'fail' ? 'A section or manifest summary does not reconcile with the loaded rows.' : undefined,
  );
}

function evaluateCoverage(snapshot: AppHealthDataSnapshot): AppHealthCheck {
  const coverage = snapshot.core?.coverage;
  if (!coverage) {
    return check(
      APP_HEALTH_CHECK_CODES.COVERAGE,
      'Producer coverage',
      'data-completeness',
      'unavailable',
      { coverageAvailable: false },
      'This payload predates producer coverage evidence.',
    );
  }

  const attempted = coverage.providers_attempted;
  const succeeded = coverage.providers_succeeded;
  const failures = coverage.provider_failures ?? coverage.failures ?? [];
  const failedCount = coverage.counts?.providers_failed ?? failures.length;
  const partialCount = coverage.counts?.providers_partial ?? 0;
  const totalsAvailable = attempted != null && succeeded != null;
  if (!totalsAvailable) {
    return check(
      APP_HEALTH_CHECK_CODES.COVERAGE,
      'Producer coverage',
      'data-completeness',
      'unavailable',
      {
        coverageAvailable: true,
        totalsAvailable: false,
        providersAttempted: attempted ?? null,
        providersSucceeded: succeeded ?? null,
        providersFailed: failedCount,
        providersPartial: partialCount,
        limitations: coverage.limitations?.length ?? 0,
        invalidCounts: false,
      },
      'Provider coverage totals are incomplete, so complete coverage cannot be established.',
    );
  }
  const invalidCounts =
    (attempted != null && (!Number.isInteger(attempted) || attempted < 0)) ||
    (succeeded != null && (!Number.isInteger(succeeded) || succeeded < 0)) ||
    (attempted != null && succeeded != null && succeeded > attempted) ||
    !Number.isInteger(failedCount) ||
    failedCount < 0 ||
    !Number.isInteger(partialCount) ||
    partialCount < 0 ||
    (attempted != null && succeeded != null && succeeded + failedCount > attempted + partialCount);
  const degraded = failedCount > 0 || partialCount > 0 || (coverage.limitations?.length ?? 0) > 0;
  const status: AppHealthStatus = invalidCounts ? 'fail' : degraded ? 'warn' : 'pass';
  return check(
    APP_HEALTH_CHECK_CODES.COVERAGE,
    'Producer coverage',
    'data-completeness',
    status,
    {
      coverageAvailable: true,
      providersAttempted: attempted ?? null,
      providersSucceeded: succeeded ?? null,
      providersFailed: failedCount,
      providersPartial: partialCount,
      limitations: coverage.limitations?.length ?? 0,
      invalidCounts,
    },
    invalidCounts
      ? 'Producer coverage counts do not reconcile.'
      : degraded
        ? 'The producer reported failed, partial, or limited coverage.'
        : undefined,
  );
}

function evaluateQuarantine(snapshot: AppHealthDataSnapshot): AppHealthCheck {
  if (!snapshot.quarantine) {
    return check(
      APP_HEALTH_CHECK_CODES.QUARANTINE,
      'Quarantine impact',
      'data-completeness',
      'unavailable',
      { evidenceAvailable: false },
      'No normalization quarantine evidence was supplied to this audit.',
    );
  }
  const rowCount = Object.values(snapshot.quarantine.rowsByReason).reduce(
    (sum, value) => sum + (Number.isFinite(value) && value > 0 ? value : 0),
    0,
  );
  const affected = rowCount + Math.max(0, snapshot.quarantine.bankHistoryPairs);
  return check(
    APP_HEALTH_CHECK_CODES.QUARANTINE,
    'Quarantine impact',
    'data-completeness',
    affected ? 'warn' : 'pass',
    {
      evidenceAvailable: true,
      quarantinedRows: rowCount,
      quarantinedBankHistoryPairs: Math.max(0, snapshot.quarantine.bankHistoryPairs),
      quarantineReasons: Object.keys(snapshot.quarantine.rowsByReason).length,
    },
    affected ? 'Invalid or cross-section records were withheld from user-facing results.' : undefined,
  );
}

function evaluateFreshness(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
  nowMs: number,
): AppHealthCheck {
  const nextDueMs = parseTimestamp(snapshot.manifest?.schedule?.next_due_utc);
  const nextDueValue = snapshot.manifest?.schedule?.next_due_utc;
  if (!nextDueValue) {
    return check(
      APP_HEALTH_CHECK_CODES.FRESHNESS,
      'Publication freshness',
      'data-completeness',
      'unavailable',
      { nextDueAvailable: false },
      'The producer did not publish a machine-readable next due time.',
    );
  }
  if (nextDueMs == null) {
    return check(
      APP_HEALTH_CHECK_CODES.FRESHNESS,
      'Publication freshness',
      'data-completeness',
      'fail',
      { nextDueAvailable: true, validNextDue: false },
      'The producer next due time is not a valid timestamp.',
    );
  }
  const staleAfterMs = nextDueMs + contract.freshnessGraceMs;
  const overdueMs = Math.max(0, nowMs - staleAfterMs);
  return check(
    APP_HEALTH_CHECK_CODES.FRESHNESS,
    'Publication freshness',
    'data-completeness',
    overdueMs > 0 ? 'fail' : 'pass',
    {
      nextDueAvailable: true,
      validNextDue: true,
      graceMs: contract.freshnessGraceMs,
      overdueMs,
    },
    overdueMs > 0 ? 'Published data is beyond the producer schedule and configured grace window.' : undefined,
  );
}

function evaluateDetailsCompleteness(snapshot: AppHealthDataSnapshot): AppHealthCheck {
  if (!snapshot.core) {
    return check(
      APP_HEALTH_CHECK_CODES.DETAILS_COMPLETENESS,
      'Product detail record coverage',
      'data-completeness',
      'fail',
      { coreProducts: 0, detailProducts: 0, coveragePercent: null },
      'Product detail coverage cannot be assessed without core data.',
    );
  }
  if (!snapshot.details) {
    return check(
      APP_HEALTH_CHECK_CODES.DETAILS_COMPLETENESS,
      'Product detail record coverage',
      'data-completeness',
      'unavailable',
      { coreProducts: new Set(allRows(snapshot).map(([, row]) => row.product_key)).size, detailProducts: 0, coveragePercent: null },
      'Product details were not available to this audit.',
    );
  }
  const coreProducts = new Set(
    allRows(snapshot).map(([, row]) => row.product_key).filter(Boolean),
  ).size;
  const detailProducts = Math.max(0, snapshot.details.productCount);
  const matchedProducts = Math.max(
    0,
    snapshot.details.matchedProductCount ?? Math.min(coreProducts, detailProducts),
  );
  const orphanProducts = Math.max(
    0,
    snapshot.details.orphanProductCount ?? Math.max(0, detailProducts - matchedProducts),
  );
  const missingProducts = Math.max(0, coreProducts - matchedProducts);
  const coveragePercent = coreProducts
    ? Math.min(100, Math.round((matchedProducts / coreProducts) * 10_000) / 100)
    : null;
  const runMatches = snapshot.details.runDate === snapshot.core.run_date;
  const accounting = validatePayloadAccounting(snapshot);
  const explainedOrphans = accounting.valid && detailProducts === accounting.sourceProducts
    ? accounting.productsWithoutRates + (snapshot.quarantine?.countImpacts?.products ?? 0) : 0;
  const impossibleCounts = matchedProducts > coreProducts || matchedProducts + orphanProducts > detailProducts;
  const status: AppHealthStatus = !runMatches || impossibleCounts || (coreProducts > 0 && matchedProducts === 0)
    ? 'fail'
    : (coveragePercent != null && coveragePercent < 100) || orphanProducts !== explainedOrphans
      ? 'warn'
      : 'pass';
  return check(
    APP_HEALTH_CHECK_CODES.DETAILS_COMPLETENESS,
    'Product detail record coverage',
    'data-completeness',
    status,
    {
      coreProducts,
      detailProducts,
      matchedProducts,
      missingProducts,
      orphanProducts,
      explainedOrphanProducts: explainedOrphans,
      coveragePercent,
      runMatches,
      impossibleCounts,
    },
    status === 'fail'
      ? 'The details asset is empty or belongs to a different publication run.'
      : status === 'warn'
        ? missingProducts > 0
          ? 'Some core products have no corresponding detail record.'
          : 'The details asset contains records that are not present in the active core snapshot.'
        : 'This checks product record coverage only. Document and clause completeness are not established by these counts.',
  );
}

function evaluateAssetAvailability(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
): AppHealthCheck {
  let requiredUnavailable = 0;
  let optionalUnavailable = 0;
  let optionalNotObserved = 0;
  let requiredEmpty = 0;
  let optionalEmpty = 0;
  let mismatchedRunDates = 0;
  for (const asset of APP_HEALTH_ASSET_KEYS) {
    const observation = snapshot.assets?.[asset];
    const inferredState = asset === 'core' && snapshot.core
      ? 'ready'
      : asset === 'details' && snapshot.details
        ? 'ready'
        : observation?.state;
    const runDate = observation?.runDate ??
      (asset === 'core' ? snapshot.core?.run_date : asset === 'details' ? snapshot.details?.runDate : null);
    if (
      inferredState === 'ready' &&
      runDate &&
      snapshot.core?.run_date &&
      runDate !== snapshot.core.run_date
    ) {
      mismatchedRunDates += 1;
    }
    if (contract.requiredAssets.includes(asset)) {
      if (inferredState !== 'ready') requiredUnavailable += 1;
      else if (observation?.itemCount === 0) requiredEmpty += 1;
    } else if (contract.optionalAssets.includes(asset)) {
      if (inferredState === 'missing' || inferredState === 'failed') optionalUnavailable += 1;
      else if (inferredState == null || inferredState === 'not-requested') optionalNotObserved += 1;
      else if (observation?.itemCount === 0) optionalEmpty += 1;
    }
  }
  const status: AppHealthStatus = requiredUnavailable || requiredEmpty || mismatchedRunDates
    ? 'fail'
    : optionalUnavailable || optionalEmpty
      ? 'warn'
      : optionalNotObserved
        ? 'unavailable'
        : 'pass';
  return check(
    APP_HEALTH_CHECK_CODES.ASSET_AVAILABILITY,
    'Asset availability',
    'asset-availability',
    status,
    {
      requiredAssets: contract.requiredAssets.length,
      requiredUnavailable,
      requiredEmpty,
      optionalAssets: contract.optionalAssets.length,
      optionalUnavailable,
      optionalEmpty,
      optionalNotObserved,
      mismatchedRunDates,
    },
    requiredUnavailable || requiredEmpty
      ? 'A required app data asset is unavailable or empty.'
      : mismatchedRunDates
        ? 'Loaded assets belong to different publication runs.'
        : optionalUnavailable || optionalEmpty
          ? 'An advertised optional experience has no usable data asset.'
        : optionalNotObserved
          ? 'Some optional assets were not exercised by this audit.'
          : undefined,
  );
}

/** Evaluate payload correctness, completeness, freshness, and asset gaps without I/O. */
export function evaluateAppHealthDataQuality(
  snapshot: AppHealthDataSnapshot,
  contract: AppHealthSourceContract,
  nowMs = Date.now(),
): AppHealthCheck[] {
  return [
    evaluateSourceState(snapshot),
    evaluateManifest(snapshot, contract),
    evaluateCoreSchema(snapshot, contract),
    evaluateAssetDescriptors(snapshot, contract),
    evaluateRunIdentity(snapshot),
    evaluateRequiredSections(snapshot, contract),
    evaluateRateValues(snapshot),
    evaluateExactTierIdentities(snapshot),
    evaluateTaxonomyRoots(snapshot, contract),
    evaluateRibbonReconciliation(snapshot, contract),
    evaluateCoverage(snapshot),
    evaluateQuarantine(snapshot),
    evaluateFreshness(snapshot, contract, nowMs),
    evaluateDetailsCompleteness(snapshot),
    evaluateAssetAvailability(snapshot, contract),
  ];
}
