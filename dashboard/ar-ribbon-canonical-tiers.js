(function () {
  'use strict';
  /**
   * Local ribbon patches for CDR row quirks. Tier order comes from production
   * `site/ar-ribbon-format.js` (`ribbonInitialTierFieldsForSection` in hierarchy).
   * Deferred: full ar-filters.js / Tabulator table port — see UNIVERSAL_ROADMAP.
   */
  const R = window.AR && window.AR.ribbon;
  if (!R) return;

  const origGroup = R.ribbonRateStructureGroupValue;
  R.ribbonRateStructureGroupValue = function ribbonRateStructureGroupValueLocal(raw) {
    const value = String(raw || '').trim().toLowerCase();
    if (!value) return '';
    if (value === 'variable' || value === 'fixed') return value;
    const fromOrig = typeof origGroup === 'function' ? origGroup(raw) : '';
    if (fromOrig === 'variable' || fromOrig === 'fixed') return fromOrig;
    if (value === 'variable' || /^variable\b/.test(value) || /^bundle[_-]?discount[_-]?variable\b/.test(value)) {
      return 'variable';
    }
    if (value === 'fixed' || /^fixed\b/.test(value)) return 'fixed';
    const termFn = R.ribbonFixedRateTermValue;
    if (typeof termFn === 'function' && termFn(raw)) return 'fixed';
    const head = value.split(/\s+/)[0] || '';
    if (head === 'variable' || head === 'var') return 'variable';
    if (head === 'fixed') return 'fixed';
    if (/\bvariable\b/.test(value.slice(0, 96)) && !/^fixed\b/.test(value)) return 'variable';
    return fromOrig || '';
  };

  const origFormat = R.formatRibbonTierValue;
  R.formatRibbonTierValue = function formatRibbonTierValueLocal(row, field) {
    if (field === 'fixed_rate_term' && row && typeof row === 'object') {
      const explicit = row.ribbon_fixed_term != null ? String(row.ribbon_fixed_term).trim() : '';
      if (explicit) return explicit;
    }
    return typeof origFormat === 'function' ? origFormat(row, field) : '';
  };
})();
