(function () {
  'use strict';

  /** Banking sections only; Economic Data is the public macro page. */
  const SECTION = {
    Mortgage: 'Mortgage',
    Savings: 'Savings',
    TD: 'TD',
    EconomicData: 'EconomicData',
  };
  const BANKING_SECTIONS = [SECTION.Mortgage, SECTION.Savings, SECTION.TD];

  function isEconomicDataSection(section) {
    return section === SECTION.EconomicData;
  }

  function sectionDisplayLabel(section) {
    if (section === SECTION.TD) return 'Term Deposits';
    return section;
  }

  function sectionFromPathname() {
    const path = String(window.location.pathname || '/').replace(/\/+$/, '') || '/';
    if (path === '/savings') return SECTION.Savings;
    if (path === '/term-deposits') return SECTION.TD;
    return SECTION.Mortgage;
  }

  function sectionToPath(section) {
    if (section === SECTION.Savings) return '/savings/';
    if (section === SECTION.TD) return '/term-deposits/';
    return '/';
  }

  function syncSectionUrl() {
    const target = sectionToPath(state.section);
    if (window.location.pathname !== target) {
      window.history.replaceState(null, '', target);
    }
  }

  let loadSectionToken = 0;

  const state = {
    section: SECTION.Mortgage,
    manifest: null,
    manifestSignature: '',
    bankRibbons: {},
    bankSections: {},
    bankHistory: null,
    bankHistorySection: '',
    bankHistoryIndex: null,
    retainedRunDatesSorted: [],
    descending: false,
    includeNonStandard: false,
    historyWindow: '30D',
    hierarchyPath: '',
    focusProvider: '',
    hoverProvider: '',
    focusedProductKeys: null,
    chartHoverDate: '',
    chartPinnedDate: '',
    chartDates: [],
    _chartFocusPainted: '',
    _chartRedrawFrame: 0,
    ingestSchedule: null,
    ingestClockOffsetMs: 0,
    ingestScheduleFetchedAtMs: 0,
    ingestScheduleIntervalsStarted: false,
    realtimeIntervalsStarted: false,
    realtimeRefreshInFlight: false,
  };
  const $ = (id) => document.getElementById(id);
  const { bankRateMatchesSection, historyIndexKey, normalizeRows, pct } = window.LocalCdrUtils;
  const HISTORY_WINDOWS = { '30D': 30, '90D': 90, '180D': 180, '1Y': 365 };

  function clear(element) {
    while (element.firstChild) element.removeChild(element.firstChild);
  }

  function child(parent, tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text != null) element.textContent = String(text);
    parent.appendChild(element);
    return element;
  }

  function preferredDescending(section) {
    return section !== 'Mortgage';
  }

  async function getJson(url, options) {
    const response = await fetch(url, { cache: 'force-cache', ...(options || {}) });
    if (!response.ok) throw new Error(url + ' returned ' + response.status);
    return response.json();
  }

  // The server strips constants (dataset, rate_family, run_date) from
  // /api/banks/section and /api/banks/history/section since they're already in
  // the envelope. Put them back on each row before downstream code touches it,
  // so the existing section filter, history identity key, and the current-only
  // ribbon seed (which keys aggregation by run_date) keep working unchanged.
  function hydrateSectionRows(rows, section, runDate) {
    if (!Array.isArray(rows) || !section) return rows;
    const rateFamily = section === 'Mortgage' ? 'lending' : 'deposit';
    rows.forEach((row) => {
      row.dataset = section;
      row.rate_family = rateFamily;
      if (runDate && !row.run_date) row.run_date = runDate;
      if (window.LocalCdrRibbonMap && window.LocalCdrRibbonMap.hydrateCanonicalRibbonFields) {
        window.LocalCdrRibbonMap.hydrateCanonicalRibbonFields(row, section);
      }
    });
    return rows;
  }

  function num(value) {
    return Number(value || 0).toLocaleString('en-AU');
  }

  // Non-standard accounts (foreign-currency, farm, business, trust/SMSF, …) are
  // hidden by default; the chart-toggle-nonstandard checkbox opts them in. Legacy
  // rows with no account_class read '' and are always treated as standard.
  // 'non_standard' is the wire value emitted by cdr_taxonomy.ACCOUNT_CLASS_NON_STANDARD.
  const ACCOUNT_CLASS_NON_STANDARD = 'non_standard';
  function accountClassVisible(row) {
    if (state.includeNonStandard) return true;
    return String(row.account_class || '') !== ACCOUNT_CLASS_NON_STANDARD;
  }

  // The /api/banks/ribbon aggregate now depends on the non-standard toggle, so the
  // bootstrap cache must be keyed by it too — otherwise switching the toggle and
  // re-entering a section would replay a stale (wrongly-filtered) ribbon.
  function ribbonCacheKey(section, includeNonStandard = state.includeNonStandard) {
    return includeNonStandard ? `${section}|ns` : section;
  }

  // Section-scoped rows WITHOUT the account-class filter. Used to seed the
  // current-only history so the seed always carries every product; visibility is
  // applied when the history index is (re)built via historyRowMatchesLiveTable,
  // so toggling the checkbox works even before the full history payload arrives.
  function sectionRows() {
    const sectionPayload = state.bankSections[state.section];
    if (!sectionPayload || !Array.isArray(sectionPayload.rates)) return [];
    return sectionPayload.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
  }

  function rateRows() {
    return sectionRows().filter(accountClassVisible);
  }

  function focusActiveProvider() {
    return String(state.hoverProvider || state.focusProvider || '').trim();
  }

  function providerMatchKeys(label) {
    const raw = String(label || '').trim();
    const brand = window.LocalCdrBrand;
    const canonical = brand && brand.lookupProvider ? brand.lookupProvider(raw) : raw;
    const keys = new Set();
    [raw, canonical].forEach((value) => {
      const key = String(value || '').trim().toLowerCase();
      if (key) keys.add(key);
    });
    return keys;
  }

  function rowMatchesProvider(row, label) {
    const keys = providerMatchKeys(label);
    if (!keys.size) return true;
    return keys.has(String(row.provider || '').trim().toLowerCase());
  }

  /** Click-locked provider filter (table/hierarchy). Chart hover uses focusProvider on the model only. */
  function applyFocusFilter(rows) {
    const focus = String(state.focusProvider || '').trim();
    if (!focus) return rows;
    return rows.filter((row) => rowMatchesProvider(row, focus));
  }

  const rowProductKey = (row) => window.LocalCdrHierarchy.rowProductKey(row);

  function applyHierarchyFilter(rows) {
    const keys = state.focusedProductKeys;
    if (!keys) return rows;
    return rows.filter((row) => keys.has(rowProductKey(row)));
  }

  function historyRowMatchesLiveTable(row) {
    return row.dataset === state.section && bankRateMatchesSection(row) && accountClassVisible(row);
  }

  function buildHistoryIndex(rows) {
    const index = {};
    (rows || []).forEach((row) => {
      if (!historyRowMatchesLiveTable(row)) return;
      const key = historyIndexKey(row);
      if (!key) return;
      if (!index[key]) index[key] = [];
      index[key].push(row);
    });
    return index;
  }

  function refreshRetainedRunDatesCache() {
    const raw = state.bankHistory && state.bankHistory.run_dates;
    if (!Array.isArray(raw)) {
      state.retainedRunDatesSorted = [];
      return;
    }
    state.retainedRunDatesSorted = sortedValidRunDates(raw);
  }

  function refreshBankHistoryIndex() {
    if (!state.bankHistory) return;
    state.bankHistoryIndex = buildHistoryIndex(state.bankHistory.rates);
    refreshRetainedRunDatesCache();
  }

  function parseYmd(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return null;
    const parts = String(value || '').split('-').map((part) => Number(part));
    if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part))) return null;
    const ts = Date.UTC(parts[0], parts[1] - 1, parts[2]);
    const check = new Date(ts);
    if (check.getUTCFullYear() !== parts[0] || check.getUTCMonth() !== parts[1] - 1 || check.getUTCDate() !== parts[2]) return null;
    return ts;
  }

  function normalizeRunDate(value) {
    const date = String(value || '').slice(0, 10);
    return parseYmd(date) == null ? '' : date;
  }

  function sortedValidRunDates(values) {
    // Single parseYmd per input value (Gemini PR #131): the previous
    // path called parseYmd inside normalizeRunDate AND again here for
    // the sort key, which is the hot path on every realtime refresh.
    const seen = new Set();
    const rows = [];
    (values || []).forEach((value) => {
      const date = String(value || '').slice(0, 10);
      const ts = parseYmd(date);
      if (ts == null || seen.has(date)) return;
      seen.add(date);
      rows.push({ date, ts });
    });
    rows.sort((a, b) => a.ts - b.ts);
    return rows.map((row) => row.date);
  }

  function historyDatesInWindow(dates) {
    const sorted = (dates || [])
      .map((date) => ({ date: String(date || ''), ts: parseYmd(date) }))
      .filter((item) => item.ts != null)
      .sort((a, b) => a.ts - b.ts)
      .map((item) => item.date);
    if (state.historyWindow === 'All' || sorted.length < 2) return sorted;
    const days = HISTORY_WINDOWS[state.historyWindow] || 30;
    const anchor = parseYmd(sorted[sorted.length - 1]);
    if (anchor == null) return sorted;
    const cutoff = anchor - (days * 24 * 60 * 60 * 1000);
    return sorted.filter((date) => {
      const parsed = parseYmd(date);
      return parsed != null && parsed >= cutoff;
    });
  }

  /** All run dates retained by /api/banks/history (not limited to the current chart slice). */
  function retainedRunDates() {
    if (!state.retainedRunDatesSorted) refreshRetainedRunDatesCache();
    return (state.retainedRunDatesSorted || []).slice();
  }

  async function loadBankHistory() {
    if (state.bankHistory && state.bankHistorySection === state.section && !state.bankHistory.current_only) return;
    const sectionName = state.section;
    const section = encodeURIComponent(sectionName);
    const data = await getJson(`/api/banks/history/section?date=${state.manifest.run_date}&section=${section}`);
    // History rows already carry run_date from the server (it's the time axis),
    // so we only need to put dataset/rate_family back.
    hydrateSectionRows(data.rates, sectionName);
    const rates = Array.isArray(data.rates) ? normalizeRows(data.rates) : [];
    if (state.section !== sectionName) return;
    state.bankHistory = {
      ...data,
      rates,
      run_dates: sortedValidRunDates(Array.isArray(data.run_dates) ? data.run_dates : []),
    };
    state.bankHistorySection = sectionName;
    refreshBankHistoryIndex();
  }

  function seedCurrentHistory(section, rows) {
    const normalized = normalizeRows(rows || []);
    state.bankHistory = {
      run_dates: sortedValidRunDates(state.manifest && state.manifest.run_date ? [state.manifest.run_date] : []),
      rates: normalized,
      carry_forward_count: 0,
      section,
      current_only: true,
    };
    state.bankHistorySection = section;
    refreshBankHistoryIndex();
  }

  function currentRateRange(rows) {
    let min = null;
    let max = null;
    rows.forEach((row) => {
      const rate = Number(row.rate);
      if (!Number.isFinite(rate) || rate <= 0) return;
      if (min == null || rate < min) min = rate;
      if (max == null || rate > max) max = rate;
    });
    return { min, max };
  }

  function filteredHistoryRows(currentRows) {
    if (!state.bankHistoryIndex) return [];
    const visibleKeys = new Set();
    currentRows.forEach((row) => {
      const key = historyIndexKey(row);
      if (key) visibleKeys.add(key);
    });
    if (!visibleKeys.size) return [];
    const out = [];
    visibleKeys.forEach((key) => {
      (state.bankHistoryIndex[key] || []).forEach((row) => out.push(row));
    });
    return out;
  }

  function medianOf(values) {
    if (!values || !values.length) return null;
    const sorted = values.slice().sort((a, b) => a - b);
    const mid = sorted.length >> 1;
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  function buildAggregateRibbon(historyRows) {
    const byProvider = {};
    const sliceDates = new Set();
    const byDate = {};
    const accumulate = (slot, rate) => {
      if (!slot) return { min: rate, max: rate, sum: rate, count: 1, rates: [rate] };
      slot.min = Math.min(slot.min, rate);
      slot.max = Math.max(slot.max, rate);
      slot.sum += rate;
      slot.count += 1;
      slot.rates.push(rate);
      return slot;
    };
    historyRows.forEach((row) => {
      const date = normalizeRunDate(row.run_date);
      const provider = row.provider || 'Unknown';
      const rate = Number(row.rate);
      if (!date || !Number.isFinite(rate) || rate <= 0) return;
      sliceDates.add(date);
      if (!byProvider[provider]) byProvider[provider] = { label: provider, byDate: {} };
      const p = byProvider[provider];
      p.byDate[date] = accumulate(p.byDate[date], rate);
      byDate[date] = accumulate(byDate[date], rate);
    });
    const retained = retainedRunDates();
    const sliceDatesSorted = sortedValidRunDates(Array.from(sliceDates));
    const timelineSource = retained.length ? retained : sliceDatesSorted;
    const dates = historyDatesInWindow(timelineSource);
    const points = dates.map((date) => {
      const agg = byDate[date];
      if (!agg) return { date, min: null, max: null, mean: null, median: null, count: 0 };
      return {
        date,
        min: agg.min,
        max: agg.max,
        mean: agg.sum / Math.max(1, agg.count),
        median: medianOf(agg.rates),
        count: agg.count,
      };
    });
    const providers = Object.values(byProvider).map((p) => {
      const visible = {};
      dates.forEach((date) => {
        const point = p.byDate[date];
        if (!point) return;
        visible[date] = {
          min: point.min,
          max: point.max,
          mean: point.sum / Math.max(1, point.count),
          median: medianOf(point.rates),
          count: point.count,
        };
      });
      return { label: p.label, byDate: visible };
    });
    return {
      dates,
      points,
      providers,
      allDates: retained.length ? retained : sliceDatesSorted,
    };
  }

  function availableProvidersInSection() {
    const rows = normalizeRows(rateRows());
    return [...new Set(rows.map((row) => String(row.provider || '').trim()).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
  }

  function deterministicProviderFallback() {
    const providers = availableProvidersInSection();
    return providers.length ? providers[0] : '';
  }

  function sanitizeFocusedProviders() {
    const fallback = deterministicProviderFallback();
    if (state.focusProvider) {
      const focusValid = rateRows().some((row) => rowMatchesProvider(row, state.focusProvider));
      if (!focusValid) state.focusProvider = fallback;
    }
    if (state.hoverProvider) {
      const hoverValid = rateRows().some((row) => rowMatchesProvider(row, state.hoverProvider));
      // Clear hover rather than substitute a deterministic provider
      // (Codex P2 PR #131): hover is a transient pointer state, not
      // user intent. Substituting would leave the chart dimmed to a
      // provider the user never hovered, with no mouseleave to fire
      // the natural reset because the pointer may no longer be on
      // the logo rail when the polling refresh lands.
      if (!hoverValid) state.hoverProvider = '';
    }
  }

  function closestRetainedDate(dates, target) {
    const tsTarget = parseYmd(target);
    if (!dates.length) return '';
    if (tsTarget == null) return dates[dates.length - 1];
    let best = dates[0];
    for (let i = 0; i < dates.length; i += 1) {
      const date = dates[i];
      const ts = parseYmd(date);
      if (ts == null) continue;
      if (ts > tsTarget) break;
      best = date;
    }
    return best;
  }

  function sanitizeChartDateState(validDates) {
    const dates = sortedValidRunDates(validDates);
    const pinned = normalizeRunDate(state.chartPinnedDate);
    const hover = normalizeRunDate(state.chartHoverDate);
    if (pinned && dates.indexOf(pinned) < 0) state.chartPinnedDate = closestRetainedDate(dates, pinned);
    else state.chartPinnedDate = pinned;
    if (hover && dates.indexOf(hover) < 0) state.chartHoverDate = closestRetainedDate(dates, hover);
    else state.chartHoverDate = hover;
    if (!state.chartHoverDate && dates.length) state.chartHoverDate = dates[dates.length - 1];
  }

  function sanitizeFocusedProductKeys() {
    if (!state.focusedProductKeys || !state.focusedProductKeys.size) {
      state.focusedProductKeys = null;
      return;
    }
    const live = new Set();
    normalizeRows(rateRows()).forEach((row) => {
      const key = rowProductKey(row);
      if (key) live.add(key);
    });
    const retained = new Set();
    state.focusedProductKeys.forEach((key) => {
      if (live.has(key)) retained.add(key);
    });
    state.focusedProductKeys = retained.size ? retained : null;
  }

  function chartItems(rows) {
    const historyRows = filteredHistoryRows(rows);
    const aggregate = buildAggregateRibbon(historyRows);
    return {
      kind: 'bank-history',
      section: state.section,
      window: state.historyWindow,
      dates: aggregate.dates,
      points: aggregate.points,
      providers: aggregate.providers,
      allDates: aggregate.allDates,
      descending: state.descending,
      currentRange: currentRateRange(rows),
      totalHistoryRows: historyRows.length,
      focusProvider: focusActiveProvider(),
      chartPinnedDate: state.chartPinnedDate,
      onHoverDateChange: onChartHoverDate,
      onSliceClick: onChartSliceClick,
    };
  }

  function ribbonChartItems(ribbon) {
    if (!ribbon || !ribbon.run_date) return null;
    const date = normalizeRunDate(ribbon.run_date);
    if (!date) return null;
    const range = ribbon.range || {};
    const providers = (ribbon.providers || []).map((row) => ({
      label: row.provider || 'Unknown',
      byDate: {
        [date]: {
          min: Number(row.min),
          max: Number(row.max),
          mean: Number(row.mean),
          median: row.median == null ? null : Number(row.median),
          count: Number(row.rates || 0),
        },
      },
    }));
    return {
      kind: 'bank-history',
      section: state.section,
      window: state.historyWindow,
      dates: [date],
      points: [{
        date,
        min: range.min == null ? null : Number(range.min),
        max: range.max == null ? null : Number(range.max),
        mean: range.mean == null ? null : Number(range.mean),
        median: range.median == null ? null : Number(range.median),
        count: Number((ribbon.counts && ribbon.counts.rates) || 0),
      }],
      providers,
      allDates: [date],
      descending: state.descending,
      currentRange: {
        min: range.min == null ? null : Number(range.min),
        max: range.max == null ? null : Number(range.max),
      },
      totalHistoryRows: Number((ribbon.counts && ribbon.counts.rates) || 0),
      focusProvider: focusActiveProvider(),
      chartPinnedDate: state.chartPinnedDate,
      onHoverDateChange: onChartHoverDate,
      onSliceClick: onChartSliceClick,
    };
  }

  function chartTableAnchorDate() {
    const pinned = String(state.chartPinnedDate || '').slice(0, 10);
    if (pinned) return pinned;
    const dates = Array.isArray(state.chartDates) ? state.chartDates : [];
    return dates.length ? String(dates[dates.length - 1]).slice(0, 10) : '';
  }

  /** Ribbon hover / pin date (hover wins over default timeline end). */
  function chartAnchorDate() {
    const pinned = String(state.chartPinnedDate || '').slice(0, 10);
    if (pinned) return pinned;
    const hover = String(state.chartHoverDate || '').slice(0, 10);
    if (hover) return hover;
    return chartTableAnchorDate();
  }

  /** Rebuild hierarchy rows for a historical chart slice (per-date product counts). */
  function rateRowsForChartAnchor(baseRows) {
    const anchor = chartAnchorDate();
    const manifest = String((state.manifest && state.manifest.run_date) || '');
    if (!anchor || !state.bankHistoryIndex || anchor === manifest) return baseRows;
    const out = [];
    (baseRows || []).forEach((row) => {
      const key = historyIndexKey(row);
      const series = state.bankHistoryIndex[key] || [];
      for (let i = 0; i < series.length; i += 1) {
        const historyRow = series[i];
        if (String(historyRow.run_date || '') === anchor) {
          out.push(historyRow);
          return;
        }
      }
    });
    return out;
  }

  function onChartHoverDate(dateYmd) {
    const next = String(dateYmd || '').slice(0, 10);
    if (state.chartHoverDate === next) return;
    state.chartHoverDate = next;
    refreshProviderHighlightUi(undefined, { highlightOnly: true });
    refreshHierarchyPanel(undefined, { highlightOnly: false, slicePreview: true });
    redrawChartIfFocusChanged();
  }

  function onChartSliceClick(dateYmd) {
    const next = String(dateYmd || '').slice(0, 10);
    const pinned = String(state.chartPinnedDate || '').slice(0, 10);
    if (!next) {
      if (!pinned) return;
      state.chartPinnedDate = '';
    } else if (next === pinned) {
      state.chartPinnedDate = '';
    } else {
      state.chartPinnedDate = next;
    }
    refreshProviderHighlightUi(undefined, { slicePreview: true });
  }

  function visibleSliceRows() {
    return chartSliceRows(applyFocusFilter(normalizeRows(rateRows())));
  }

  function relevantProviderKeys() {
    const hover = String(state.hoverProvider || '').trim();
    if (hover) {
      return providerMatchKeys(hover);
    }
    const focus = String(state.focusProvider || '').trim();
    if (focus) return providerMatchKeys(focus);
    const rows = visibleSliceRows();
    const pinned = String(state.chartPinnedDate || '').slice(0, 10);
    const chartHover = String(state.chartHoverDate || '').slice(0, 10);
    const anchor = pinned || chartHover || chartTableAnchorDate();
    if (!anchor || !state.bankHistoryIndex || !rows.length) return null;
    const keys = new Set();
    rows.forEach((row) => {
      const indexKey = historyIndexKey(row);
      (state.bankHistoryIndex[indexKey] || []).forEach((historyRow) => {
        if (String(historyRow.run_date || '') !== anchor) return;
        const provider = String(historyRow.provider || '').trim().toLowerCase();
        if (provider) keys.add(provider);
      });
    });
    return keys.size ? keys : null;
  }

  function isProviderDimmed(provider, activeProviders) {
    if (!activeProviders) return false;
    const keys = providerMatchKeys(provider);
    for (const key of keys) {
      if (activeProviders.has(key)) return false;
    }
    return true;
  }

  const logoRailMatchCache = new Map();
  let logoRailHighlightRaf = 0;
  let logoRailHighlightPending = null;

  function logoRailProviderDimmed(provider, activeProviders, keys) {
    if (!activeProviders) return false;
    const matchKeys = keys || providerMatchKeys(provider);
    for (const key of matchKeys) {
      if (activeProviders.has(key)) return false;
    }
    return true;
  }

  /** Toggle logo-rail dim/hover/selection without rebuilding badges (avoids logo reload flash). */
  function applyLogoRailHighlight(activeProviders) {
    const wrap = $('selectedLogos');
    if (!wrap || wrap.hidden) return;
    const focus = String(state.focusProvider || '').toLowerCase();
    const hover = String(state.hoverProvider || '').toLowerCase();
    const buttons = wrap._logoRailButtons
      || (wrap._logoRailButtons = Array.from(wrap.querySelectorAll('.local-provider-logo-btn')));
    buttons.forEach((btn) => {
      const provider = btn.dataset.providerPick || '';
      const lc = provider.toLowerCase();
      btn.classList.toggle('is-selected', !!(focus && lc === focus));
      btn.classList.toggle('is-hover', !!(hover && lc === hover));
      let keys = logoRailMatchCache.get(provider);
      if (!keys) {
        keys = providerMatchKeys(provider);
        logoRailMatchCache.set(provider, keys);
      }
      const dim = logoRailProviderDimmed(provider, activeProviders, keys);
      btn.classList.toggle('is-dim', dim);
      const badge = btn.querySelector('.bank-badge');
      if (badge) badge.classList.toggle('is-logo-dim', dim);
    });
  }

  function scheduleLogoRailHighlight(activeProviders) {
    logoRailHighlightPending = activeProviders;
    if (logoRailHighlightRaf) return;
    logoRailHighlightRaf = requestAnimationFrame(() => {
      logoRailHighlightRaf = 0;
      const active = logoRailHighlightPending;
      logoRailHighlightPending = null;
      applyLogoRailHighlight(active);
    });
  }

  function refreshProviderHighlightUi(activeProviders, options) {
    const active = activeProviders !== undefined ? activeProviders : relevantProviderKeys();
    refreshHierarchyPanel(active, options);
    if (options && options.highlightOnly) {
      scheduleLogoRailHighlight(active);
      return;
    }
    renderSelectedLogos(active);
  }

  function hierarchyRenderOptions(overrides) {
    return {
      ...(overrides || {}),
      onFocusChange: (productKeys) => {
        if (state._hierarchySlicePreview) return;
        state.focusedProductKeys = productKeys && productKeys.size ? productKeys : null;
      },
    };
  }

  function refreshHierarchyPanel(activeProviders, options) {
    if (!$('hierarchy') || $('hierarchy').hidden) return;
    const active = activeProviders !== undefined ? activeProviders : relevantProviderKeys();
    state.isProviderDimmed = (provider) => isProviderDimmed(provider, active);
    if (options && options.highlightOnly && window.LocalCdrHierarchy.applyProviderHighlight) {
      window.LocalCdrHierarchy.applyProviderHighlight($('hierarchy'), state);
      return;
    }
    let rows = applyFocusFilter(normalizeRows(rateRows()));
    if (options && options.slicePreview) {
      rows = rateRowsForChartAnchor(rows);
    }
    window.LocalCdrHierarchy.render($('hierarchy'), $('table-count'), rows, state, hierarchyRenderOptions(options));
  }

  function setLinks() {
    const date = state.manifest.run_date;
    const json = `/exports/banks-${date}.json`;
    const xlsx = `/exports/banks-${date}.xlsx`;
    $('jsonLink').href = json;
    $('xlsxLink').href = xlsx;
    $('footerJsonLink').href = json;
    $('footerXlsxLink').href = xlsx;
  }

  function setSectionUi() {
    document.body.classList.toggle('ar-section-home-loans',   state.section === 'Mortgage');
    document.body.classList.toggle('ar-section-savings',      state.section === 'Savings');
    document.body.classList.toggle('ar-section-term-deposits',state.section === 'TD');
    const slug = state.section === SECTION.Savings ? 'savings' : state.section === SECTION.TD ? 'term-deposits' : 'home-loans';
    document.body.dataset.arSection = slug;
    document.querySelectorAll('[data-section]').forEach((button) => {
      const active = button.dataset.section === state.section;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-current', active ? 'page' : 'false');
    });
    const pageTitles = {
      Mortgage: 'Compare Australian Home Loan Rates | AustralianRates',
      Savings:  'Compare Australian Savings Rates | AustralianRates',
      TD:       'Compare Australian Term Deposit Rates | AustralianRates',
    };
    document.title = pageTitles[state.section] || pageTitles.Mortgage;
    const titles = {
      Mortgage: 'Home loan rates, tracked.',
      Savings: 'Savings rates, tracked.',
      TD: 'Term deposit yields, tracked.',
    };
    $('page-title').textContent = titles[state.section] || titles.Mortgage;
    const leaderLabels = { Mortgage: 'Lowest rate', Savings: 'Top yield', TD: 'Top yield' };
    const focusLabels  = { Mortgage: 'Lowest rates', Savings: 'Top yields', TD: 'Top yields' };
    $('hero-leader-label').textContent = leaderLabels[state.section] || leaderLabels.Mortgage;
    $('chart-focus').textContent = focusLabels[state.section] || focusLabels.Mortgage;
    $('chart-toggle-sort').textContent = state.descending ? 'Lowest first' : 'Highest first';

    document.querySelectorAll('.local-history-window, .local-history-window-status')
      .forEach((el) => { el.hidden = false; });
  }

  function setHistoryWindowUi(items) {
    document.querySelectorAll('[data-history-window]').forEach((button) => {
      const active = button.dataset.historyWindow === state.historyWindow;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const status = $('history-window-status');
    if (!status) return;
    if (!items || items.kind !== 'bank-history' || !items.dates.length) {
      status.textContent = 'Historical ribbon: no retained run data for this slice.';
      return;
    }
    const first = items.dates[0];
    const last = items.dates[items.dates.length - 1];
    const label = first === last ? first : `${first} through ${last}`;
    const inRange = items.dates.length;
    const retained = items.allDates.length;
    status.textContent = `Visible window: ${label}. ${num(inRange)} in range, ${num(retained)} retained.`;
  }

  function parseIsoMs(value) {
    const ts = Date.parse(String(value || ''));
    return Number.isFinite(ts) ? ts : null;
  }

  function formatCountdown(ms) {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const sec = String(seconds).padStart(2, '0');
    const min = String(minutes).padStart(2, '0');
    const hr = String(hours).padStart(2, '0');
    if (days > 0) return `${days}d ${hr}h ${min}m ${sec}s`;
    if (hours > 0) return `${hours}h ${min}m ${sec}s`;
    return `${minutes}m ${sec}s`;
  }

  function renderIngestCountdown() {
    const el = $('ingestCountdown');
    if (!el) return;
    const schedule = state.ingestSchedule || {};
    const nextMs = parseIsoMs(schedule.next_due_utc);
    if (nextMs == null) {
      el.textContent = 'Next refresh: unavailable';
      return;
    }
    if (state.ingestScheduleFetchedAtMs && Date.now() - state.ingestScheduleFetchedAtMs > 15 * 60 * 1000) {
      el.textContent = 'Next refresh: schedule stale';
      return;
    }
    const serverNowMs = Date.now() + state.ingestClockOffsetMs;
    const remaining = nextMs - serverNowMs;
    const nextText = new Date(nextMs).toLocaleString('en-AU', {
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
      timeZoneName: 'short',
    });
    el.textContent = `Next refresh in ${formatCountdown(remaining)} (${nextText})`;
  }

  async function refreshIngestSchedule() {
    try {
      const data = await getJson('/api/ingest-schedule', { cache: 'no-store' });
      const serverNow = parseIsoMs(data.now_utc);
      state.ingestSchedule = data;
      state.ingestClockOffsetMs = serverNow == null ? state.ingestClockOffsetMs : serverNow - Date.now();
      state.ingestScheduleFetchedAtMs = Date.now();
    } catch (_err) {
      // renderIngestCountdown will keep "unavailable" or mark an old value stale.
    }
    renderIngestCountdown();
  }

  function loadIngestSchedule() {
    if (state.ingestScheduleIntervalsStarted) return;
    state.ingestScheduleIntervalsStarted = true;
    renderIngestCountdown();
    window.setInterval(renderIngestCountdown, 1000);
    window.setInterval(refreshIngestSchedule, 5 * 60 * 1000);
    refreshIngestSchedule();
  }

  function manifestSignature(manifest) {
    const runDate = String((manifest && manifest.run_date) || '');
    const counts = manifest && manifest.banks_counts ? manifest.banks_counts : {};
    const rates = Number(counts.rates || 0);
    const providers = Number(counts.providers || 0);
    const products = Number(counts.products || 0);
    return `${runDate}|${rates}|${providers}|${products}`;
  }

  async function refreshRealtimeSectionData() {
    if (state.realtimeRefreshInFlight) return;
    state.realtimeRefreshInFlight = true;
    try {
      const latest = await getJson('/api/latest', { cache: 'no-store' });
      if (!latest || !latest.run_date) return;
      const nextSignature = manifestSignature(latest);
      if (!nextSignature || nextSignature === state.manifestSignature) return;
      const sectionName = state.section;
      const encoded = encodeURIComponent(sectionName);
      const dateEncoded = encodeURIComponent(latest.run_date);
      // Capture the toggle BEFORE awaiting so the response is cached under the key
      // matching the request, even if the user toggles mid-flight (Codex PR #149).
      const ribIncludeNs = state.includeNonStandard;
      const [ribbon, sectionPayload, historyPayload] = await Promise.all([
        getJson(`/api/banks/ribbon?date=${dateEncoded}&section=${encoded}${ribIncludeNs ? '&include_non_standard=1' : ''}`),
        getJson(`/api/banks/section?date=${dateEncoded}&section=${encoded}`),
        getJson(`/api/banks/history/section?date=${dateEncoded}&section=${encoded}`),
      ]);
      hydrateSectionRows(sectionPayload.rates, sectionName, latest.run_date);
      hydrateSectionRows(historyPayload.rates, sectionName);
      // Cache the fetched section data for ``sectionName`` regardless of
      // whether the user has navigated away (Codex P2 PR #131) -- if they
      // navigate back, those rows are fresh.
      state.bankRibbons[ribbonCacheKey(sectionName, ribIncludeNs)] = ribbon;
      state.bankSections[sectionName] = {
        ...sectionPayload,
        rates: Array.isArray(sectionPayload.rates) ? normalizeRows(sectionPayload.rates) : [],
      };
      if (state.section !== sectionName) {
        // User switched sections while we were fetching. Do NOT advance
        // state.manifestSignature here (Codex P1 PR #131): the next poll
        // needs to refetch for the now-active section, and that loop
        // short-circuits when nextSignature === state.manifestSignature.
        // Updating state.manifest is fine; the signature is the gate.
        state.manifest = latest;
        return;
      }
      state.manifest = latest;
      state.manifestSignature = nextSignature;
      state.bankHistory = {
        ...historyPayload,
        rates: Array.isArray(historyPayload.rates) ? normalizeRows(historyPayload.rates) : [],
        run_dates: sortedValidRunDates(Array.isArray(historyPayload.run_dates) ? historyPayload.run_dates : []),
      };
      state.bankHistorySection = sectionName;
      refreshBankHistoryIndex();
      // No snapshot/restore here (Gemini + Codex PR #131): UI fields
      // (descending, hoverProvider, chartPinnedDate, etc.) are
      // persistent on ``state`` and are not touched by the data
      // refresh above. Snapshotting before the await and restoring
      // after would clobber any in-flight user interaction.
      sanitizeFocusedProviders();
      sanitizeFocusedProductKeys();
      sanitizeChartDateState(state.bankHistory.run_dates);
      warmProviderLogoCache();
      render();
    } catch (_err) {
      // Keep current dashboard view and retry on next poll.
    } finally {
      state.realtimeRefreshInFlight = false;
    }
  }

  function loadRealtimeSectionData() {
    if (state.realtimeIntervalsStarted) return;
    state.realtimeIntervalsStarted = true;
    window.setInterval(refreshRealtimeSectionData, 30 * 1000);
  }

  function warmProviderLogoCache() {
    const sectionPayload = state.bankSections[state.section];
    if (!window.LocalCdrBrand || !window.LocalCdrBrand.preloadRailProviders || !sectionPayload || !sectionPayload.rates) {
      return;
    }
    const bySection = {};
    sectionPayload.rates.forEach((row) => {
      if (!row.provider || !row.dataset) return;
      if (!bySection[row.dataset]) bySection[row.dataset] = { providers: new Set(), samples: {} };
      bySection[row.dataset].providers.add(row.provider);
      if (!bySection[row.dataset].samples[row.provider]) bySection[row.dataset].samples[row.provider] = row;
    });
    Object.keys(bySection).forEach((section) => {
      const pack = bySection[section];
      const providers = [...pack.providers].sort((a, b) => a.localeCompare(b));
      window.LocalCdrBrand.preloadRailProviders(providers, pack.samples);
    });
  }

  function renderSectionCards() {
    const wrap = $('sectionCards');
    clear(wrap);
    wrap.hidden = false;
    if (!window.LocalCdrBrand) return;
    BANKING_SECTIONS.forEach((section) => {
      const card = child(wrap, 'button', 'local-section-card' + (state.section === section ? ' is-active' : ''));
      card.type = 'button';
      card.dataset.sectionCard = section;
      const head = child(card, 'span', 'local-section-card-head');
      child(head, 'span', 'local-section-kicker', section === 'TD' ? 'Term Deposits' : section);
      child(head, 'strong', '', section === 'Mortgage' ? 'Home loans' : section === 'Savings' ? 'Savings accounts' : 'Term deposits');
    });
  }

  function renderSelectedLogos(activeProviders) {
    const wrap = $('selectedLogos');
    clear(wrap);
    delete wrap._logoRailButtons;
    const sectionPayload = state.bankSections[state.section];
    if (!window.LocalCdrBrand || !sectionPayload || !sectionPayload.rates) { wrap.hidden = true; return; }

    const rows = sectionPayload.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
    const providers = [...new Set(rows.map((row) => row.provider).filter(Boolean))].sort();
    const sampleByProvider = {};
    rows.forEach((row) => { if (row.provider && !sampleByProvider[row.provider]) sampleByProvider[row.provider] = row; });
    const label = sectionDisplayLabel(state.section);

    if (window.LocalCdrBrand && window.LocalCdrBrand.preloadRailProviders) {
      window.LocalCdrBrand.preloadRailProviders(providers, sampleByProvider);
    }

    wrap.hidden = false;
    const coarse = typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches;
    const focus = String(state.focusProvider || '').toLowerCase();
    const headRow = child(wrap, 'div', 'local-selected-logos-head');
    const baseHint = coarse
      ? `${label} providers — tap to filter`
      : `${label} providers — hover to preview, click to filter`;
    const titleText = focus
      ? `Filtered: ${state.focusProvider} (1 of ${providers.length})`
      : `${baseHint} (${providers.length})`;
    child(headRow, 'span', 'local-selected-logos-title', titleText);
    if (focus) {
      const clearBtn = child(headRow, 'button', 'local-selected-logos-clear');
      clearBtn.type = 'button';
      clearBtn.dataset.providerClear = '1';
      clearBtn.setAttribute('aria-label', 'Clear provider filter');
      clearBtn.textContent = 'Clear ×';
    }
    const rail = child(wrap, 'span', 'local-section-logo-rail local-section-logo-rail-full');
    const hover = String(state.hoverProvider || '').toLowerCase();
    const active = activeProviders !== undefined ? activeProviders : relevantProviderKeys();
    providers.forEach((provider, index) => {
      const btn = child(rail, 'button', 'local-provider-logo-btn');
      btn.type = 'button';
      btn.dataset.providerPick = provider;
      const railMeta = window.LocalCdrBrand.providerMeta
        ? window.LocalCdrBrand.providerMeta(provider)
        : null;
      const railTip = window.LocalCdrBrand.providerTooltip
        ? window.LocalCdrBrand.providerTooltip(provider, railMeta)
        : provider;
      btn.title = railTip;
      btn.setAttribute('aria-label', railTip);
      const lc = provider.toLowerCase();
      const isSelected = !!(focus && lc === focus);
      btn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
      if (isSelected) btn.classList.add('is-selected');
      if (hover && lc === hover) btn.classList.add('is-hover');
      if (active) {
        const keys = providerMatchKeys(provider);
        let hit = false;
        keys.forEach((key) => { if (active.has(key)) hit = true; });
        if (!hit) btn.classList.add('is-dim');
      }
      const badge = window.LocalCdrBrand.appendProviderBadge(btn, provider, false, {
        logoOnly: true,
        suppressTitle: true,
        rateRow: sampleByProvider[provider],
        logoFetchPriority: index < 16 ? 'high' : 'low',
      });
      if (btn.classList.contains('is-dim')) badge.classList.add('is-logo-dim');
    });
  }

  // Hero "best rate" conditional caveat. Classification lives in rate-honesty.js
  // (window.LocalCdrRateHonesty) to keep this module focused.
  function setHeroLeaderNote(text) {
    const el = $('hero-leader-note');
    if (!el) return;
    if (text) {
      el.textContent = text;
      el.hidden = false;
    } else {
      el.textContent = '';
      el.hidden = true;
    }
  }

  function updateHero(rows, items) {
    $('hero-run').textContent = state.manifest.run_date;
    $('hero-rows').textContent = num(rows.length);
    const range = items && items.kind === 'bank-history' ? items.currentRange : currentRateRange(rows);
    const leader = preferredDescending(state.section) ? range.max : range.min;
    $('hero-leader').textContent = leader == null ? '-' : pct(leader);
    const honesty = window.LocalCdrRateHonesty;
    setHeroLeaderNote(leader == null || !honesty ? '' : honesty.heroNote(rows, preferredDescending(state.section)));
  }

  function renderFlatTable(rows) {
    const keys = ['provider', 'product_name', 'rate', 'rate_type', 'last_updated'];
    const visible = rows.slice(0, 1500);
    $('table-count').textContent = num(visible.length) + ' visible';
    const table = $('table');
    $('chart-side-panel').hidden = true;
    document.querySelector('.local-table-panel').hidden = false;
    table.hidden = false;
    clear(table);
    const thead = child(table, 'thead');
    const header = child(thead, 'tr');
    keys.forEach((key) => child(header, 'th', '', key));
    const tbody = child(table, 'tbody');
    visible.forEach((row) => {
      const tr = child(tbody, 'tr');
      keys.forEach((key) => child(tr, 'td', '', row[key] || ''));
    });
  }

  function renderTable(rows) {
    const hasTaxonomy = rows.length > 0 && rows.some((r) => r.taxonomy_path);
    if (hasTaxonomy || state.bankSections[state.section]) {
      $('table').hidden = true;
      document.querySelector('.local-table-panel').hidden = true;
      $('chart-side-panel').hidden = false;
      $('hierarchy').hidden = false;
      const activeProviders = relevantProviderKeys();
      state.isProviderDimmed = (provider) => isProviderDimmed(provider, activeProviders);
      window.LocalCdrHierarchy.render($('hierarchy'), $('table-count'), rows, state, hierarchyRenderOptions());
    } else {
      renderFlatTable(rows);
    }
  }

  function chartSliceRows(allRows) {
    return applyHierarchyFilter(allRows);
  }

  function syncChartRibbonState(finalRows) {
    const items = chartItems(finalRows);
    state.chartDates = items && items.kind === 'bank-history' ? (items.dates || []) : [];
    sanitizeChartDateState(state.chartDates);
    return items;
  }

  function paintChart(finalRows, items) {
    window.LocalCdrChart.draw($('chart'), items, 'banks');
    state._chartFocusPainted = focusActiveProvider();
    setHistoryWindowUi(items);
    updateHero(finalRows, items);
    if (items && items.kind === 'bank-history') {
      $('chart-status').textContent = `${num(finalRows.length)} current rows / ${num(items.totalHistoryRows)} historical rows`;
    } else {
      $('chart-status').textContent = `${num(finalRows.length)} local rate rows loaded`;
    }
  }

  function drawChartFromState(finalRows) {
    const items = syncChartRibbonState(finalRows);
    paintChart(finalRows, items);
  }

  function redrawChart() {
    drawChartFromState(chartSliceRows(normalizeRows(rateRows())));
  }

  function scheduleChartRedraw() {
    if (state._chartRedrawFrame) return;
    const raf = window.requestAnimationFrame || ((fn) => window.setTimeout(fn, 0));
    state._chartRedrawFrame = raf(() => {
      state._chartRedrawFrame = 0;
      redrawChart();
    });
  }

  /** Hover paths: skip full ECharts rebuild when ribbon focus is unchanged. */
  function redrawChartIfFocusChanged() {
    const focus = focusActiveProvider();
    if (focus === state._chartFocusPainted) return;
    redrawChart();
  }

  function renderEmptySection() {
    const label = sectionDisplayLabel(state.section);
    const emptyMsg = `No ${label} rates in export ${state.manifest.run_date}.`;
    setLinks();
    renderTable([]);
    drawChartFromState([]);
    $('chart-status').textContent = emptyMsg;
    updateHero([], null);
    renderSelectedLogos(relevantProviderKeys());
  }

  function renderRibbonBootstrap() {
    const ribbon = state.bankRibbons[ribbonCacheKey(state.section)];
    if (!ribbon) return;
    const counts = ribbon.counts || {};
    const items = ribbonChartItems(ribbon);
    if (!items) return;
    setLinks();
    $('hero-run').textContent = state.manifest.run_date;
    $('hero-rows').textContent = num(counts.rates || 0);
    const range = items && items.currentRange ? items.currentRange : { min: null, max: null };
    const leader = preferredDescending(state.section) ? range.max : range.min;
    $('hero-leader').textContent = leader == null ? '-' : pct(leader);
    setHeroLeaderNote(null);
    window.LocalCdrChart.draw($('chart'), items, 'banks');
    state._chartFocusPainted = focusActiveProvider();
    setHistoryWindowUi(items);
    $('chart-status').textContent = `${num(counts.rates || 0)} current rows / details loading`;
    $('table-count').textContent = counts.products || counts.providers
      ? `${num(counts.products || 0)} products / ${num(counts.providers || 0)} providers`
      : 'Loading details';
    $('table').hidden = true;
    document.querySelector('.local-table-panel').hidden = true;
    $('chart-side-panel').hidden = false;
    $('hierarchy').hidden = false;
    clear($('hierarchy'));
    const loading = child($('hierarchy'), 'div', 'chart-series-empty', 'Loading current slice...');
    loading.setAttribute('aria-live', 'polite');
  }

  function render() {
    const allRows = normalizeRows(rateRows());
    if (!allRows.length) {
      renderEmptySection();
      return;
    }
    const focused = applyFocusFilter(allRows);
    const chartRows = chartSliceRows(allRows);
    const chartItems = syncChartRibbonState(chartRows);
    setLinks();
    // renderTable runs the hierarchy, which sets state.focusedProductKeys via its
    // onFocusChange callback (state only — no redraw inside the callback).
    renderTable(focused);
    renderSelectedLogos(relevantProviderKeys());
    paintChart(chartRows, chartItems);
  }

  async function loadSection(section) {
    if (isEconomicDataSection(section)) {
      window.location.assign('/economic-data/');
      return;
    }
    const token = ++loadSectionToken;
    if (state.section !== section) {
      state.hierarchyPath = '';
      state.focusProvider = '';
      resetHierarchyHover();
      state.focusedProductKeys = null;
      state.chartHoverDate = '';
      state.chartPinnedDate = '';
      state.chartDates = [];
      state.descending = preferredDescending(section);
    }
    state.section = section;
    setSectionUi();
    syncSectionUrl();
    const cachedSection = state.bankSections[section];
    if (cachedSection && Array.isArray(cachedSection.rates)) {
      renderSelectedLogos(null);
      warmProviderLogoCache();
    } else {
      const logoWrap = $('selectedLogos');
      if (logoWrap) logoWrap.hidden = true;
    }
    $('chart-status').textContent = 'Loading rates';
    $('table-count').textContent = '';
    clear($('table'));
    clear($('hierarchy'));
    const ribIncludeNs = state.includeNonStandard;
    const ribKey = ribbonCacheKey(section, ribIncludeNs);
    if (!state.bankRibbons[ribKey]) {
      const encodedSection = encodeURIComponent(section);
      state.bankRibbons[ribKey] = await getJson(`/api/banks/ribbon?date=${state.manifest.run_date}&section=${encodedSection}${ribIncludeNs ? '&include_non_standard=1' : ''}`);
    }
    if (token !== loadSectionToken) return;
    renderRibbonBootstrap();
    if (!state.bankSections[section]) {
      const encodedSection = encodeURIComponent(section);
      const payload = await getJson(`/api/banks/section?date=${state.manifest.run_date}&section=${encodedSection}`);
      hydrateSectionRows(payload.rates, section, state.manifest.run_date);
      state.bankSections[section] = payload;
      warmProviderLogoCache();
    }
    if (token !== loadSectionToken) return;
    // Seed from unfiltered section rows so the current-only history retains
    // non-standard products; accountClassVisible is applied at index-build time.
    seedCurrentHistory(section, sectionRows());
    sanitizeFocusedProviders();
    render();
    loadBankHistory()
      .then(() => {
        if (token !== loadSectionToken || state.section !== section) return;
        render();
      })
      .catch((error) => {
        console.warn('History payload failed', error);
      });
  }

  function resetHierarchyHover() {
    state.hoverProvider = '';
  }

  function bind() {
    let resizeFrame = 0;
    const scheduleChartResize = () => {
      if (resizeFrame) return;
      resizeFrame = window.requestAnimationFrame(() => {
        resizeFrame = 0;
        redrawChart();
      });
    };

    document.querySelectorAll('[data-section]').forEach((el) => el.addEventListener('click', (e) => {
      // Preserve open-in-new-tab/window: skip JS handling on modified clicks
      // (Ctrl/Cmd/Shift/Alt/middle-click) so the anchor's native behaviour wins.
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) return;
      e.preventDefault();
      loadSection(el.dataset.section);
    }));

    const logoWrap = $('selectedLogos');
    logoWrap.addEventListener('click', (event) => {
      const clearBtn = event.target.closest('[data-provider-clear]');
      if (clearBtn) {
        state.focusProvider = '';
        resetHierarchyHover();
        state.hierarchyPath = '';
        state.focusedProductKeys = null;
        render();
        return;
      }
      const btn = event.target.closest('[data-provider-pick]');
      if (!btn) return;
      const pick = btn.dataset.providerPick || '';
      const current = state.focusProvider;
      state.focusProvider = (current && pick.toLowerCase() === current.toLowerCase()) ? '' : pick;
      resetHierarchyHover();
      state.hierarchyPath = '';
      state.focusedProductKeys = null;
      render();
    });
    logoWrap.addEventListener('mouseover', (event) => {
      const btn = event.target.closest('[data-provider-pick]');
      if (!btn) return;
      const next = btn.dataset.providerPick || '';
      if (state.hoverProvider === next) return;
      state.hoverProvider = next;
      logoWrap.querySelectorAll('.local-provider-logo-btn.is-hover').forEach((el) => el.classList.remove('is-hover'));
      btn.classList.add('is-hover');
      refreshProviderHighlightUi(undefined, { highlightOnly: true });
      redrawChartIfFocusChanged();
    });
    logoWrap.addEventListener('mouseleave', () => {
      if (!state.hoverProvider) return;
      resetHierarchyHover();
      logoWrap.querySelectorAll('.local-provider-logo-btn.is-hover').forEach((el) => el.classList.remove('is-hover'));
      refreshProviderHighlightUi(undefined, { highlightOnly: true });
      redrawChartIfFocusChanged();
    });

    $('hierarchy').addEventListener('click', (event) => {
      const action = event.target.closest('[data-local-hierarchy-action]');
      if (!action) return;
      state.hierarchyPath = action.dataset.localHierarchyPath || '';
      resetHierarchyHover();
      renderTable(applyFocusFilter(normalizeRows(rateRows())));
      redrawChart();
    });
    $('hierarchy').addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const action = event.target.closest('[data-local-hierarchy-action]');
      if (!action) return;
      event.preventDefault();
      state.hierarchyPath = action.dataset.localHierarchyPath || '';
      resetHierarchyHover();
      renderTable(applyFocusFilter(normalizeRows(rateRows())));
      redrawChart();
    });
    $('chart-toggle-sort').addEventListener('click', () => {
      state.descending = !state.descending;
      $('chart-toggle-sort').textContent = state.descending ? 'Lowest first' : 'Highest first';
      render();
    });
    const nonStandardToggle = $('chart-toggle-nonstandard');
    if (nonStandardToggle) {
      nonStandardToggle.checked = state.includeNonStandard;
      nonStandardToggle.addEventListener('change', () => {
        state.includeNonStandard = nonStandardToggle.checked;
        // The history index is built through historyRowMatchesLiveTable, which now
        // honours the toggle — rebuild it so non-standard series appear/disappear.
        refreshBankHistoryIndex();
        // Hiding non-standard rows can strand a provider focus/hover that only
        // matched a now-hidden product; drop it so the table/hierarchy aren't
        // left empty (Codex P2).
        sanitizeFocusedProviders();
        render();
      });
    }
    document.querySelectorAll('[data-history-window]').forEach((button) => {
      button.addEventListener('click', () => {
        state.historyWindow = button.dataset.historyWindow || '30D';
        render();
      });
    });
    const workspaceResizeHandle = document.getElementById('chart-workspace-resizer');
    if (workspaceResizeHandle) {
      window.addEventListener('pointermove', () => {
        if (document.body.classList.contains('is-resizing-chart-workspace')) scheduleChartResize();
      });
      ['pointerup', 'pointercancel', 'dblclick', 'keydown', 'keyup'].forEach((eventName) => {
        workspaceResizeHandle.addEventListener(eventName, scheduleChartResize);
      });
    }
    window.addEventListener('resize', () => {
      scheduleChartResize();
    });
    window.addEventListener('ar:theme-changed', () => redrawChart());
    if (window.ARTheme && window.ARTheme.initToggles) window.ARTheme.initToggles(document);
  }

  async function init() {
    state.manifest = await getJson('/api/latest', { cache: 'no-store' });
    state.manifestSignature = manifestSignature(state.manifest);
    loadIngestSchedule();
    loadRealtimeSectionData();
    bind();
    await loadSection(sectionFromPathname());
  }

  init().catch((error) => {
    clear(document.body);
    const pre = child(document.body, 'pre', 'panel', error.stack || error.message || error);
    pre.style.margin = '20px';
  });
})();
