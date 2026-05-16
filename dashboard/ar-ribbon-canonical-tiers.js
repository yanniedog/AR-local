(function () {
  'use strict';
  /**
   * Local ribbon tier order — granular but short. Matches AustralianRates'
   * public hierarchy intent while ensuring bank_name appears as a tier so the
   * tree can collapse to a single lender per row.
   *
   * Order chosen to mirror how a human filters: criteria (purpose, repayment,
   * structure) first; then balance/term tiers; then features; then lender;
   * finally the specific product.
   */
  const R = window.AR && window.AR.ribbon;
  if (!R) return;

  const TIER_FIELDS = {
    'home-loans': [
      'security_purpose',   // Owner Occ / Investor
      'repayment_type',     // P&I / IO
      'rate_structure',     // Variable / Fixed
      'fixed_rate_term',    // 1Y..5Y when fixed
      'lvr_tier',           // <=60% .. 90-95%
      'feature_set',        // Basic / Premium
      'bank_name',          // Lender (short)
      'product_name',       // Product
      'product_id',
    ],
    savings: [
      'account_type',       // Savings / Transaction / At call
      'rate_type',          // Base / Bonus / Intro / Total
      'deposit_tier',       // $0-10k .. $10m+
      'feature_set',
      'bank_name',
      'product_name',
      'product_id',
    ],
    'term-deposits': [
      'term_months',        // 1-3m .. 60m+
      'deposit_tier',
      'interest_payment',   // At maturity / Monthly / Quarterly / Annually
      'rate_structure',
      'feature_set',
      'bank_name',
      'product_name',
      'product_id',
    ],
  };

  const DEFAULT_FIELDS = ['security_purpose', 'repayment_type', 'rate_structure', 'bank_name', 'product_name', 'product_id'];

  R.ribbonTierFieldsForSection = function ribbonTierFieldsForSection(sec) {
    const fields = TIER_FIELDS[String(sec || '')];
    return fields ? fields.slice() : DEFAULT_FIELDS.slice();
  };
})();
