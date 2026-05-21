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
    bankRibbons: {},
    bankSections: {},
    bankHistory: null,
    bankHistorySection: '',
    bankHistoryIndex: null,
    retainedRunDatesSorted: [],
    descending: false,
    historyWindow: '30D',
    hierarchyPath: '',
    focusProvider: '',
    hoverProvider: '',
    hoverHierarchyPath: '',
    hoverHierarchyProductKeys: null,
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

  function rateRows() {
    const sectionPayload = state.bankSections[state.section];
    if (!sectionPayload || !Array.isArray(sectionPayload.rates)) return [];
    return sectionPayload.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
  }

  function focusActiveProvider() {
    if (hasHierarchyHover()) {
      return String(state.focusProvider || '').trim();
    }
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
    const hover = hasHierarchyHover() ? state.hoverHierarchyProductKeys : null;
    const focus = hover ? null : state.focusedProductKeys;
    const keys = hover || focus;
    if (!keys) return rows;
    return rows.filter((row) => keys.has(rowProductKey(row)));
  }

  function historyRowMatchesLiveTable(row) {
    return row.dataset === state.section && bankRateMatchesSection(row);
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
    state.retainedRunDatesSorted = raw
      .map((date) => String(date || ''))
      .filter((date) => parseYmd(date) != null)
      .sort();
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
      run_dates: Array.isArray(data.run_dates) ? data.run_dates : [],
    };
    state.bankHistorySection = sectionName;
    refreshBankHistoryIndex();
  }

  function seedCurrentHistory(section, rows) {
    const normalized = normalizeRows(rows || []);
    state.bankHistory = {
      run_dates: state.manifest && state.manifest.run_date ? [state.manifest.run_date] : [],
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

  function buildAggregateRibbon(historyRows) {
    const byProvider = {};
    const sliceDates = new Set();
    const byDate = {};
    historyRows.forEach((row) => {
      const date = String(row.run_date || '');
      const provider = row.provider || 'Unknown';
      const rate = Number(row.rate);
      if (!date || !Number.isFinite(rate) || rate <= 0) return;
      sliceDates.add(date);
      if (!byProvider[provider]) byProvider[provider] = { label: provider, byDate: {} };
      const p = byProvider[provider];
      const existing = p.byDate[date];
      p.byDate[date] = existing
        ? { min: Math.min(existing.min, rate), max: Math.max(existing.max, rate), count: existing.count + 1, sum: existing.sum + rate }
        : { min: rate, max: rate, count: 1, sum: rate };
      const agg = byDate[date];
      byDate[date] = agg
        ? { min: Math.min(agg.min, rate), max: Math.max(agg.max, rate), sum: agg.sum + rate, count: agg.count + 1 }
        : { min: rate, max: rate, sum: rate, count: 1 };
    });
    const retained = retainedRunDates();
    const sliceDatesSorted = Array.from(sliceDates).sort();
    const timelineSource = retained.length ? retained : sliceDatesSorted;
    const dates = historyDatesInWindow(timelineSource);
    const points = dates.map((date) => {
      const agg = byDate[date];
      if (!agg) return { date, min: null, max: null, mean: null, count: 0 };
      return { date, min: agg.min, max: agg.max, mean: agg.sum / Math.max(1, agg.count), count: agg.count };
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
    const date = String(ribbon.run_date);
    const range = ribbon.range || {};
    const providers = (ribbon.providers || []).map((row) => ({
      label: row.provider || 'Unknown',
      byDate: {
        [date]: {
          min: Number(row.min),
          max: Number(row.max),
          mean: Number(row.mean),
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
    if (hover && !hasHierarchyHover()) {
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

  function renderHierarchySlicePreview() {
    if (!$('hierarchy') || $('hierarchy').hidden) return;
    state._hierarchySlicePreview = true;
    try {
      refreshHierarchyPanel(undefined, { slicePreview: true });
      scheduleChartRedraw();
    } finally {
      state._hierarchySlicePreview = false;
    }
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
      Mortgage: 'Compare Australian Home Loan Rates - Daily CDR Data | AustralianRates',
      Savings:  'Compare Australian Savings Rates - Daily CDR Data | AustralianRates',
      TD:       'Compare Australian Term Deposit Rates - Daily CDR Data | AustralianRates',
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
      el.textContent = 'Next ingest: unavailable';
      return;
    }
    if (state.ingestScheduleFetchedAtMs && Date.now() - state.ingestScheduleFetchedAtMs > 15 * 60 * 1000) {
      el.textContent = 'Next ingest: schedule stale';
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
    el.textContent = `Next ingest in ${formatCountdown(remaining)} (${nextText})`;
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
    child(wrap, 'span', 'local-selected-logos-title', `${label} providers — hover to preview, click to filter`);
    const rail = child(wrap, 'span', 'local-section-logo-rail local-section-logo-rail-full');
    const focus = String(state.focusProvider || '').toLowerCase();
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
      if (focus && lc === focus) btn.classList.add('is-selected');
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

  function updateHero(rows, items) {
    $('hero-run').textContent = state.manifest.run_date;
    $('hero-rows').textContent = num(rows.length);
    const range = items && items.kind === 'bank-history' ? items.currentRange : currentRateRange(rows);
    const leader = preferredDescending(state.section) ? range.max : range.min;
    $('hero-leader').textContent = leader == null ? '-' : pct(leader);
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
    if (!state.chartHoverDate && state.chartDates.length) {
      state.chartHoverDate = state.chartDates[state.chartDates.length - 1];
    }
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
    const ribbon = state.bankRibbons[state.section];
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
    }
    state.section = section;
    state.descending = preferredDescending(section);
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
    $('chart-status').textContent = 'Loading local CDR data';
    $('table-count').textContent = '';
    clear($('table'));
    clear($('hierarchy'));
    if (!state.bankRibbons[section]) {
      const encodedSection = encodeURIComponent(section);
      state.bankRibbons[section] = await getJson(`/api/banks/ribbon?date=${state.manifest.run_date}&section=${encodedSection}`);
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
    seedCurrentHistory(section, rateRows());
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

  function hasHierarchyHover() {
    return !!(state.hoverHierarchyProductKeys && state.hoverHierarchyProductKeys.size);
  }

  function clearHierarchyHoverState() {
    state.hoverHierarchyPath = '';
    state.hoverHierarchyProductKeys = null;
  }

  function resetHierarchyHover() {
    state.hoverProvider = '';
    clearHierarchyHoverState();
    lastHierarchyHoverSignature = '';
  }

  function hierarchyHoverDomSignature(node) {
    const path = node.getAttribute('data-ribbon-tree-path')
      || node.getAttribute('data-local-hierarchy-path')
      || '';
    const provider = node.getAttribute('data-local-hierarchy-provider') || '';
    const productKey = node.getAttribute('data-local-hierarchy-product-key') || '';
    return `${path}|${provider}|${productKey}`;
  }

  let lastHierarchyHoverSignature = '';
  let hierarchyHoverDebounceTimer = 0;

  function resolveHierarchyHoverProductKeys(node, tree, hierarchyEl) {
    const productKey = node.getAttribute('data-local-hierarchy-product-key') || '';
    if (productKey) return new Set([rowProductKey({ product_key: productKey })]);
    const path = node.getAttribute('data-ribbon-tree-path')
      || node.getAttribute('data-local-hierarchy-path')
      || '';
    if (!path || !tree || !window.LocalCdrHierarchy || !window.LocalCdrHierarchy.productKeysAtPath) {
      return null;
    }
    if (hierarchyEl) {
      if (!hierarchyEl.__localHierarchyPathKeys) hierarchyEl.__localHierarchyPathKeys = new Map();
      const cached = hierarchyEl.__localHierarchyPathKeys.get(path);
      if (cached) return cached;
      const keys = window.LocalCdrHierarchy.productKeysAtPath(tree, path);
      if (keys) hierarchyEl.__localHierarchyPathKeys.set(path, keys);
      return keys;
    }
    return window.LocalCdrHierarchy.productKeysAtPath(tree, path);
  }

  function applyHierarchyTableHover(node) {
    const domSig = hierarchyHoverDomSignature(node);
    if (domSig === lastHierarchyHoverSignature) return;
    const hierarchyEl = $('hierarchy');
    const tree = hierarchyEl && hierarchyEl.__localHierarchyTree;
    const path = node.getAttribute('data-ribbon-tree-path')
      || node.getAttribute('data-local-hierarchy-path')
      || '';
    const provider = node.getAttribute('data-local-hierarchy-provider') || '';
    const productKeys = resolveHierarchyHoverProductKeys(node, tree, hierarchyEl);
    state.hoverHierarchyPath = path;
    state.hoverHierarchyProductKeys = productKeys;
    state.hoverProvider = provider;
    lastHierarchyHoverSignature = domSig;
    refreshProviderHighlightUi(undefined, { highlightOnly: true });
    renderHierarchySlicePreview();
  }

  function scheduleHierarchyTableHover(node) {
    if (hierarchyHoverDebounceTimer) clearTimeout(hierarchyHoverDebounceTimer);
    hierarchyHoverDebounceTimer = window.setTimeout(() => {
      hierarchyHoverDebounceTimer = 0;
      applyHierarchyTableHover(node);
    }, 100);
  }

  function clearHierarchyTableHover() {
    if (hierarchyHoverDebounceTimer) {
      clearTimeout(hierarchyHoverDebounceTimer);
      hierarchyHoverDebounceTimer = 0;
    }
    if (!state.hoverProvider && !state.hoverHierarchyProductKeys && !state.hoverHierarchyPath) return;
    resetHierarchyHover();
    lastHierarchyHoverSignature = '';
    refreshProviderHighlightUi(undefined, { highlightOnly: true });
    renderHierarchySlicePreview();
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
      e.preventDefault();
      loadSection(el.dataset.section);
    }));

    const logoWrap = $('selectedLogos');
    logoWrap.addEventListener('click', (event) => {
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
      if (state.hoverProvider === next && !hasHierarchyHover()) return;
      state.hoverProvider = next;
      clearHierarchyHoverState();
      lastHierarchyHoverSignature = '';
      logoWrap.querySelectorAll('.local-provider-logo-btn.is-hover').forEach((el) => el.classList.remove('is-hover'));
      btn.classList.add('is-hover');
      refreshProviderHighlightUi(undefined, { highlightOnly: true });
      redrawChartIfFocusChanged();
    });
    logoWrap.addEventListener('mouseleave', () => {
      if (!state.hoverProvider && !state.hoverHierarchyProductKeys) return;
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
    loadIngestSchedule();
    bind();
    await loadSection(sectionFromPathname());
  }

  init().catch((error) => {
    clear(document.body);
    const pre = child(document.body, 'pre', 'panel', error.stack || error.message || error);
    pre.style.margin = '20px';
  });
})();
