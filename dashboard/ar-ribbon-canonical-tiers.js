(function () {
  'use strict';
  /**
   * Pin ribbon hierarchy tier order to AustralianRates public UI (site/ar-ribbon-format.js on main).
   * Local dashboards may load an older `site/` tree beside this repo; savings must use
   * deposit_tier (balance-band grouping in ar-ribbon-tree.js), not raw balance columns in the tier list.
   */
  var R = window.AR && window.AR.ribbon;
  if (!R) return;

  R.ribbonTierFieldsForSection = function ribbonTierFieldsForSection(sec) {
    var s = String(sec || '');
    if (s === 'home-loans') {
      return [
        'security_purpose',
        'repayment_type',
        'rate_structure',
        'fixed_rate_term',
        'lvr_tier',
        'feature_set',
        'product_name',
        'product_id',
      ];
    }
    if (s === 'savings') {
      return ['account_type', 'rate_type', 'deposit_tier', 'feature_set', 'product_name', 'product_id'];
    }
    if (s === 'term-deposits') {
      return [
        'term_months',
        'deposit_tier',
        'interest_payment',
        'rate_structure',
        'feature_set',
        'product_name',
        'product_id',
      ];
    }
    return ['security_purpose', 'repayment_type', 'rate_structure', 'product_name', 'product_id'];
  };
})();
