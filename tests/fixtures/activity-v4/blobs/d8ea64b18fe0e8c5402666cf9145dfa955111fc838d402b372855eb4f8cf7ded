import { utf8ToBytes } from '@noble/hashes/utils';
import { PAYLOAD_REPO } from '../../config';
import type { CorePayload, DetailsPayload, Manifest, ProductDetail, RateRow, SectionKey } from '../../types';
import type { CoreIntegrityContext } from '../sectionIntegrity';
import { verifiedCatalogueDetails } from '../detailsCatalogue';
import { revisionTag } from '../payloadRevision';
import { isValidCalendarDate } from '../../lib/calendarDate';
import { downloadInflate } from '../payload';
import { canonical, hashText } from '../../lib/productTermsEngine/validation';
import { assertEligibilityWire } from './schemaValidation';
import { validateEligibilityAsset } from './validation';
import type { EligibilityApproval, EligibilitySubject } from './types';
export interface EligibilityContext { manifest: Manifest | null; core: CorePayload | null; coreIntegrity: CoreIntegrityContext | null; details: DetailsPayload | null }
export type EligibilityTarget = { kind: 'product'; productKey: string; detail: ProductDetail } | { kind: 'rate_variant'; productKey: string; detail: ProductDetail; section: SectionKey; row: RateRow };
export interface EligibilitySelection { readonly subject: EligibilitySubject; readonly approval: EligibilityApproval; readonly edition: string }
type Descriptor = NonNullable<Manifest['executable_v2']>['index'];
interface Binding { context: EligibilityContext; target: EligibilityTarget; manifestSha256: string; contentSha256: string; indexSha256: string; shardSha256: string; assetSha256: string }
const bindings = new WeakMap<EligibilitySelection, Binding>();
function verifyContext(context: EligibilityContext, target: EligibilityTarget) {
  const { manifest: m, core: c, details: d } = context;
  if (!m?.payload_revision || m.repo !== PAYLOAD_REPO || !c || !d || verifiedCatalogueDetails(c, context.coreIntegrity, m, d) !== d || !Object.hasOwn(d.products, target.productKey) || d.products[target.productKey] !== target.detail || (target.kind === 'rate_variant' && (!c.sections[target.section]?.rates.includes(target.row) || target.row.product_key !== target.productKey))) throw new Error('Eligibility product publication is not verified');
  return { m, c, d };
}
/** Producer bundle preimage: transport URLs and publication envelope fields are excluded. */
export function eligibilityBundleIdentity(m: Manifest) {
  const value = Object.fromEntries(Object.entries(m).filter(([key]) => !['generated_at', 'tag', 'payload_revision', 'files'].includes(key)));
  value.files = Object.fromEntries(Object.entries(m.files).map(([key, file]) => [key, Object.fromEntries(Object.entries(file).filter(([field]) => field !== 'url'))]));
  return hashText(canonical(value));
}
function namespace(m: Manifest) {
  if (utf8ToBytes(JSON.stringify(m)).length > 64 * 1024) throw new Error('Manifest exceeds eligibility limit');
  assertEligibilityWire(m.executable_v2, 'namespace'); const n = m.executable_v2!;
  const r = m.payload_revision;
  if (!r || r.schema_version !== 1 || !Number.isSafeInteger(r.revision) || r.revision < 1 || r.revision > 999999 || !isValidCalendarDate(m.run_date) || m.tag !== revisionTag(m.run_date, r.revision) || !/^[a-f0-9]{64}$/.test(r.bundle_sha256) || typeof r.generation_id !== 'string' || !r.generation_id.trim() || !(r.parent_revision === null || Number.isSafeInteger(r.parent_revision) && r.parent_revision > 0 && r.parent_revision < r.revision)) throw new Error('Immutable release revision invalid');
  const bundle = eligibilityBundleIdentity(m);
  if (r.bundle_sha256 !== bundle || r.generation_id !== `sha256-${bundle}`) throw new Error('Eligibility bundle identity mismatch');
  const legacyNames = Object.values(m.files).map(file => file.name), names = new Set(legacyNames); let bytes = Object.values(m.files).reduce((total, file) => { if (!Number.isSafeInteger(file.bytes) || file.bytes <= 0) throw new Error('Invalid legacy asset bytes'); return total + file.bytes; }, 0);
  if (names.size !== legacyNames.length) throw new Error('Duplicate legacy asset filename');
  for (const [key, descriptor] of [['executable_v2_index', n.index], ...Object.entries(n.shards)] as [string, Descriptor][]) {
    if (descriptor.name !== `${key}-${m.run_date}-${descriptor.sha256.slice(0, 12)}.json.gz` || names.has(descriptor.name)) throw new Error('Eligibility descriptor identity mismatch');
    names.add(descriptor.name); bytes += descriptor.bytes;
  }
  if (bytes > 8 * 1024 * 1024) throw new Error('Eligibility transfer inventory exceeds limit');
  return n;
}
async function acquire(m: Manifest, descriptor: Descriptor) {
  const url = `https://github.com/${PAYLOAD_REPO}/releases/download/${m.tag}/${descriptor.name}`;
  return JSON.parse(await downloadInflate(url, descriptor.sha256, { fileName: descriptor.name, expectedBytes: descriptor.bytes, requireExactBytes: true, maxCompressedBytes: 512 * 1024, maxInflatedBytes: 512 * 1024, allowEncrypted: false }));
}
function envelope(v: any, m: Manifest, kind: 'index' | 'shard') {
  assertEligibilityWire(v, kind);
  if (v.run_date !== m.run_date || v.core_asset_sha256 !== m.files.core.sha256 || v.details_asset_sha256 !== m.files.details.sha256) throw new Error('Eligibility envelope edition mismatch');
}
function verifySubject(s: EligibilitySubject, context: EligibilityContext, target: EligibilityTarget) {
  const { m, c } = verifyContext(context, target);
  if (s.scope.productKey !== target.productKey || s.source.generationId !== m.source_observation?.generation_id || s.source.exportContractSha256 !== m.source_observation?.contract_digest || s.source.productRecordSha256 !== hashText(canonical(target.detail))) throw new Error('Eligibility source association mismatch');
  for (const selected of s.source.rateRows) {
    const row = c.sections[s.scope.family].rates[selected.coreRowIndex];
    if (!row || row.product_key !== target.productKey || row.rate_index !== selected.rateIndex || hashText(canonical(row)) !== selected.rowSha256) throw new Error('Eligibility source variant mismatch');
  }
}
/** Lazy optional namespace only: no eligibility request participates in core adoption. */
export async function loadEligibilitySelections(context: EligibilityContext, target: EligibilityTarget): Promise<EligibilitySelection[]> {
  const { m } = verifyContext(context, target);
  if (Object.keys(m.files).some(key => key.startsWith('executable_v2_'))) throw new Error('Misplaced eligibility descriptors');
  if (!Object.hasOwn(m, 'executable_v2')) return [];
  const n = namespace(m), manifestSha256 = hashText(canonical(m)), index = await acquire(m, n.index); envelope(index, m, 'index');
  if (Object.keys(index.products).some(key => !Object.hasOwn(context.details!.products, key))) throw new Error('Eligibility index product not in verified details');
  const referenced = new Set(Object.values(index.products));
  if (referenced.size !== Object.keys(n.shards).length || [...referenced].some(key => typeof key !== 'string' || !Object.hasOwn(n.shards, key))) throw new Error('Eligibility shard inventory mismatch');
  if (!Object.hasOwn(index.products, target.productKey)) return [];
  const shardDescriptor = n.shards[index.products[target.productKey]], shard = await acquire(m, shardDescriptor); envelope(shard, m, 'shard');
  if (!Object.hasOwn(shard.products, target.productKey)) throw new Error('Eligibility product missing from shard');
  for (const [key, value] of Object.entries(shard.products)) {
    const asset = validateEligibilityAsset(value);
    if (asset.productKey !== key || asset.runDate !== m.run_date || asset.sourceGenerationId !== m.source_observation?.generation_id || asset.coreAssetSha256 !== m.files.core.sha256 || asset.detailsAssetSha256 !== m.files.details.sha256 || index.products[key] !== index.products[target.productKey]) throw new Error('Eligibility product map association mismatch');
    if (!Object.hasOwn(context.details!.products, key)) throw new Error('Eligibility product not in verified details');
    for (const entry of asset.subjects) verifySubject(entry.subject, context, { kind: 'product', productKey: key, detail: context.details!.products[key] });
  }
  const asset = validateEligibilityAsset(shard.products[target.productKey]);
  if (hashText(canonical(m)) !== manifestSha256) throw new Error('Eligibility edition changed');
  return asset.subjects.filter(({ subject: s }) => target.kind === 'product' ? s.scope.coverage === 'product' : s.scope.family === target.section && (s.scope.coverage === 'product' || s.scope.rateIndexes.includes(target.row.rate_index!))).map(({ subject, approval }) => {
    verifySubject(subject, context, target);
    const handle = { subject, approval, edition: m.payload_revision!.bundle_sha256 };
    bindings.set(handle, { context: { ...context }, target: { ...target }, manifestSha256, contentSha256: hashText(canonical(handle)), indexSha256: n.index.sha256, shardSha256: shardDescriptor.sha256, assetSha256: asset.identitySha256 });
    return handle;
  });
}
export function assertEligibilitySelection(selection: EligibilitySelection, context: EligibilityContext, target: EligibilityTarget) {
  const b = bindings.get(selection); verifyContext(context, target);
  if (!b || b.context.core !== context.core || b.context.coreIntegrity !== context.coreIntegrity || b.context.details !== context.details || b.context.manifest !== context.manifest || b.target.kind !== target.kind || b.target.productKey !== target.productKey || b.target.detail !== target.detail || target.kind === 'rate_variant' && (b.target.kind !== 'rate_variant' || b.target.row !== target.row || b.target.section !== target.section) || hashText(canonical(context.manifest)) !== b.manifestSha256 || hashText(canonical(selection)) !== b.contentSha256) throw new Error('Eligibility selection is stale or unverified');
  verifySubject(selection.subject, context, target);
  return { manifestSha256: b.manifestSha256, edition: selection.edition, indexSha256: b.indexSha256, shardSha256: b.shardSha256, assetSha256: b.assetSha256, coreSha256: context.manifest!.files.core.sha256, detailsSha256: context.manifest!.files.details.sha256 };
}
