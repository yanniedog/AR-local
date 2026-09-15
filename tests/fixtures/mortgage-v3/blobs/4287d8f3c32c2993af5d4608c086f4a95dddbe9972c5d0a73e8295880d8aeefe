const RUN_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Validate a publication day without letting Date roll impossible dates forward. */
export function isValidCalendarDate(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const match = RUN_DATE_RE.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day;
}
