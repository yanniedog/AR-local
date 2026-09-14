/* Loaded history coverage and synthetic contribution disclosure; no rate math. */
(function (root) {
  'use strict';
  const count = (value) => Number.isSafeInteger(value) && value >= 0;
  const providerKey = (value) => String(value || '').trim()
    .replace(/[\u00A0\u2000-\u200B\uFEFF]/g, ' ').replace(/\s+/g, ' ').toLowerCase();

  function validCoverage(value) {
    if (!value || value.schema_version !== 1) return null;
    const fields = ['available_run_file_count', 'selected_run_file_count', 'omitted_run_file_count',
      'run_file_limit', 'unreadable_selected_run_file_count', 'empty_selected_run_file_count',
      'missing_run_file_count', 'inventory_error_count', 'observed_date_count'];
    if (!fields.every((field) => count(value[field]))) return null;
    if (value.selected_run_file_count > value.run_file_limit ||
        value.selected_run_file_count + value.omitted_run_file_count !== value.available_run_file_count ||
        value.unreadable_selected_run_file_count + value.empty_selected_run_file_count > value.selected_run_file_count ||
        value.truncated !== (value.omitted_run_file_count > 0)) return null;
    return value;
  }

  function contributions(items) {
    const providers = Array.isArray(items.providers) ? items.providers : [];
    const focus = providerKey(items.focusProvider);
    const provider = focus ? providers.find((item) => providerKey(item.label) === focus) : null;
    const points = new Map((items.points || []).map((point) => [point.date, point]));
    let observed = 0;
    let carried = 0;
    for (const day of items.dates || []) {
      const point = provider ? (provider.byDate || {})[day] : points.get(day);
      if (!point || point.count === 0) continue;
      if (![point.count, point.observed_count, point.carry_forward_count].every(count) ||
          point.observed_count + point.carry_forward_count !== point.count) return null;
      observed += point.observed_count;
      carried += point.carry_forward_count;
    }
    return { observed, carried };
  }

  function status(items, format = String) {
    if (!items || items.kind !== 'bank-history') return 'Historical ribbon: no history loaded.';
    const dates = Array.isArray(items.dates) ? items.dates : [];
    const loaded = Array.isArray(items.allDates) ? items.allDates.length : dates.length;
    const label = dates.length ? (dates[0] === dates[dates.length - 1] ? dates[0]
      : `${dates[0]} through ${dates[dates.length - 1]}`) : 'no dates in this slice';
    const parts = [`Visible window: ${label}. ${format(dates.length)} dates in range, ${format(loaded)} loaded.`];
    if (items.currentOnly) {
      parts.push('Current snapshot only; history not loaded.');
    } else {
      const coverage = validCoverage(items.historyCoverage);
      if (!coverage) parts.push('Run-file coverage unavailable.');
      else {
        parts.push(`${format(coverage.selected_run_file_count)} of ${format(coverage.available_run_file_count)} available run files selected.`);
        if (coverage.truncated) parts.push(`${format(coverage.run_file_limit)}-run-file cap; ${format(coverage.omitted_run_file_count)} older files omitted.`);
        if (coverage.unreadable_selected_run_file_count) parts.push(`${format(coverage.unreadable_selected_run_file_count)} selected files unreadable.`);
        if (coverage.empty_selected_run_file_count) parts.push(`${format(coverage.empty_selected_run_file_count)} selected files returned no matching rows.`);
        if (coverage.missing_run_file_count) parts.push(`${format(coverage.missing_run_file_count)} expected run files missing.`);
        if (coverage.inventory_error_count) parts.push('Run-file inventory incomplete.');
      }
      parts.push('Full historical coverage not verified.');
    }
    const totals = contributions(items);
    if (totals) parts.push(`${format(totals.observed)} observed rate contributions; ${format(totals.carried)} carried-forward estimates in this slice.`);
    else parts.push('Observed/carried-forward split unavailable.');
    return parts.join(' ');
  }

  const api = { validCoverage, contributions, status };
  root.LocalCdrHistoryCoverage = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window === 'object' ? window : globalThis);
