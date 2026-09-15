import { calendarDate, dayNumber } from './calendar';
import type { TdBusinessCalendar, TdLifecycle, TdSchedule } from './tdTypes';

/** No substitute national calendar or guessed holidays. Coverage must include the resolved date. */
export function nextTdBusinessDay(date: string, calendar: TdBusinessCalendar | null): string | null {
  if (!calendar) return null;
  for (let n = dayNumber(date), attempts = 0; attempts < 370; n++, attempts++) {
    const current = calendarDate(n);
    if (current < calendar.from || current >= calendar.toExclusive) return null;
    const weekday = new Date(n * 86400000).getUTCDay();
    if (weekday !== 0 && weekday !== 6 && !calendar.holidays.includes(current)) return current;
  }
  return null;
}
export function tdSchedule(td: TdLifecycle): TdSchedule {
  const issues: string[] = [];
  const resolve = (date: string) => td.mode === 'legacy_noncompounding' ? nextTdBusinessDay(date, td.calendar) : date;
  const maturity = resolve(td.nominalMaturityDate);
  if (!maturity) issues.push('td_business_calendar_unknown');
  let closure = td.closure.confirmedDate;
  if (td.closure.kind === 'hardship' || td.closure.kind === 'rollover') {
    issues.push(`td_${td.closure.kind}_unsupported`); closure = null;
  } else if (td.closure.kind === 'maturity') {
    if (closure && maturity && closure !== maturity) throw new Error('td_confirmed_maturity_mismatch');
    closure = maturity && closure ? closure : null;
  } else {
    const accepted = td.closure.acceptedNoticeDate;
    if (!accepted) { issues.push('td_notice_acceptance_unknown'); closure = null; }
    else if (dayNumber(td.nominalMaturityDate) - dayNumber(accepted) < 31 ||
        (td.mode === 'legacy_noncompounding' && td.term.unit === 'months' && td.term.count === 1)) throw new Error('td_notice_inside_final_period');
    else if (closure && (dayNumber(closure) - dayNumber(accepted) < 31 || (maturity && closure > maturity))) throw new Error('td_notice_closure_invalid');
  }
  if (!closure) issues.push('td_closure_unconfirmed');
  const postingDates: string[] = [];
  for (const periodEnd of td.payments.periodEnds) {
    const date = resolve(periodEnd);
    if (!date) issues.push('td_posting_calendar_unknown');
    else if (closure && date < closure) postingDates.push(date);
  }
  const accrualToExclusive = td.mode === 'digital_notice_no_interest' && td.closure.kind === 'early_notice'
    ? td.closure.acceptedNoticeDate : closure;
  if (!td.roundingReviewed) issues.push('td_rounding_unreviewed');
  if (td.payments.destination === 'unknown') issues.push('td_payment_destination_unknown');
  if (td.taxTreatment !== 'none_confirmed') issues.push('td_tax_treatment_unknown');
  if (td.closure.feeDecision === 'unknown') issues.push('td_break_fee_decision_unknown');
  return { maturity, closure, accrualToExclusive, postingDates, issues };
}
