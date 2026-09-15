import type { Manifest } from '../types';
import { isValidCalendarDate } from '../lib/calendarDate';

export interface PayloadRevisionHead {
  revision: number;
  generation_id: string;
  manifest_url: string;
  manifest_sha256: string;
  bundle_sha256: string;
}

const SHA = /^[a-f0-9]{64}$/;

export function revisionTag(date: string, revision: number): string {
  return `app-payload-${date}-r${String(revision).padStart(6, '0')}`;
}

/** A revision head grants access to one exact immutable GitHub manifest. */
export function validateRevisionHead(value: unknown, date: string, repo: string): PayloadRevisionHead {
  const head = value as PayloadRevisionHead | null;
  if (!isValidCalendarDate(date) || !head || !Number.isSafeInteger(head.revision) || head.revision < 1 ||
      typeof head.generation_id !== 'string' || !head.generation_id ||
      typeof head.manifest_sha256 !== 'string' || !SHA.test(head.manifest_sha256) ||
      typeof head.bundle_sha256 !== 'string' || !SHA.test(head.bundle_sha256) ||
      head.manifest_url !== `https://github.com/${repo}/releases/download/${revisionTag(date, head.revision)}/manifest.json`) {
    throw new Error(`Invalid selected payload revision for ${date}`);
  }
  return head;
}

export function assertRevisionManifest(manifest: Manifest, head: PayloadRevisionHead, date: string, repo: string): void {
  const revision = manifest.payload_revision;
  if (manifest.run_date !== date || manifest.repo !== repo || manifest.tag !== revisionTag(date, head.revision) ||
      revision?.schema_version !== 1 || revision.revision !== head.revision ||
      revision.generation_id !== head.generation_id || revision.bundle_sha256 !== head.bundle_sha256 ||
      !(revision.parent_revision === null || (Number.isSafeInteger(revision.parent_revision) &&
        revision.parent_revision > 0 && revision.parent_revision < revision.revision))) {
    throw new Error('Selected payload manifest binding mismatch');
  }
  const prefix = head.manifest_url.slice(0, -'manifest.json'.length);
  if (!manifest.files?.core || !manifest.files?.details) throw new Error('Revision is missing required assets');
  for (const file of Object.values(manifest.files)) {
    if (!file || typeof file.name !== 'string' || !/^[A-Za-z0-9_.-]+$/.test(file.name) ||
        file.url !== prefix + file.name || !SHA.test(file.sha256) ||
        !Number.isSafeInteger(file.bytes) || file.bytes <= 0 || file.bytes > 64 * 1024 * 1024) {
      throw new Error('Revision asset descriptor is invalid or belongs to another generation');
    }
  }
}

export function assertNoRevisionRollback(installed: Manifest | null | undefined, next: Manifest): void {
  if (!installed?.payload_revision) return;
  if (!next.payload_revision || next.run_date < installed.run_date ||
      (next.run_date === installed.run_date &&
        (next.payload_revision.revision < installed.payload_revision.revision ||
          (next.payload_revision.revision === installed.payload_revision.revision &&
            !samePayloadIdentity(installed, next))))) {
    throw new Error('Selected payload revision is stale; retaining verified data');
  }
}

/** Core equality alone cannot detect corrected product details or sidecars. */
export function samePayloadIdentity(a: Manifest | null | undefined, b: Manifest): boolean {
  if (!a || a.run_date !== b.run_date) return false;
  if (a.payload_revision || b.payload_revision) {
    return !!a.payload_revision && !!b.payload_revision &&
      a.payload_revision.revision === b.payload_revision.revision &&
      a.payload_revision.generation_id === b.payload_revision.generation_id &&
      a.payload_revision.bundle_sha256 === b.payload_revision.bundle_sha256;
  }
  return a.files.core.sha256 === b.files.core.sha256 && a.files.details.sha256 === b.files.details.sha256;
}
