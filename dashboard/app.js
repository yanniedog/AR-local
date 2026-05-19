(function () {
  'use strict';

  /** Banking sections only; Economic Data is the public /economic-data/ page (macro API, not energy CDR). */
  const SECTION = {
    Mortgage: 'Mortgage',
    Savings: 'Savings',
    TD: 'TD',
    EconomicData: 'EconomicData',
  };

  function isEconomicDataSection(section) {
    return section === SECTION.EconomicData;
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
    banks: null,
    bankHistory: null,
    bankHistoryIndex: null,
    descending: false,
    historyWindow: '30D',
    hierarchyPath: '',
    focusProvider: '',
    hoverProvider: '',
    focusedProductKeys: null,
    chartHoverDate: '',
    chartDates: [],
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

  async function getJson(url) {
    const response = await fetch(url, { cache: 'force-cache' });
    if (!response.ok) throw new Error(url + ' returned ' + response.status);
    return response.json();
  }

  function num(value) {
    return Number(value || 0).toLocaleString('en-AU');
  }

  function rateRows() {
    if (!state.banks) return [];
    return state.banks.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
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

  function rowProductKey(row) {
    return row.product_key || row.product_id || row.plan_id || row.product_name || row.plan_name || '';
  }

  function applyHierarchyFilter(rows) {
    if (!state.focusedProductKeys) return rows;
    const allowed = state.focusedProductKeys;
    return rows.filter((row) => allowed.has(rowProductKey(row)));
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
    if (state.bankHistory) return;
    const data = await getJson(`/api/banks/history?date=${state.manifest.run_date}`);
    const rates = Array.isArray(data.rates) ? normalizeRows(data.rates) : [];
    state.bankHistory = {
      ...data,
      rates,
      run_dates: Array.isArray(data.run_dates) ? data.run_dates : [],
    };
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
      onHoverDateChange: onChartHoverDate,
    };
  }

  function onChartHoverDate(dateYmd) {
    const next = String(dateYmd || '').slice(0, 10);
    if (state.chartHoverDate === next) return;
    state.chartHoverDate = next;
    refreshProviderHighlightUi();
  }

  function visibleSliceRows() {
    return chartSliceRows(applyFocusFilter(normalizeRows(rateRows())));
  }

  function relevantProviderKeys() {
    const hover = String(state.hoverProvider || '').trim();
    if (hover) return providerMatchKeys(hover);
    const focus = String(state.focusProvider || '').trim();
    if (focus) return providerMatchKeys(focus);
    const rows = visibleSliceRows();
    const dates = Array.isArray(state.chartDates) ? state.chartDates : [];
    const anchor = String(state.chartHoverDate || (dates.length ? dates[dates.length - 1] : '')).slice(0, 10);
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

  function refreshProviderHighlightUi(activeProviders) {
    const active = activeProviders !== undefined ? activeProviders : relevantProviderKeys();
    refreshHierarchyPanel(active);
    renderSelectedLogos(active);
  }

  function refreshHierarchyPanel(activeProviders) {
    if (!$('hierarchy') || $('hierarchy').hidden) return;
    const rows = applyFocusFilter(normalizeRows(rateRows()));
    const active = activeProviders !== undefined ? activeProviders : relevantProviderKeys();
    state.isProviderDimmed = (provider) => isProviderDimmed(provider, active);
    window.LocalCdrHierarchy.render($('hierarchy'), $('table-count'), rows, state, {
      onFocusChange: (productKeys) => {
        state.focusedProductKeys = productKeys && productKeys.size ? productKeys : null;
      },
    });
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

  function renderSectionCards() {
    const wrap = $('sectionCards');
    clear(wrap);
    wrap.hidden = false;
    if (!state.banks || !window.LocalCdrBrand) return;
    ['Mortgage', 'Savings', 'TD'].forEach((section) => {
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
    if (!window.LocalCdrBrand || !state.banks || !state.banks.rates) { wrap.hidden = true; return; }

    const rows = state.banks.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
    const providers = [...new Set(rows.map((row) => row.provider).filter(Boolean))].sort();
    const sampleByProvider = {};
    rows.forEach((row) => { if (row.provider && !sampleByProvider[row.provider]) sampleByProvider[row.provider] = row; });
    const label = state.section === SECTION.TD ? 'Term Deposit' : state.section;

    wrap.hidden = false;
    child(wrap, 'span', 'local-selected-logos-title', `${label} providers — hover to preview, click to filter`);
    const rail = child(wrap, 'span', 'local-section-logo-rail local-section-logo-rail-full');
    const focus = String(state.focusProvider || '').toLowerCase();
    const hover = String(state.hoverProvider || '').toLowerCase();
    const active = activeProviders !== undefined ? activeProviders : relevantProviderKeys();
    providers.forEach((provider) => {
      const btn = child(rail, 'button', 'local-provider-logo-btn');
      btn.type = 'button';
      btn.dataset.providerPick = provider;
      btn.title = provider;
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
        rateRow: sampleByProvider[provider],
      });
      if (btn.classList.contains('is-dim')) badge.classList.add('is-logo-dim');
    });
  }

  function updateHero(rows, items) {
    $('hero-run').textContent = state.manifest.run_date;
    $('hero-rows').textContent = num(rows.length);
    const range = items && items.kind === 'bank-history' ? items.currentRange : currentRateRange(rows);
    const leader = state.descending ? range.max : range.min;
    $('hero-leader').textContent = leader == null ? '-' : pct(leader);
  }

  function renderStats(rows) {
    const counts = state.manifest.banks_counts;
    const entries = Object.entries(counts).slice(0, 6).concat([['visible rows', rows.length]]);
    const stats = $('stats');
    clear(stats);
    entries.forEach(([key, value]) => {
      const card = child(stats, 'div', 'terminal-stat');
      child(card, 'span', 'metric-code', key);
      child(card, 'strong', '', num(value));
    });
  }

  function renderFlatTable(rows) {
    const keys = ['provider', 'plan_name', 'fuel_type', 'last_updated', 'description'];
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
    if (hasTaxonomy || state.banks) {
      $('table').hidden = true;
      document.querySelector('.local-table-panel').hidden = true;
      $('chart-side-panel').hidden = false;
      $('hierarchy').hidden = false;
      const activeProviders = relevantProviderKeys();
      state.isProviderDimmed = (provider) => isProviderDimmed(provider, activeProviders);
      window.LocalCdrHierarchy.render($('hierarchy'), $('table-count'), rows, state, {
        onFocusChange: (productKeys) => {
          state.focusedProductKeys = productKeys && productKeys.size ? productKeys : null;
        },
      });
    } else {
      renderFlatTable(rows);
    }
  }

  function chartSliceRows(allRows) {
    return applyHierarchyFilter(allRows);
  }

  function drawChartFromState(finalRows) {
    const items = chartItems(finalRows);
    state.chartDates = items && items.kind === 'bank-history' ? (items.dates || []) : [];
    if (!state.chartHoverDate && state.chartDates.length) {
      state.chartHoverDate = state.chartDates[state.chartDates.length - 1];
    }
    window.LocalCdrChart.draw($('chart'), items, 'banks');
    setHistoryWindowUi(items);
    updateHero(finalRows, items);
    if (items && items.kind === 'bank-history') {
      $('chart-status').textContent = `${num(finalRows.length)} current rows / ${num(items.totalHistoryRows)} historical rows`;
    } else {
      $('chart-status').textContent = `${num(finalRows.length)} local rate rows loaded`;
    }
  }

  function redrawChart() {
    drawChartFromState(chartSliceRows(normalizeRows(rateRows())));
  }

  function renderEmptySection() {
    const label = state.section === SECTION.TD ? 'Term Deposits' : state.section;
    const emptyMsg = `No ${label} rates in export ${state.manifest.run_date}.`;
    setLinks();
    renderStats([]);
    renderTable([]);
    drawChartFromState([]);
    $('chart-status').textContent = emptyMsg;
    updateHero([], null);
    renderSectionCards();
    renderSelectedLogos(relevantProviderKeys());
  }

  function render() {
    const allRows = normalizeRows(rateRows());
    if (!allRows.length) {
      renderEmptySection();
      return;
    }
    const focused = applyFocusFilter(allRows);
    setLinks();
    renderStats(focused);
    // renderTable runs the hierarchy, which sets state.focusedProductKeys via its
    // onFocusChange callback (state only — no redraw inside the callback).
    renderTable(focused);
    drawChartFromState(chartSliceRows(allRows));
    renderSelectedLogos(relevantProviderKeys());
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
      state.hoverProvider = '';
      state.focusedProductKeys = null;
      state.chartHoverDate = '';
      state.chartDates = [];
    }
    state.section = section;
    state.descending = preferredDescending(section);
    setSectionUi();
    syncSectionUrl();
    $('chart-status').textContent = 'Loading local CDR data';
    $('table-count').textContent = '';
    clear($('table'));
    clear($('hierarchy'));
    if (!state.banks) state.banks = await getJson(`/api/banks?date=${state.manifest.run_date}`);
    if (token !== loadSectionToken) return;
    await loadBankHistory();
    if (token !== loadSectionToken) return;
    refreshBankHistoryIndex();
    renderSectionCards();
    render();
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

    $('sectionCards').addEventListener('click', (event) => {
      const card = event.target.closest('[data-section-card]');
      if (card) loadSection(card.dataset.sectionCard);
    });

    const logoWrap = $('selectedLogos');
    logoWrap.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-provider-pick]');
      if (!btn) return;
      const pick = btn.dataset.providerPick || '';
      const current = state.focusProvider;
      state.focusProvider = (current && pick.toLowerCase() === current.toLowerCase()) ? '' : pick;
      state.hoverProvider = '';
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
      refreshProviderHighlightUi();
      redrawChart();
    });
    logoWrap.addEventListener('mouseleave', () => {
      if (!state.hoverProvider) return;
      state.hoverProvider = '';
      logoWrap.querySelectorAll('.local-provider-logo-btn.is-hover').forEach((el) => el.classList.remove('is-hover'));
      refreshProviderHighlightUi();
      redrawChart();
    });

    $('hierarchy').addEventListener('click', (event) => {
      const action = event.target.closest('[data-local-hierarchy-action]');
      if (!action) return;
      state.hierarchyPath = action.dataset.localHierarchyPath || '';
      renderTable(applyFocusFilter(normalizeRows(rateRows())));
      redrawChart();
    });
    $('hierarchy').addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const action = event.target.closest('[data-local-hierarchy-action]');
      if (!action) return;
      event.preventDefault();
      state.hierarchyPath = action.dataset.localHierarchyPath || '';
      renderTable(applyFocusFilter(normalizeRows(rateRows())));
      redrawChart();
    });
    $('hierarchy').addEventListener('mouseover', (event) => {
      const node = event.target.closest('[data-local-hierarchy-action]');
      if (!node) return;
      const provider = node.getAttribute('data-local-hierarchy-provider') || '';
      if (provider && provider !== state.hoverProvider) {
        state.hoverProvider = provider;
        refreshProviderHighlightUi();
        redrawChart();
      }
    });
    $('hierarchy').addEventListener('mouseleave', () => {
      if (state.hoverProvider) {
        state.hoverProvider = '';
        refreshProviderHighlightUi();
        redrawChart();
      }
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
    state.manifest = await getJson('/api/latest');
    bind();
    await loadSection(sectionFromPathname());
  }

  init().catch((error) => {
    clear(document.body);
    const pre = child(document.body, 'pre', 'panel', error.stack || error.message || error);
    pre.style.margin = '20px';
  });
})();
