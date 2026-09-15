import { mortgageSnapshotBudget } from './snapshotBudget';
import { verifiedCoreContents } from '../sectionIntegrity';
import { utf8ToBytes } from '@noble/hashes/utils';
import { PAYLOAD_REPO } from '../../config';
import { verifiedCatalogueDetails } from '../detailsCatalogue';
import { downloadInflate } from '../payload';
import { revisionTag } from '../payloadRevision';
import { isValidCalendarDate } from '../../lib/calendarDate';
import { canonical, hashText } from '../../lib/productTermsEngine/validation';
import { eligibilityBundleIdentity, type EligibilityContext, type EligibilityTarget } from '../eligibilityContracts/transport';
import { assertMonetaryWire } from '../monetaryContracts/schemaValidation';
import { assertMortgageWire } from './schemaValidation';
import { detailsDisplayIdentity } from '../detailsCatalogue';
import { Decimal } from '../../lib/productTermsEngine/decimal';
import { validateMortgageAsset, mortgageBudget } from './validation';
import type { MonetaryDescriptor, MonetaryRouting } from '../monetaryContracts/types';
import type { MortgageSubject, MortgageApproval } from './types';
export type MortgageContext = EligibilityContext;
export type MortgageTarget = EligibilityTarget;
export interface MortgageSelection { readonly subject: MortgageSubject; readonly approval: MortgageApproval; readonly edition: string }
interface Binding { context: MortgageContext; target: MortgageTarget; manifestSha256: string; contentSha256: string; indexSha256: string; shardSha256: string; assetSha256: string }
const bindings = new WeakMap<MortgageSelection, Binding>();
function contextCheck(c: MortgageContext, target: MortgageTarget) {
  const { manifest: m, core, details } = c;
  if (!m || !core || !details || m.repo !== PAYLOAD_REPO || !m.payload_revision || !verifiedCoreContents(c.coreIntegrity) || verifiedCatalogueDetails(core, c.coreIntegrity, m, details) !== details || !Object.hasOwn(details.products, target.productKey) || details.products[target.productKey] !== target.detail || target.kind === 'rate_variant' && (target.section !== 'Mortgage' || !core.sections.Mortgage.rates.includes(target.row) || target.row.product_key !== target.productKey) || detailsDisplayIdentity(target.detail).productCategory !== 'RESIDENTIAL_MORTGAGES') throw new Error('Mortgage product publication is not verified');
  return { m, core, details };
}
function route(c: MortgageContext, target: MortgageTarget) {
  const { m } = contextCheck(c, target);
  if (Object.entries(m.files).some(([key, value]) => /^(monetary|executable)_v3_/.test(key) || /^(monetary|executable)_v3_/.test(value.name))) throw new Error('Misplaced monetary descriptors');
  if (!Object.hasOwn(m, 'executable_v3')) return null;
  if (utf8ToBytes(JSON.stringify(m)).length > 64 * 1024) throw new Error('Monetary manifest size limit'); assertMonetaryWire(m.executable_v3, 'namespace');
  const r = m.payload_revision!, bundle = eligibilityBundleIdentity(m);
  if (!isValidCalendarDate(m.run_date) || r.schema_version !== 1 || !Number.isSafeInteger(r.revision) || r.revision < 1 || r.revision > 999999 || m.tag !== revisionTag(m.run_date, r.revision) || r.bundle_sha256 !== bundle || r.generation_id !== `sha256-${bundle}` || !(r.parent_revision === null || Number.isSafeInteger(r.parent_revision) && r.parent_revision > 0 && r.parent_revision < r.revision)) throw new Error('Monetary immutable revision mismatch');
  const names = new Set<string>(); let bytes = 0;
  function descriptor(d: MonetaryDescriptor, expected?: string) {
    if (!d || typeof d.name !== 'string' || names.has(d.name) || !Number.isSafeInteger(d.bytes) || d.bytes <= 0 || !/^[a-f0-9]{64}$/.test(d.sha256) || expected && d.name !== `${expected}-${m.run_date}-${d.sha256.slice(0,12)}.json.gz`) throw new Error('Monetary descriptor mismatch'); names.add(d.name); bytes += d.bytes;
  }
  Object.values(m.files).forEach(d => descriptor(d));
  if (m.executable_v2) { descriptor(m.executable_v2.index, 'executable_v2_index'); Object.entries(m.executable_v2.shards).forEach(([key, d]) => descriptor(d, key)); }
  for (const [capability, inventory] of Object.entries(m.executable_v3!.capabilities)) {
    descriptor(inventory!.index, `monetary_v3_${capability}_index`); Object.entries(inventory!.shards).forEach(([key, d]) => descriptor(d, key));
  }
  if (bytes > 8 * 1024 * 1024) throw new Error('Shared publication transfer budget exceeded');
  return m.executable_v3!.capabilities.mortgage_calculation ?? null;
}
function routingCheck(r: MonetaryRouting, c: MortgageContext, target: MortgageTarget) {
  // Called synchronously only after the boundary has verified the adopted context.
  const m = c.manifest!;
  if (r.productKey !== target.productKey || r.runDate !== m.run_date || r.coreAssetSha256 !== m.files.core.sha256 || r.detailsAssetSha256 !== m.files.details.sha256 || r.sourceGenerationId !== m.source_observation?.generation_id || r.exportContractSha256 !== m.source_observation?.contract_digest || r.productRecordSha256 !== hashText(canonical(target.detail))) throw new Error('Mortgage routing source association mismatch');
}
async function acquire(c: MortgageContext, d: MonetaryDescriptor, budget: ReturnType<typeof mortgageSnapshotBudget>) {
  const text = await downloadInflate(`https://github.com/${PAYLOAD_REPO}/releases/download/${c.manifest!.tag}/${d.name}`, d.sha256, { fileName: d.name, expectedBytes: d.bytes, requireExactBytes: true, maxCompressedBytes: 512 * 1024, maxInflatedBytes: Math.min(512 * 1024, budget.remaining), allowEncrypted: false }); budget.consume(text); return JSON.parse(text);
}
function envelope(v: any, c: MortgageContext, kind: 'index' | 'shard') { assertMortgageWire(v, kind); if (v.run_date !== c.manifest!.run_date || v.core_asset_sha256 !== c.manifest!.files.core.sha256 || v.details_asset_sha256 !== c.manifest!.files.details.sha256) throw new Error('Monetary envelope edition mismatch'); }
/** Only mortgage assets are fetched. Historical raw members remain producer-private. */
export async function loadMortgageSelections(c: MortgageContext, target: MortgageTarget): Promise<MortgageSelection[]> {
  const inventory = route(c, target); if (!inventory) return [];
  const budget = mortgageSnapshotBudget(c.core, c.details);
  const adoptedCore = c.core, manifestSha256 = hashText(canonical(c.manifest)), index = await acquire(c, inventory.index, budget); envelope(index, c, 'index'); contextCheck(c, target);
  const referenced = new Set(Object.values(index.products));
  if (referenced.size !== Object.keys(inventory.shards).length || [...referenced].some(key => typeof key !== 'string' || !Object.hasOwn(inventory.shards, key)) || Object.keys(index.products).some(key => !Object.hasOwn(c.details!.products, key))) throw new Error('Monetary index inventory mismatch');
  if (!Object.hasOwn(index.products, target.productKey)) return [];
  const shardKey = index.products[target.productKey], d = inventory.shards[shardKey], shard = await acquire(c, d, budget); envelope(shard, c, 'shard'); contextCheck(c, target);
  if (!Object.hasOwn(shard.products, target.productKey)) throw new Error('Mortgage product absent from its shard');
  const assets = Object.entries(shard.products).map(([key, raw]) => {
    const asset = validateMortgageAsset(raw); if (key !== asset.productKey || index.products[key] !== shardKey || !Object.hasOwn(c.details!.products, key)) throw new Error('Monetary product map mismatch');
    routingCheck(asset.routing, c, { kind: 'product', productKey: key, detail: c.details!.products[key] }); return asset;
  });
  mortgageBudget(assets.flatMap(a => a.subjects.map(e => e.subject)));
  if (hashText(canonical(c.manifest)) !== manifestSha256 || c.core !== adoptedCore) throw new Error('Mortgage publication changed');
  const asset = assets.find(a => a.productKey === target.productKey)!;
  return asset.subjects.filter(({ subject }) => targetMatches(subject, c, target)).map(({ subject, approval }) => {
    const handle = { subject, approval, edition: c.manifest!.payload_revision!.bundle_sha256 };
    bindings.set(handle, { context: { ...c }, target: { ...target }, manifestSha256, contentSha256: hashText(canonical(handle)), indexSha256: inventory.index.sha256, shardSha256: d.sha256, assetSha256: asset.identitySha256 }); return handle;
  });
}
export function assertMortgageSelection(selection: MortgageSelection, c: MortgageContext, target: MortgageTarget) {
  const b = bindings.get(selection); contextCheck(c, target); if (!targetMatches(selection.subject, c, target)) throw new Error('Mortgage selected target mismatch');
  if (!b || b.context.manifest !== c.manifest || b.context.core !== c.core || b.context.coreIntegrity !== c.coreIntegrity || b.context.details !== c.details || b.target.kind !== target.kind || b.target.productKey !== target.productKey || b.target.detail !== target.detail || target.kind === 'rate_variant' && (b.target.kind !== 'rate_variant' || b.target.row !== target.row || b.target.section !== target.section) || hashText(canonical(c.manifest)) !== b.manifestSha256 || hashText(canonical(selection)) !== b.contentSha256) throw new Error('Mortgage selection is stale or unverified'); routingCheck(selection.subject.routing, c, target);
  return { manifestSha256: b.manifestSha256, edition: selection.edition, indexSha256: b.indexSha256, shardSha256: b.shardSha256, assetSha256: b.assetSha256, coreSha256: c.manifest!.files.core.sha256, detailsSha256: c.manifest!.files.details.sha256, authorityGraphSha256: selection.subject.authorityGraph.identitySha256 };
}

function targetMatches(s: MortgageSubject, c: MortgageContext, target: MortgageTarget) {
 if (s.target.kind !== target.kind) return false;
 if (s.target.kind === 'product') return true;
 if (target.kind !== 'rate_variant') return false;
 return target.section === 'Mortgage' && c.core!.sections.Mortgage.rates.indexOf(target.row) === s.target.coreRowIndex && target.row.rate_index === s.target.rateIndex && hashText(canonical(target.row)) === s.target.rowSha256 && Decimal.parse(String(target.row.rate)).compare(Decimal.parse(s.target.annualRate)) === 0 && Decimal.parse(s.target.annualRate).compare(Decimal.parse(s.policy.annualRate)) === 0;
}

