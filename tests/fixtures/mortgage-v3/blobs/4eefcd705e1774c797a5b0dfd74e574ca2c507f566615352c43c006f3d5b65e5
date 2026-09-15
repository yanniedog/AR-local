import { SECTION_KEYS, type CorePayload, type DetailsPayload, type Manifest, type ProductDetail } from '../types';
import type { CoreIntegrityContext } from './sectionIntegrity';
import { verifiedDetailsSha } from './detailsIdentity';
export function verifiedCatalogueDetails(core: CorePayload | null, integrity: CoreIntegrityContext | null, manifest: Manifest | null, details: DetailsPayload | null): DetailsPayload | null {
  return core && integrity?.core === core && integrity.coreSha256 === manifest?.files.core.sha256 && integrity.runDate === core.run_date &&
    details && details.run_date === core.run_date && core.run_date === manifest?.run_date && verifiedDetailsSha(details) === manifest.files.details.sha256 ? details : null;
}
/** Display only; no family/rate/eligibility authority is derived from these strings. */
export function detailsDisplayIdentity(detail: ProductDetail | null): NonNullable<ProductDetail['displayIdentity']> {
  const value = detail?.displayIdentity;
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !['name', 'provider', 'productCategory'].includes(key))) return {};
  for (const [key, text] of Object.entries(value)) if (typeof text !== 'string' || !text.trim() || [...text].length > (key === 'productCategory' ? 80 : 256)) return {};
  return value;
}
export function detailsOnlyCatalogue(core: CorePayload, details: DetailsPayload) {
  const rated = new Set(SECTION_KEYS.flatMap(section => core.sections[section].rates.map(row => row.product_key)));
  return Object.entries(details.products).filter(([key]) => !rated.has(key)).map(([key, detail]) => ({ key, description: typeof detail.description === 'string' ? detail.description : '', ...detailsDisplayIdentity(detail) })).sort((a, b) => (a.name ?? a.key).localeCompare(b.name ?? b.key));
}
