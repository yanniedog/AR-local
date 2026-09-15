import {
  DATED_TAG_PREFIX,
  DATES_INDEX_URL,
  MANIFEST_URL,
  PAYLOAD_REPO,
  RELEASE_TAG,
  SUPPORTED_SCHEMA,
} from '../../config';
import type { AppHealthSourceContract } from './types';

import { publishedV1SourceContract } from './v1Contract';

export const CURRENT_V1_APP_HEALTH_SOURCE_CONTRACT = publishedV1SourceContract({
  repo: PAYLOAD_REPO, rollingTag: RELEASE_TAG, manifestUrl: MANIFEST_URL,
  datesIndexUrl: DATES_INDEX_URL, datedTagPrefix: DATED_TAG_PREFIX, schema: SUPPORTED_SCHEMA,
});

/** Factory for deterministic tests and future contract versions. */
export function createV1AppHealthSourceContract(
  overrides: Partial<AppHealthSourceContract> = {},
): AppHealthSourceContract {
  const base = CURRENT_V1_APP_HEALTH_SOURCE_CONTRACT;
  return Object.freeze({
    ...base,
    ...overrides,
    supportedManifestSchemas: Object.freeze([
      ...(overrides.supportedManifestSchemas ?? base.supportedManifestSchemas),
    ]),
    supportedCoreSchemas: Object.freeze([
      ...(overrides.supportedCoreSchemas ?? base.supportedCoreSchemas),
    ]),
    requiredSections: Object.freeze([
      ...(overrides.requiredSections ?? base.requiredSections),
    ]),
    taxonomyRoots: Object.freeze({ ...(overrides.taxonomyRoots ?? base.taxonomyRoots) }),
    requiredAssets: Object.freeze([...(overrides.requiredAssets ?? base.requiredAssets)]),
    optionalAssets: Object.freeze([...(overrides.optionalAssets ?? base.optionalAssets)]),
  });
}
