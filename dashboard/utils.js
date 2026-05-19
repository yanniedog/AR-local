(function () {
  'use strict';

  function cssVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function rateValue(raw, row) {
    const value = Number(raw);
    if (!Number.isFinite(value)) return NaN;
    if (row && row.__percentStyleRate) return value / 100;
    // Some CDR mortgage feeds store 0.589 for 5.89% (÷10). Only when the raw token
    // is in (0.3, 1] and the product was not classified as percent-style (>1 elsewhere).
    if (row && row.dataset === 'Mortgage' && !row.__percentStyleRate && value > 0.3 && value <= 1) {
      return value / 10;
    }
    return value > 1 ? value / 100 : value;
  }

  function pct(raw) {
    const value = rateValue(raw);
    return Number.isFinite(value) ? (value * 100).toFixed(2) + '%' : '';
  }

  function normalizeRows(rows) {
    const percentStyleProducts = new Set();
    rows.forEach((row) => { if (Number(row.rate) > 1) percentStyleProducts.add(row.product_key || row.product_id || row.product_name); });
    return rows.map((row) => {
      const key = row.product_key || row.product_id || row.product_name;
      const out = { ...row, __percentStyleRate: percentStyleProducts.has(key) };
      out.rate = String(rateValue(row.rate, out));
      if (row.comparison_rate) out.comparison_rate = String(rateValue(row.comparison_rate, out));
      return out;
    });
  }

  function bankRateMatchesSection(row) {
    return row.dataset === 'Mortgage'
      ? row.rate_family === 'lending' && row.rate_type !== 'DISCOUNT'
      : row.rate_family === 'deposit';
  }

  // Mirror cdr_dashboard_server.HISTORY_IDENTITY_FIELDS (rate values excluded).
  const HISTORY_IDENTITY_FIELDS = [
    'dataset', 'provider', 'product_key', 'product_id', 'product_name',
    'rate_family', 'rate_type', 'term', 'repayment_type', 'loan_purpose',
    'application_type', 'application_frequency', 'security_purpose',
    'ribbon_repayment_type', 'ribbon_rate_structure', 'ribbon_fixed_term',
    'ribbon_deposit_kind', 'lvr_tier', 'balance_min', 'balance_max',
    'term_months', 'interest_payment', 'feature_set', 'account_type',
  ];

  function historyIndexKey(row) {
    return HISTORY_IDENTITY_FIELDS.map((field) => String(row[field] ?? '')).join('\u0001');
  }

  window.LocalCdrUtils = { bankRateMatchesSection, cssVar, historyIndexKey, normalizeRows, pct, rateValue };
})();
