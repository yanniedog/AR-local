/**
 * Mortgage calculator inputs — persisted on the user profile so the calculator
 * remembers the user's situation across sessions, and a real LVR can be computed
 * (not merely chosen) from the values they enter.
 */
export type CalcMode = 'buy' | 'refi';

export interface CalcInputs {
  mode: CalcMode;
  /** Property price (buying) or current property value (refinancing). */
  propertyValue: string;
  /** Buying: deposit/savings going toward the purchase. */
  deposit: string;
  /** Buying: upfront costs (stamp duty + fees) paid from savings, reducing the deposit. */
  costs: string;
  /** Refinancing: current loan balance. */
  loanBalance: string;
  currentRate: string;
  years: string;
  /** Savings/TD section balance (kept here so all calculator inputs persist together). */
  savingsBalance: string;
  /** Mortgage offset: whether the user wants/has an offset account (reveals the field). */
  wantsOffset: boolean;
  /** Expected balance held in the offset account (dollars). */
  offsetBalance: string;
}

export const EMPTY_CALC: CalcInputs = {
  mode: 'buy',
  propertyValue: '',
  deposit: '',
  costs: '',
  loanBalance: '',
  currentRate: '',
  years: '',
  savingsBalance: '',
  wantsOffset: false,
  offsetBalance: '',
};

export function normalizeCalcInputs(value?: Partial<CalcInputs> | null): CalcInputs {
  const str = (v: unknown): string => (typeof v === 'string' ? v : '');
  const mode: CalcMode = value?.mode === 'refi' ? 'refi' : 'buy';
  return {
    mode,
    propertyValue: str(value?.propertyValue),
    deposit: str(value?.deposit),
    costs: str(value?.costs),
    loanBalance: str(value?.loanBalance),
    currentRate: str(value?.currentRate),
    years: str(value?.years),
    savingsBalance: str(value?.savingsBalance),
    wantsOffset: value?.wantsOffset === true,
    offsetBalance: str(value?.offsetBalance),
  };
}

export function num(text: string): number {
  const n = Number(String(text ?? '').replace(/[^0-9.]/g, ''));
  return Number.isFinite(n) ? n : 0;
}

export interface LvrResult {
  /** Computed loan amount in dollars (null when inputs are insufficient). */
  loan: number | null;
  /** Loan-to-value ratio as a percentage (null when inputs are insufficient). */
  lvr: number | null;
  /** Deposit actually applied to the property (buying), after upfront costs. */
  depositApplied: number;
}

/** Compute loan + LVR from the inputs for the active mode. */
export function computeLvr(inputs: CalcInputs): LvrResult {
  const value = num(inputs.propertyValue);
  if (inputs.mode === 'refi') {
    const loan = num(inputs.loanBalance);
    const lvr = value > 0 && loan > 0 ? (loan / value) * 100 : null;
    return { loan: loan > 0 ? loan : null, lvr, depositApplied: 0 };
  }
  const deposit = num(inputs.deposit);
  const costs = num(inputs.costs);
  const depositApplied = Math.max(0, deposit - costs);
  const loan = value > 0 ? Math.max(0, value - depositApplied) : 0;
  const lvr = value > 0 && loan > 0 ? (loan / value) * 100 : null;
  return { loan: value > 0 ? loan : null, lvr, depositApplied };
}

/**
 * Extra deposit needed to bring the LVR to `targetLvrPct` or below, given the
 * property value and the deposit already applied. Returns 0 when already there.
 */
export function depositToReachLvr(
  propertyValue: number,
  depositApplied: number,
  targetLvrPct: number,
): number {
  if (propertyValue <= 0 || targetLvrPct <= 0) return 0;
  const needed = propertyValue * (1 - targetLvrPct / 100);
  return Math.max(0, needed - depositApplied);
}

/** Level monthly repayment (P&I) that amortises `balance` at `annualRate` over
 *  `months`. Rate 0 → straight-line. */
export function monthlyPayment(balance: number, annualRate: number, months: number): number {
  if (months <= 0) return 0;
  const r = annualRate / 12;
  if (r <= 0) return balance / months;
  return (r * balance) / (1 - Math.pow(1 + r, -months));
}

export interface OffsetResult {
  /** Offset applied (clamped to [0, loan]). */
  offset: number;
  /** Interest-bearing balance at the start (loan − offset). */
  effectiveBalance: number;
  /** Months to clear the loan with the offset in place (repayments unchanged). */
  monthsToPayoff: number;
  /** Months saved vs the nominal term. */
  monthsSaved: number;
  /** Total interest over the nominal term with no offset. */
  interestWithout: number;
  /** Total interest paid until payoff with the offset. */
  interestWith: number;
  /** Interest saved by the offset. */
  interestSaved: number;
}

/**
 * Simulate a mortgage offset: repayments stay at the contractual P&I amount, but
 * interest each month is charged only on (balance − offset), so more of every
 * repayment reduces principal and the loan clears sooner. Pure month-by-month
 * amortisation. Returns null when inputs are insufficient.
 */
export function simulateOffset(
  loan: number,
  annualRate: number,
  months: number,
  offset: number,
): OffsetResult | null {
  if (loan <= 0 || annualRate <= 0 || months <= 0) return null;
  const off = Math.max(0, Math.min(offset, loan));
  const payment = monthlyPayment(loan, annualRate, months);
  const r = annualRate / 12;
  let balance = loan;
  let interestWith = 0;
  let m = 0;
  // The contractual payment amortises the full loan in `months`, so with any
  // offset it clears no later — bound the loop at `months` for safety.
  while (balance > 1e-6 && m < months) {
    const interest = Math.max(0, balance - off) * r;
    let principal = payment - interest;
    if (principal <= 0) break; // pathological (rate/term mismatch); leave outstanding
    if (principal > balance) principal = balance;
    interestWith += interest;
    balance -= principal;
    m += 1;
  }
  const monthsToPayoff = balance <= 1e-6 ? m : months;
  const interestWithout = payment * months - loan;
  return {
    offset: off,
    effectiveBalance: Math.max(0, loan - off),
    monthsToPayoff,
    monthsSaved: Math.max(0, months - monthsToPayoff),
    interestWithout,
    interestWith,
    interestSaved: Math.max(0, interestWithout - interestWith),
  };
}
