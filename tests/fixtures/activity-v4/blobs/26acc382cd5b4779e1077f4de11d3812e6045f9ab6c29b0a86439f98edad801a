import type { DatesIndex } from './datesIndex';
import { isValidCalendarDate } from '../lib/calendarDate';

function verifiedRevision(value: unknown): number | null {
  if (typeof value !== 'string' || value.length >= 512) return null;
  const match = /^revision:([1-9]\d*):[^:]+:[^:]+$/.exec(value);
  const revision = match ? Number(match[1]) : NaN;
  return Number.isSafeInteger(revision) ? revision : null;
}

/** Keep verified revisions even when their values leave the renderable date axis. */
export function historicalRevisionHighWater(...sources: unknown[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const source of sources) {
    if (!source || typeof source !== 'object' || Array.isArray(source)) continue;
    for (const [date, identity] of Object.entries(source)) {
      const revision = verifiedRevision(identity);
      if (!isValidCalendarDate(date) || revision == null) continue;
      // Equal revisions retain the first verified identity, detecting equivocation
      // rather than letting an inconsistent reusable-cache identity replace it.
      if (revision > (verifiedRevision(result[date]) ?? 0)) result[date] = identity as string;
    }
  }
  return result;
}

/** Identity of the selected immutable publication, including terms-only revisions. */
export function historicalSourceIdentity(index: DatesIndex, date: string): string {
  const head = index.revision_heads?.[date];
  return head
    ? `revision:${head.revision}:${head.bundle_sha256}:${head.manifest_sha256}`
    : `legacy:${date}`;
}

/** An older index must never replace an already verified corrected date. */
export function assertHistoricalIdentitiesAdvance(
  index: DatesIndex, dates: string[], existing: Record<string, string> | undefined,
): void {
  for (const date of dates) {
    const previous = existing?.[date];
    const match = previous && /^revision:(\d+):/.exec(previous);
    if (!match) continue;
    const next = index.revision_heads?.[date];
    if (!next || next.revision < Number(match[1]) ||
        (next.revision === Number(match[1]) && historicalSourceIdentity(index, date) !== previous)) {
      throw new Error('Historical publication index is stale; retaining verified history');
    }
  }
}

export function normalizeHistoryIdentities(
  raw: unknown,
  dates: readonly string[],
): Record<string, string> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const values = raw as Record<string, unknown>;
  return Object.fromEntries(dates.flatMap((date) => {
    const value = values[date];
    return typeof value === 'string' && value.length > 0 && value.length < 512
      ? [[date, value]] : [];
  }));
}
