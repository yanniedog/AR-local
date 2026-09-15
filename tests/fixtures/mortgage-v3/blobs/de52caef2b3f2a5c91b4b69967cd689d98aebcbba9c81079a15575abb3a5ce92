import type { CalculationReceipt } from './types';

export interface AccountMovement {
  id: string;
  delta: string;
  evidenceIds: string[];
  order: number;
  status: 'cleared' | 'projected';
  loan?: { type: 'payment' | 'extra_payment' | 'redraw'; obligationId?: string };
}
export interface AccountDay {
  phase: 'start' | 'end';
  date: string;
  balance: string;
  receipt: CalculationReceipt;
}
export type AccountPort = Generator<AccountDay, CalculationReceipt, AccountMovement[]>;
/** Single-account callers supply no portfolio movements; arithmetic uses the same runner. */
export function finishAccount(port: AccountPort): CalculationReceipt {
  let next = port.next();
  while (!next.done) next = port.next([]);
  return next.value;
}
