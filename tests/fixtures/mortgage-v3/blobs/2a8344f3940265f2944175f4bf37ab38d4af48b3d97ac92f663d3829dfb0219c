import { addCalendarMonths, calendarDate, dayNumber } from '../../lib/productTermsEngine/calendar';
import { canonical, hashText } from '../../lib/productTermsEngine/validation';
import type { MortgageSubject } from './types';
export function mortgageDueDates(s: MortgageSubject, anchor: string) {
 const start = dayNumber(s.scope.from), end = dayNumber(s.scope.toExclusive), first = dayNumber(anchor); if (first > start) throw new Error('Mortgage anchor follows opening date');
 const [year, month] = anchor.split('-').map(Number), [ey, em] = s.scope.toExclusive.split('-').map(Number), count = (ey - year) * 12 + em - month;
 if (count > 1200) throw new Error('Mortgage anchor is outside supported calendar');
 const dates: string[] = [];
 for (let n = 0; n <= count; n++) { const date = addCalendarMonths(anchor, n, s.policy.obligationCalendar.monthConvention), d = dayNumber(date); if (d >= end) break; if (d >= start) dates.push(date); }
 if (dates.length > 24) throw new Error('Mortgage obligation limit'); return dates;
}
export function mortgagePostingDates(s: MortgageSubject) {
 const dates: string[] = []; for (let d = dayNumber(s.scope.from); d < dayNumber(s.scope.toExclusive); d++) if (calendarDate(d + 1).slice(8) === '01') dates.push(calendarDate(d)); return dates;
}
export const mortgageObligationId = (s: MortgageSubject, accountId: string, date: string) => hashText(canonical(['mortgage-obligation-v1', s.id, accountId, date]));
