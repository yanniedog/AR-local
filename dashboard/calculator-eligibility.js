(function (root, factory) {
  'use strict';
  const api = factory();
  root.AR = root.AR || {};
  root.AR.calculatorEligibility = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function isProjectionSafeMortgageRate(row) {
    const rateType = String((row && row.rate_type) || '').toUpperCase();
    return rateType !== 'DISCOUNT' && rateType !== 'INTRODUCTORY' && rateType !== 'INTRO';
  }

  function isProjectionSafeSavingsRate(row) {
    const kind = String((row && row.ribbon_deposit_kind) || '').toLowerCase();
    return kind !== 'introductory' && kind !== 'intro';
  }

  /** Numeric eligibility follows docs/LVR_INTERVAL_CONTRACT.md; unknown fails closed. */
  function mortgageLvrEligible(row, value) {
    if (!Number.isFinite(value) || value <= 0 || value > 100) return false;
    const tier = String((row && row.lvr_tier) || '').trim().toLowerCase();
    let match = /^lvr_(=|<=|<)?(\d+(?:\.\d+)?)%$/.exec(tier);
    if (match) {
      const hi = Number(match[2]);
      return hi > 0 && hi <= 100 && (match[1] === '<' ? value < hi : value <= hi);
    }
    match = /^lvr_(>=|>)?(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)%$/.exec(tier);
    if (match) {
      const lo = Number(match[2]), hi = Number(match[3]);
      const inclusive = match[1] === '>=';
      return hi <= 100 && (lo < hi || (inclusive && lo === hi)) &&
        (inclusive ? value >= lo : value > lo) && value <= hi;
    }
    match = /^lvr_(>=|>)(\d+(?:\.\d+)?)%$/.exec(tier);
    if (!match) return false;
    const lo = Number(match[2]);
    return lo <= 100 && (match[1] === '>=' ? value >= lo : value > lo);
  }

  return { isProjectionSafeMortgageRate, isProjectionSafeSavingsRate, mortgageLvrEligible };
});
