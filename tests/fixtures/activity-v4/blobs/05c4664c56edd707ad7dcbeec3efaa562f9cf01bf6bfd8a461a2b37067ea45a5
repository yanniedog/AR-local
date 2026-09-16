import { addCalendarMonths, calendarDate, dayNumber } from './calendar';
import type { FeeDefinition, FeeOccurrence, FeeSchedule } from './feeTypes';
import { hashText } from './validation';

export function feeOccurrences(schedule: FeeSchedule): FeeOccurrence[] {
  const result: FeeOccurrence[] = [];
  for (const fee of schedule.fees) {
    const push = (incurredDate: string, dueDate: string, triggerId: string) => {
      if (result.length >= 10000) throw new Error('fee_occurrence_limit');
      const scope = fee.scope.type === 'account' ? fee.scope.accountId : fee.scope.packageInstanceId;
      const id = `fee:${hashText(JSON.stringify([fee.chargeIdentity, fee.scope.type, scope, triggerId]))}`;
      result.push({ id, fee, incurredDate, dueDate, triggerId });
    };
    const timing = fee.timing;
    if (timing.type === 'dated') timing.occurrences.forEach(o => push(o.incurredDate, o.dueDate, o.triggerId));
    else if (timing.calendarAdjustment === 'none' && timing.settlement === 'same_day') {
      for (let n = 0; n < 18301; n++) {
        if (timing.unit === 'months') {
          const [year, month] = timing.anchor.split('-').map(Number);
          const [endYear, endMonth] = timing.toExclusive.split('-').map(Number);
          if (year * 12 + month - 1 + n * timing.step > endYear * 12 + endMonth - 1) break;
        } else if (dayNumber(timing.anchor) + n * timing.step >= dayNumber(timing.toExclusive)) break;
        const date = timing.unit === 'days' ? calendarDate(dayNumber(timing.anchor) + n * timing.step) : addCalendarMonths(timing.anchor, n * timing.step, timing.monthConvention);
        if (date >= timing.toExclusive) break;
        if (date >= timing.from) push(date, date, date);
      }
    }
  }
  return result.sort((a, b) => a.dueDate.localeCompare(b.dueDate) || a.fee.order - b.fee.order);
}
export function feeDebitsAccount(fee: FeeDefinition, accountId: string): boolean {
  return fee.scope.type === 'account' ? fee.scope.accountId === accountId : fee.scope.debtorAccountId === accountId;
}
