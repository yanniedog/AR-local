import { isValidCalendarDate } from '../lib/calendarDate';
import { validateRevisionHead, type PayloadRevisionHead } from './payloadRevision';

export interface DatesIndex {
  revision_protocol?: 1;
  revision_heads?: Record<string, PayloadRevisionHead>;
  schema_version: number;
  dates: string[];
  count: number;
  min_date: string;
  latest_date: string;
}
/** Parse ``dates-index.json`` from the rolling GitHub release. */
export function parseDatesIndex(raw: unknown, repo = 'yanniedog/AR-local'): DatesIndex | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  if (!Array.isArray(obj.dates)) return null;
  const dates = obj.dates.map((date) => (typeof date === 'string' ? date.slice(0, 10) : ''));
  // Reject the document rather than silently deleting corrupt publication days.
  if (dates.some((date) => !isValidCalendarDate(date))) return null;
  if (!dates.length) return null;
  const sorted = [...new Set(dates)].sort();
  const revisionFields: Pick<DatesIndex, 'revision_protocol' | 'revision_heads'> = {};
  if (obj.revision_protocol != null || obj.revision_heads != null) {
    if (obj.revision_protocol !== 1 || !obj.revision_heads || typeof obj.revision_heads !== 'object' || Array.isArray(obj.revision_heads)) return null;
    try {
      revisionFields.revision_protocol = 1;
      revisionFields.revision_heads = Object.fromEntries(Object.entries(obj.revision_heads).map(([date, head]) => {
        if (!sorted.includes(date)) throw new Error('Revision date is not finalized');
        return [date, validateRevisionHead(head, date, repo)];
      }));
      if (!revisionFields.revision_heads[sorted.at(-1)!]) return null;
    } catch { return null; }
  }
  return {
    ...revisionFields,
    schema_version: typeof obj.schema_version === 'number' ? obj.schema_version : 1,
    dates: sorted,
    count: typeof obj.count === 'number' ? obj.count : sorted.length,
    min_date: typeof obj.min_date === 'string' ? obj.min_date.slice(0, 10) : '2026-05-13',
    latest_date: sorted.at(-1) ?? '',
  };
}
