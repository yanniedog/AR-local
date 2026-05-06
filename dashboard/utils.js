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
    if (row && row.dataset === 'Mortgage' && value > 0.3 && value <= 1) return value / 10;
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

  window.LocalCdrUtils = { bankRateMatchesSection, cssVar, normalizeRows, pct, rateValue };
})();
