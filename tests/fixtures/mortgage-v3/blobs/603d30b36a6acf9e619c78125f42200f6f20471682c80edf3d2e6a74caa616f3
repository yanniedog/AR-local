import type { ISODate } from './types';
const DAY = 86_400_000;
export function dayNumber(value: ISODate): number {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error('invalid_calendar_date');
  const [year, month, day] = value.split('-').map(Number);
  if (year < 1900 || year > 2200) throw new Error('calendar_year_unsupported');
  const result = Date.UTC(year, month - 1, day);
  if (new Date(result).toISOString().slice(0, 10) !== value) throw new Error('invalid_calendar_date');
  return result / DAY;
}
export function calendarDate(day: number): ISODate { return new Date(day * DAY).toISOString().slice(0, 10); }
export function isLeapYear(year: number): boolean { return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0); }
export function addCalendarMonths(value: ISODate, months: number, convention: 'clamp' | 'preserve_month_end'): ISODate {
  dayNumber(value);
  if (!Number.isInteger(months) || Math.abs(months) > 1200) throw new Error('calendar_month_count_unsupported');
  if (!['clamp', 'preserve_month_end'].includes(convention)) throw new Error('calendar_convention_unsupported');
  const [year, month, day] = value.split('-').map(Number);
  const oldEnd = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const target = new Date(Date.UTC(year, month - 1 + months, 1));
  const newEnd = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  const chosen = convention === 'preserve_month_end' && day === oldEnd ? newEnd : Math.min(day, newEnd);
  const result = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth(), chosen)).toISOString().slice(0, 10);
  dayNumber(result);
  return result;
}
