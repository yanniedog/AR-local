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

  return { isProjectionSafeMortgageRate, isProjectionSafeSavingsRate };
});
