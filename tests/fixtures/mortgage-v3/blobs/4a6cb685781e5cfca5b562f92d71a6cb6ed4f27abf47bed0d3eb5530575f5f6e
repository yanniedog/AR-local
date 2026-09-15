import type { RbaEntry, SectionKey } from '../types';
import { SECTION_KEYS } from '../types';
import { parseYmd } from './bankHistoryTransform';
import type { RbaCalendar, RbaDecisionEntry } from './rbaCalendar';
import {
  DAY_MS,
  FOLLOW_DIRS,
  type BankInsightsPayload,
  type BankRateEvent,
} from './bankInsightsTypes';

export interface RbaDecisionRef {
  date: string;
  /** Decision size in basis points (negative = cut). */
  bps: number;
  outcome: 'hike' | 'cut';
  /** Cash-rate target after the decision, percent — when known. */
  rate?: number;
  /**
   * Announcement predates the bank-history ledger start, so first-move timing may
   * miss earlier responses and days-to-follow is an upper bound on observed delay.
   */
  partialObservation: boolean;
}

export interface RbaResponseWindowRef {
  decision: RbaDecisionRef;
  windowEnd: string;
  windowDays: number;
  windowOpen: boolean;
  tracked: boolean;
}

export type PassThroughStatus = 'full' | 'partial' | 'none' | 'over' | 'unscored';

export interface PassThroughRow {
  provider: string;
  /**
   * Same-direction change in the provider median over the response window, in
   * basis points (signed). This intentionally does not sum daily event averages:
   * doing so double-counts product churn and can manufacture implausible totals.
   */
  passedBps: number;
  /** Net provider-median change, including a move opposite the RBA direction. */
  netChangeBps?: number;
  /** Days from the decision date to the provider's first matching move, if any. */
  daysToFirstMove: number | null;
  /** |passedBps| / |decision bps|; null when decision bps is 0 or no move. */
  ratio: number | null;
  /** False when the decision predates the ledger and no pre-decision baseline exists. */
  baselineComplete?: boolean;
  /**
   * True when this lender has an observation on the final tracked ledger date
   * in the window. Closed-window tendencies must not treat an earlier last
   * value as evidence that the lender chose not to respond.
   */
  windowEndComplete?: boolean;
  passStatus: PassThroughStatus;
}

export interface PassThroughModel {
  decision: RbaDecisionRef;
  rows: PassThroughRow[];
  /** Observed response-window span in days (at least one for chart layout). */
  windowDays: number;
  /** Inclusive observed end: day before the next rate change, or latest tracked day. */
  windowEnd: string;
  /** Latest bank-history day available for observation. */
  observedThrough: string;
  /** True when the response window still extends past observedThrough. */
  windowOpen: boolean;
}

export interface MultiSectionPassThroughRow {
  provider: string;
  sections: Partial<Record<SectionKey, PassThroughRow>>;
}

export interface MultiSectionPassThroughModel {
  decision: RbaDecisionRef;
  rows: MultiSectionPassThroughRow[];
  windowDays: number;
  windowEnd: string;
  observedThrough: string;
  windowOpen: boolean;
}

export interface PassThroughOpts {
  /** Prefer announcement-dated calendar decisions when present. */
  calendar?: RbaCalendar | null;
  /** Score this announcement date instead of the latest scorable decision. */
  decisionDate?: string;
  section?: SectionKey;
}

function ymdFromUtcMs(ms: number): string | null {
  if (!Number.isFinite(ms)) return null;
  try {
    return new Date(ms).toISOString().slice(0, 10);
  } catch {
    return null;
  }
}

function addDaysYmd(ymd: string, days: number): string | null {
  const ts = parseYmd(ymd);
  if (ts == null || !Number.isFinite(ts)) return null;
  return ymdFromUtcMs(ts + days * DAY_MS);
}

function daysBetweenYmd(from: string, to: string): number | null {
  const a = parseYmd(from);
  const b = parseYmd(to);
  if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b)) return null;
  return Math.round((b - a) / DAY_MS);
}

function passStatusFor(passedBps: number, decisionBps: number): PassThroughStatus {
  if (passedBps === 0 || decisionBps === 0) return 'none';
  // Same-direction only (callers already filter, but guard against misuse).
  if (Math.sign(passedBps) !== Math.sign(decisionBps)) return 'none';
  const ratio = Math.abs(passedBps) / Math.abs(decisionBps);
  if (ratio >= 1.0001) return 'over';
  if (ratio >= 0.999) return 'full';
  return 'partial';
}

function windowEndForDecision(
  decision: Pick<PassThroughSourceDecision, 'date'>,
  rateChangeDates: readonly string[],
  observedThrough: string,
): { windowEnd: string; windowOpen: boolean } | null {
  const nextDate = rateChangeDates.find((date) => date > decision.date);
  if (nextDate) {
    const dayBeforeNext = addDaysYmd(nextDate, -1);
    if (!dayBeforeNext) return null;
    return {
      windowEnd: dayBeforeNext,
      windowOpen: observedThrough < dayBeforeNext,
    };
  }
  return parseYmd(observedThrough)
    ? { windowEnd: observedThrough, windowOpen: true }
    : null;
}

export interface PassThroughSourceDecision {
  date: string;
  bps: number;
  outcome: 'hike' | 'cut';
  rate?: number;
  /** Cash-rate effective date when known (calendar announcements only). */
  effective?: string | null;
}

/** Derive hike/cut steps from the core cash-rate series (effective dates). */
export function decisionsFromRbaSeries(
  rba: RbaEntry[] | null | undefined,
): PassThroughSourceDecision[] {
  if (!rba?.length) return [];
  // Live payloads are chronological; sort defensively so a shuffled series cannot
  // invent bogus steps or drop real ones.
  const series = rba
    .map((e) => ({ date: String(e.date || '').slice(0, 10), rate: e.rate }))
    .filter((e) => parseYmd(e.date) && Number.isFinite(e.rate))
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const out: PassThroughSourceDecision[] = [];
  for (let i = 1; i < series.length; i += 1) {
    const { rate: prior } = series[i - 1];
    const { rate, date } = series[i];
    if (rate === prior) continue;
    const bps = Math.round((rate - prior) * 100);
    if (bps === 0) continue;
    out.push({
      date,
      bps,
      outcome: bps > 0 ? 'hike' : 'cut',
      rate,
    });
  }
  return out;
}

/** Prefer calendar hike/cut entries; fall back to the cash-rate series. */
function calendarPassThroughDecisions(
  calendar?: RbaCalendar | null,
): PassThroughSourceDecision[] {
  return (
    calendar?.decisions
      ?.filter((d): d is RbaDecisionEntry & { outcome: 'hike' | 'cut' } =>
        (FOLLOW_DIRS as readonly string[]).includes(d.outcome),
      )
      .map((d) => ({
        date: d.date,
        // Calendar may store cut magnitude as positive with outcome:'cut'.
        bps: d.outcome === 'cut' ? -Math.abs(d.delta_bps) : Math.abs(d.delta_bps),
        outcome: d.outcome,
        rate: d.rate,
        effective: d.effective,
      })) ?? []
  );
}

function rateChangeBoundaryDates(
  calendar: RbaCalendar | null | undefined,
  fallback: readonly PassThroughSourceDecision[],
): string[] {
  const fromCalendar = calendar?.decisions
    ?.filter((decision) => decision.outcome === 'hike' || decision.outcome === 'cut')
    ?.map((decision) => decision.date)
    .filter((date) => !!parseYmd(date));
  return [...new Set([
    ...(fromCalendar ?? []),
    ...fallback.map((decision) => decision.date),
  ])]
    .sort();
}

/** True when a core.rba step is the same RBA move as a calendar announcement. */
function isCalendarEffectiveTwin(
  seriesDecision: PassThroughSourceDecision,
  calendarDecisions: PassThroughSourceDecision[],
): boolean {
  return calendarDecisions.some((cal) => {
    if (cal.outcome !== seriesDecision.outcome || Math.abs(cal.bps) !== Math.abs(seriesDecision.bps)) {
      return false;
    }
    // Same calendar key (announcement) — defensive if merge bounds ever change.
    if (cal.date === seriesDecision.date) return true;
    if (cal.effective && cal.effective === seriesDecision.date) return true;
    // Fallback when effective is missing: same-size move the day after announcement.
    if (!cal.effective) {
      const dayAfter = addDaysYmd(cal.date, 1);
      return dayAfter != null && dayAfter === seriesDecision.date;
    }
    return false;
  });
}

export function resolvePassThroughDecisions(
  rba: RbaEntry[] | null | undefined,
  calendar?: RbaCalendar | null,
): PassThroughSourceDecision[] {
  const fromCal = calendarPassThroughDecisions(calendar);
  if (fromCal.length) return fromCal;
  return decisionsFromRbaSeries(rba);
}

function scoreDecisionsAgainstLedger(
  decisions: PassThroughSourceDecision[],
  rateChangeDates: readonly string[],
  ledgerStart: string,
  ledgerEnd: string,
): RbaDecisionRef[] {
  const scored: RbaDecisionRef[] = [];
  for (let i = 0; i < decisions.length; i += 1) {
    const dec = decisions[i];
    if (!(FOLLOW_DIRS as readonly string[]).includes(dec.outcome)) continue;
    const window = windowEndForDecision(dec, rateChangeDates, ledgerEnd);
    if (!window) continue;
    // Response window must overlap the ledger; announcement must not be after ledger end.
    if (window.windowEnd < ledgerStart || dec.date > ledgerEnd) continue;
    scored.push({
      date: dec.date,
      bps: dec.bps,
      outcome: dec.outcome,
      rate: dec.rate,
      partialObservation: dec.date < ledgerStart,
    });
  }
  return scored;
}

/**
 * Hike/cut decisions whose response window overlaps the bank-history ledger.
 * Includes decisions that slightly predate ledger start when follow-on moves are
 * still observable inside the ingest window (marked partialObservation).
 */
export function scorablePassThroughDecisions(
  payload: BankInsightsPayload | null | undefined,
  rba: RbaEntry[] | null | undefined,
  opts: PassThroughOpts = {},
): RbaDecisionRef[] {
  if (!payload?.run_dates?.length) return [];
  const ledgerStart = payload.run_dates[0];
  const ledgerEnd = payload.run_date || payload.run_dates[payload.run_dates.length - 1];
  if (!parseYmd(ledgerStart) || !parseYmd(ledgerEnd)) return [];

  const fromCal = calendarPassThroughDecisions(opts.calendar);
  const fromSeries = decisionsFromRbaSeries(rba);
  const seriesOnly = fromSeries.filter((decision) => !isCalendarEffectiveTwin(decision, fromCal));
  const primary = fromCal.length ? fromCal : fromSeries;
  if (!primary.length) return [];
  // Even when the calendar is the preferred decision source, its payload may
  // lag a newer core series step. Every scoring path must share that later
  // policy boundary so an older response window cannot remain open through it.
  const boundaries = rateChangeBoundaryDates(opts.calendar, seriesOnly);

  let scored = scoreDecisionsAgainstLedger(primary, boundaries, ledgerStart, ledgerEnd);
  // A partial or stale calendar can omit older or newer core.rba decisions.
  // Merge every non-twin series decision so the scoreable set stays identical
  // to the window chronology instead of supporting only the newest additions.
  // Skip effective-date twins: live core.rba steps on effective dates while the
  // calendar keys announcements (typically announcement+1).
  if (fromCal.length && fromSeries.length) {
    const seriesScored = scoreDecisionsAgainstLedger(
      fromSeries,
      boundaries,
      ledgerStart,
      ledgerEnd,
    );
    if (seriesScored.length) {
      const byDate = new Map(scored.map((d) => [d.date, d]));
      for (const d of seriesScored) {
        if (!isCalendarEffectiveTwin(d, fromCal)) byDate.set(d.date, d);
      }
      scored = [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
    }
  }
  return scored;
}

/**
 * Every known hike/cut window up to the latest tracked bank day, newest first.
 * Windows without overlapping bank history remain navigable and are marked
 * untracked instead of disappearing from the chronology.
 */
export function rbaResponseWindowList(
  payload: BankInsightsPayload | null | undefined,
  rba: RbaEntry[] | null | undefined,
  opts: Pick<PassThroughOpts, 'calendar'> = {},
): RbaResponseWindowRef[] {
  if (!payload?.run_dates?.length) return [];
  const observedThrough = payload.run_date || payload.run_dates[payload.run_dates.length - 1];
  const ledgerStart = payload.run_dates[0];
  if (!parseYmd(observedThrough) || !parseYmd(ledgerStart)) return [];
  const calendarDecisions = calendarPassThroughDecisions(opts.calendar);
  const seriesDecisions = decisionsFromRbaSeries(rba);
  const seriesOnly = seriesDecisions.filter(
    (decision) => !isCalendarEffectiveTwin(decision, calendarDecisions),
  );
  const primary = calendarDecisions.length ? calendarDecisions : seriesDecisions;
  const merged = new Map(primary.map((decision) => [decision.date, decision]));
  for (const decision of seriesOnly) merged.set(decision.date, decision);
  const decisions = [...merged.values()]
    .filter((decision) => decision.date <= observedThrough)
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const changeDates = decisions.map((decision) => decision.date);
  return decisions.map((decision) => {
    const window = windowEndForDecision(decision, changeDates, observedThrough)!;
    const span = daysBetweenYmd(decision.date, window.windowEnd) ?? 0;
    return {
      decision: {
        date: decision.date,
        bps: decision.bps,
        outcome: decision.outcome,
        rate: decision.rate,
        partialObservation: decision.date < ledgerStart,
      },
      windowEnd: window.windowEnd,
      windowDays: Math.max(1, span),
      windowOpen: window.windowOpen,
      tracked: window.windowEnd >= ledgerStart,
    };
  }).reverse();
}

const PASS_STATUS_RANK: Record<PassThroughStatus, number> = {
  over: 0,
  full: 1,
  partial: 2,
  unscored: 3,
  none: 4,
};

/** Events remain the most precise source for first-observed timing. */
function firstMatchingMoveDate(
  events: BankRateEvent[],
  provider: string,
  section: SectionKey,
  decision: RbaDecisionRef,
  windowEnd: string,
): string | null {
  const wantSign = Math.sign(decision.bps);
  let first: string | null = null;
  for (const event of events) {
    if (event.provider !== provider || event.section !== section) continue;
    if (event.date < decision.date || event.date > windowEnd) continue;
    const matches =
      event.dir === decision.outcome ||
      (event.dir === 'mixed' && Math.sign(event.avg_bps) === wantSign);
    if (matches && (!first || event.date < first)) first = event.date;
  }
  return first;
}

/** Rank full/fast passers above holdouts so leaderboards match user trust. */
export function comparePassThroughRows(a: PassThroughRow, b: PassThroughRow): number {
  const byStatus = PASS_STATUS_RANK[a.passStatus] - PASS_STATUS_RANK[b.passStatus];
  if (byStatus !== 0) return byStatus;
  const aDays = a.daysToFirstMove;
  const bDays = b.daysToFirstMove;
  if (aDays != null && bDays != null && aDays !== bDays) return aDays - bDays;
  if (aDays != null && bDays == null) return -1;
  if (aDays == null && bDays != null) return 1;
  const bySize = Math.abs(b.passedBps) - Math.abs(a.passedBps);
  if (bySize !== 0) return bySize;
  return a.provider.localeCompare(b.provider);
}

/**
 * Human label for days-to-first-move.
 * Partial observation uses ≤ because earlier (pre-ledger) responses may be missing.
 */
export function passThroughDaysLabel(
  daysToFirstMove: number | null,
  opts: { partialObservation: boolean; windowOpen: boolean },
): string {
  if (daysToFirstMove == null) {
    return opts.windowOpen
      ? 'no matching move yet — window still open'
      : 'no matching move in the tracking window';
  }
  const unit = daysToFirstMove === 1 ? 'day' : 'days';
  if (opts.partialObservation) return `moved after ≤${daysToFirstMove} ${unit}`;
  return `moved after ${daysToFirstMove} ${unit}`;
}

/** True when the lender had a rate to respond from for this decision. */
function lenderObservableAtDecision(
  payload: BankInsightsPayload,
  provider: string,
  section: SectionKey,
  decisionDate: string,
): boolean {
  const series = payload.banks[provider]?.[section];
  if (!series) return false;
  let firstIdx = -1;
  for (let i = 0; i < payload.run_dates.length; i += 1) {
    if (series.median[i] != null || series.best[i] != null) {
      firstIdx = i;
      break;
    }
  }
  if (firstIdx < 0) return false;
  const firstDate = payload.run_dates[firstIdx];
  if (firstDate <= decisionDate) return true;
  // Decision predates the ledger: lenders present from the first ingest day are
  // still in-universe (partialObservation); late-join series are not.
  return payload.run_dates[0] > decisionDate && firstIdx === 0;
}

function buildPassThroughRows(
  payload: BankInsightsPayload,
  decision: RbaDecisionRef,
  windowEnd: string,
  section: SectionKey,
): PassThroughRow[] {
  const rows: PassThroughRow[] = [];
  let requiredEndIndex = -1;
  for (let i = 0; i < payload.run_dates.length; i += 1) {
    if (payload.run_dates[i] > windowEnd) break;
    requiredEndIndex = i;
  }
  for (const [provider, sections] of Object.entries(payload.banks)) {
    const sectionSeries = sections[section];
    if (!sectionSeries) continue;
    if (!lenderObservableAtDecision(payload, provider, section, decision.date)) continue;

    // Prefer the provider median because it keeps a stable unit across days and
    // is far less sensitive than event averages to products entering/leaving the
    // CDR feed. Fall back to best only for a legacy series without any medians.
    const values = sectionSeries.median.some((v) => v != null)
      ? sectionSeries.median
      : sectionSeries.best;
    let baselineIndex = -1;
    for (let i = 0; i < payload.run_dates.length; i += 1) {
      if (payload.run_dates[i] > decision.date) break;
      if (values[i] != null) baselineIndex = i;
    }
    const baselineComplete = baselineIndex >= 0;
    if (baselineIndex < 0 && decision.partialObservation) {
      baselineIndex = values.findIndex((v, i) => v != null && payload.run_dates[i] <= windowEnd);
    }
    const baseline = baselineIndex >= 0 ? values[baselineIndex] : null;
    if (baseline == null) continue;

    let final = baseline;
    let finalObservationIndex = baselineIndex;
    const wantSign = Math.sign(decision.bps);
    for (let i = baselineIndex + 1; i < payload.run_dates.length; i += 1) {
      const date = payload.run_dates[i];
      if (date > windowEnd) break;
      const value = values[i];
      if (value == null) continue;
      final = value;
      finalObservationIndex = i;
    }

    const netChangeBps = Math.round((final - baseline) * 10000 * 10) / 10;
    const passedBps = Math.sign(netChangeBps) === wantSign ? netChangeBps : 0;
    // Timing and final movement must describe the same response. A lender can
    // briefly move with the RBA and finish the window unchanged or opposite;
    // presenting that early event as its response speed is contradictory.
    const firstMatchingDate = passedBps !== 0
      ? firstMatchingMoveDate(payload.events, provider, section, decision, windowEnd)
      : null;
    const absDecision = Math.abs(decision.bps);
    const ratio =
      baselineComplete && passedBps !== 0 && absDecision > 0
        ? Math.round((Math.abs(passedBps) / absDecision) * 1000) / 1000
        : null;
    rows.push({
      provider,
      passedBps,
      netChangeBps,
      daysToFirstMove: firstMatchingDate
        ? daysBetweenYmd(decision.date, firstMatchingDate)
        : null,
      ratio,
      baselineComplete,
      windowEndComplete:
        requiredEndIndex >= 0 && finalObservationIndex === requiredEndIndex,
      passStatus: baselineComplete ? passStatusFor(passedBps, decision.bps) : 'unscored',
    });
  }
  rows.sort(comparePassThroughRows);
  return rows;
}

interface PassThroughDecisionContext {
  decision: RbaDecisionRef;
  windowDays: number;
  windowEnd: string;
  observedThrough: string;
  observeEnd: string;
  windowOpen: boolean;
}

function resolvePassThroughDecisionContext(
  payload: BankInsightsPayload,
  rba: RbaEntry[] | null | undefined,
  opts: PassThroughOpts,
): PassThroughDecisionContext | null {
  const scorable = scorablePassThroughDecisions(payload, rba, opts);
  if (!scorable.length) return null;

  const decision = opts.decisionDate
    ? scorable.find((d) => d.date === opts.decisionDate)
    : scorable[scorable.length - 1];
  if (!decision) return null;

  const calendarDecisions = calendarPassThroughDecisions(opts.calendar);
  const seriesOnly = decisionsFromRbaSeries(rba).filter(
    (seriesDecision) => !isCalendarEffectiveTwin(seriesDecision, calendarDecisions),
  );
  const observedThrough =
    payload.run_date || payload.run_dates[payload.run_dates.length - 1];
  const window = windowEndForDecision(
    decision,
    rateChangeBoundaryDates(opts.calendar, seriesOnly),
    observedThrough,
  );
  if (!window) return null;

  const observeEnd = window.windowEnd < observedThrough ? window.windowEnd : observedThrough;
  const elapsedDays = daysBetweenYmd(decision.date, observeEnd);
  return {
    decision,
    windowDays: Math.max(1, elapsedDays ?? 1),
    windowEnd: window.windowEnd,
    observedThrough,
    observeEnd,
    windowOpen: window.windowOpen,
  };
}

/**
 * Score how each lender's section rates followed an RBA hike/cut whose response
 * window overlaps the bank-history ledger. Defaults to the latest scorable
 * decision; pass `decisionDate` / `calendar` to browse past decisions.
 */
export function rbaPassThrough(
  payload: BankInsightsPayload | null | undefined,
  rba: RbaEntry[] | null | undefined,
  opts: PassThroughOpts = {},
): PassThroughModel | null {
  if (!payload?.run_dates?.length) return null;
  const section = opts.section ?? 'Mortgage';
  const ctx = resolvePassThroughDecisionContext(payload, rba, opts);
  if (!ctx) return null;
  const rows = buildPassThroughRows(payload, ctx.decision, ctx.observeEnd, section);
  if (!rows.length) return null;
  return {
    decision: ctx.decision,
    rows,
    windowDays: ctx.windowDays,
    windowEnd: ctx.windowEnd,
    observedThrough: ctx.observedThrough,
    windowOpen: ctx.windowOpen,
  };
}

/**
 * Per-lender pass-through for Mortgage, Savings, and TD in one directory.
 * Providers are sorted A–Z; missing sections are omitted from `sections`.
 */
export function rbaPassThroughMultiSection(
  payload: BankInsightsPayload | null | undefined,
  rba: RbaEntry[] | null | undefined,
  opts: PassThroughOpts = {},
): MultiSectionPassThroughModel | null {
  if (!payload?.run_dates?.length) return null;
  const ctx = resolvePassThroughDecisionContext(payload, rba, opts);
  if (!ctx) return null;

  const sectionRows = SECTION_KEYS.map((section) => ({
    section,
    rows: buildPassThroughRows(payload, ctx.decision, ctx.observeEnd, section),
  }));
  const providers = new Set<string>();
  for (const { rows } of sectionRows) {
    for (const row of rows) providers.add(row.provider);
  }
  if (!providers.size) return null;

  const rowsBySection = new Map(
    sectionRows.map(({ section, rows }) => [section, new Map(rows.map((row) => [row.provider, row]))]),
  );
  const rows: MultiSectionPassThroughRow[] = [...providers]
    .sort((a, b) => a.localeCompare(b))
    .map((provider) => {
      const sections: Partial<Record<SectionKey, PassThroughRow>> = {};
      for (const { section } of sectionRows) {
        const row = rowsBySection.get(section)?.get(provider);
        if (row) sections[section] = row;
      }
      return { provider, sections };
    });

  return {
    decision: ctx.decision,
    rows,
    windowDays: ctx.windowDays,
    windowEnd: ctx.windowEnd,
    observedThrough: ctx.observedThrough,
    windowOpen: ctx.windowOpen,
  };
}

/** Newest-first list of scorable pass-through decisions for UI pickers. */
export function rbaPassThroughDecisionList(
  payload: BankInsightsPayload | null | undefined,
  rba: RbaEntry[] | null | undefined,
  opts: PassThroughOpts = {},
): RbaDecisionRef[] {
  return scorablePassThroughDecisions(payload, rba, opts).slice().reverse();
}
