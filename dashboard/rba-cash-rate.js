/**
 * RBA cash-rate target history — used by chart.js to overlay rate-decision
 * markers on the home-loan ribbon. Source: Reserve Bank of Australia public
 * cash-rate-target schedule.
 *
 * Each entry is the date the new target took effect (the day after the
 * Monetary Policy meeting it was announced) and the new target rate in
 * percentage points. Keep entries sorted ascending by date.
 *
 * When the RBA changes the rate, add the new (date, rate) entry here. The
 * client uses the entry list to render vertical markers and "X.XX% to Y.YY%"
 * tooltips on the ribbon chart.
 */
(function () {
  'use strict';
  window.AR = window.AR || {};

  const ENTRIES = [
    { date: '2022-05-04', rate: 0.35 },
    { date: '2022-06-08', rate: 0.85 },
    { date: '2022-07-06', rate: 1.35 },
    { date: '2022-08-03', rate: 1.85 },
    { date: '2022-09-07', rate: 2.35 },
    { date: '2022-10-05', rate: 2.60 },
    { date: '2022-11-02', rate: 2.85 },
    { date: '2022-12-07', rate: 3.10 },
    { date: '2023-02-08', rate: 3.35 },
    { date: '2023-03-08', rate: 3.60 },
    { date: '2023-05-03', rate: 3.85 },
    { date: '2023-06-07', rate: 4.10 },
    { date: '2023-11-08', rate: 4.35 },
    { date: '2025-02-19', rate: 4.10 },
    { date: '2025-05-21', rate: 3.85 },
    { date: '2025-08-13', rate: 3.60 },
  ];

  function entries() {
    return ENTRIES.slice();
  }

  /**
   * Decisions where the cash rate changed, within [startDate, endDate]
   * inclusive (both YYYY-MM-DD). Returns each entry annotated with the prior
   * rate so consumers can render "from -> to" tooltips.
   */
  function changesWithinWindow(startDate, endDate) {
    if (!Array.isArray(ENTRIES) || !ENTRIES.length) return [];
    const lo = String(startDate || '');
    const hi = String(endDate || '');
    const out = [];
    for (let i = 0; i < ENTRIES.length; i += 1) {
      const entry = ENTRIES[i];
      if (lo && entry.date < lo) continue;
      if (hi && entry.date > hi) continue;
      const prior = i > 0 ? ENTRIES[i - 1].rate : null;
      out.push({ date: entry.date, rate: entry.rate, priorRate: prior });
    }
    return out;
  }

  /** Latest known cash rate target as of (or just before) the given date. */
  function rateAsOf(date) {
    const target = String(date || '');
    let current = null;
    for (let i = 0; i < ENTRIES.length; i += 1) {
      if (!target || ENTRIES[i].date <= target) current = ENTRIES[i].rate;
      else break;
    }
    return current;
  }

  window.AR.rbaCashRate = {
    entries,
    changesWithinWindow,
    rateAsOf,
  };
})();
