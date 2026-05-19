(function () {
  'use strict';

  const state = {
    section: 'Mortgage',
    sector: 'banks',
    manifest: null,
    banks: null,
    bankHistory: null,
    bankHistoryIndex: null,
    energy: null,
    descending: false,
    historyWindow: '30D',
    hierarchyPath: '',
    focusProvider: '',
    hoverProvider: '',
    focusedProductKeys: null,
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
    if (state.sector === 'banks') {
      if (!state.banks) return [];
      return state.banks.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
    }
    if (!state.energy) return [];
    return state.energy.plans.slice();
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

  function refreshBankHistoryIndex() {
    if (!state.bankHistory) return;
    state.bankHistoryIndex = buildHistoryIndex(state.bankHistory.rates);
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
    const allDates = new Set();
    const byDate = {};
    historyRows.forEach((row) => {
      const date = String(row.run_date || '');
      const provider = row.provider || 'Unknown';
      const rate = Number(row.rate);
      if (!date || !Number.isFinite(rate) || rate <= 0) return;
      allDates.add(date);
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
    const dates = historyDatesInWindow(Array.from(allDates));
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
    return { dates, points, providers, allDates: Array.from(allDates).sort() };
  }

  function chartItems(rows) {
    if (state.sector === 'energy') {
      const counts = {};
      rows.forEach((row) => { if (row.provider) counts[row.provider] = (counts[row.provider] || 0) + 1; });
      return {
        kind: 'energy-counts',
        items: Object.entries(counts)
          .map(([label, value]) => ({ label, value }))
          .sort((a, b) => state.descending ? b.value - a.value : a.value - b.value)
          .slice(0, 30),
        focusProvider: focusActiveProvider(),
        descending: state.descending,
      };
    }
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
    };
  }

  function setLinks() {
    const date = state.manifest.run_date;
    const json = `/exports/${state.sector}-${date}.json`;
    const xlsx = `/exports/${state.sector}-${date}.xlsx`;
    $('jsonLink').href = json;
    $('xlsxLink').href = xlsx;
    $('footerJsonLink').href = json;
    $('footerXlsxLink').href = xlsx;
  }

  function setSectionUi() {
    document.body.classList.toggle('ar-section-home-loans',   state.section === 'Mortgage');
    document.body.classList.toggle('ar-section-savings',      state.section === 'Savings');
    document.body.classList.toggle('ar-section-term-deposits',state.section === 'TD');
    document.body.classList.toggle('ar-section-economic-data',state.section === 'Energy');
    const slug = state.section === 'Savings' ? 'savings' : state.section === 'TD' ? 'term-deposits' : state.section === 'Energy' ? 'economic-data' : 'home-loans';
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
      Energy:   'Australian Energy Plans - Daily CDR Data | AustralianRates',
    };
    document.title = pageTitles[state.section] || pageTitles.Mortgage;
    const titles = { Mortgage: 'Home loan rates, tracked.', Savings: 'Savings rates, tracked.', TD: 'Term deposit yields, tracked.', Energy: 'Energy plans, tracked.' };
    $('page-title').textContent = titles[state.section] || titles.Mortgage;
    const leaderLabels = { Mortgage: 'Lowest rate', Savings: 'Top yield', TD: 'Top yield', Energy: 'Plans' };
    const focusLabels  = { Mortgage: 'Lowest rates', Savings: 'Top yields', TD: 'Top yields', Energy: 'Plan count' };
    $('hero-leader-label').textContent = leaderLabels[state.section] || leaderLabels.Mortgage;
    $('chart-focus').textContent = focusLabels[state.section] || focusLabels.Mortgage;
    $('chart-toggle-sort').textContent = state.descending ? 'Lowest first' : 'Highest first';

    const isBanks = state.sector === 'banks';
    const isEnergy = state.sector === 'energy';
    document.querySelectorAll('.local-history-window, .local-history-window-status')
      .forEach((el) => { el.hidden = !isBanks; });

    const heroGrid = document.querySelector('.market-intro-live-grid');
    if (heroGrid) heroGrid.hidden = isEnergy;
    const sectionCards = $('sectionCards');
    if (sectionCards) sectionCards.hidden = isEnergy;
    const selectedLogos = $('selectedLogos');
    if (selectedLogos && isEnergy) selectedLogos.hidden = true;
    const chartQuestionRow = document.querySelector('.chart-question-row');
    if (chartQuestionRow) chartQuestionRow.hidden = isEnergy;
  }

  function setHistoryWindowUi(items) {
    document.querySelectorAll('[data-history-window]').forEach((button) => {
      const active = button.dataset.historyWindow === state.historyWindow;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const status = $('history-window-status');
    if (!status || state.sector !== 'banks') return;
    if (!items || items.kind !== 'bank-history' || !items.dates.length) {
      status.textContent = 'Historical ribbon: no retained run data for this slice.';
      return;
    }
    const first = items.dates[0];
    const last = items.dates[items.dates.length - 1];
    const label = first === last ? first : `${first} through ${last}`;
    status.textContent = `Visible window: ${label}. ${num(items.allDates.length)} retained run date${items.allDates.length === 1 ? '' : 's'}.`;
  }

  function renderSectionCards() {
    const wrap = $('sectionCards');
    clear(wrap);
    if (state.sector === 'energy') {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    if (!state.banks || !window.LocalCdrBrand) return;
    ['Mortgage', 'Savings', 'TD'].forEach((section) => {
      const rows = state.banks.rates.filter((row) => row.dataset === section && bankRateMatchesSection(row));
      const products = new Set(rows.map((row) => row.product_key || row.product_id || row.product_name));
      const providers = [...new Set(rows.map((row) => row.provider).filter(Boolean))].sort();
      const card = child(wrap, 'button', 'local-section-card' + (state.section === section ? ' is-active' : ''));
      card.type = 'button';
      card.dataset.sectionCard = section;
      const head = child(card, 'span', 'local-section-card-head');
      child(head, 'span', 'local-section-kicker', section === 'TD' ? 'Term Deposits' : section);
      child(head, 'strong', '', section === 'Mortgage' ? 'Home loans' : section === 'Savings' ? 'Savings accounts' : 'Term deposits');
      child(card, 'span', 'local-section-card-meta', `${num(rows.length)} rates / ${num(products.size)} products / ${num(providers.length)} providers`);
    });
  }

  function renderSelectedLogos() {
    const wrap = $('selectedLogos');
    clear(wrap);
    if (state.sector === 'energy') {
      wrap.hidden = true;
      return;
    }
    if (!window.LocalCdrBrand) { wrap.hidden = true; return; }

    let providers, label, sampleByProvider = {};
    if (state.sector === 'banks' && state.banks && state.banks.rates) {
      const rows = state.banks.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
      providers = [...new Set(rows.map((row) => row.provider).filter(Boolean))].sort();
      rows.forEach((row) => { if (row.provider && !sampleByProvider[row.provider]) sampleByProvider[row.provider] = row; });
      label = state.section === 'TD' ? 'Term Deposit' : state.section;
    } else {
      wrap.hidden = true;
      return;
    }

    wrap.hidden = false;
    child(wrap, 'span', 'local-selected-logos-title', `${label} providers — hover to preview, click to filter`);
    const rail = child(wrap, 'span', 'local-section-logo-rail local-section-logo-rail-full');
    const focus = String(state.focusProvider || '').toLowerCase();
    const hover = String(state.hoverProvider || '').toLowerCase();
    providers.forEach((provider) => {
      const btn = child(rail, 'button', 'local-provider-logo-btn');
      btn.type = 'button';
      btn.dataset.providerPick = provider;
      btn.title = provider;
      const lc = provider.toLowerCase();
      if (focus && lc === focus) btn.classList.add('is-selected');
      if (hover && lc === hover) btn.classList.add('is-hover');
      window.LocalCdrBrand.appendProviderBadge(btn, provider, false, { logoOnly: true, rateRow: sampleByProvider[provider] });
    });
  }

  function updateHero(rows, items) {
    if (state.sector === 'energy') return;
    $('hero-run').textContent = state.manifest.run_date;
    $('hero-rows').textContent = num(rows.length);
    if (state.sector === 'banks') {
      const range = items && items.kind === 'bank-history' ? items.currentRange : currentRateRange(rows);
      const leader = state.descending ? range.max : range.min;
      $('hero-leader').textContent = leader == null ? '-' : pct(leader);
    } else {
      $('hero-leader').textContent = num(rows.length);
    }
  }

  function renderStats(rows) {
    const counts = state.sector === 'banks' ? state.manifest.banks_counts : state.manifest.energy_counts;
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
    if (state.sector === 'banks' || state.sector === 'energy' || hasTaxonomy) {
      $('table').hidden = true;
      document.querySelector('.local-table-panel').hidden = true;
      $('chart-side-panel').hidden = false;
      $('hierarchy').hidden = false;
      // Callback only updates state; the chart redraw is driven by the caller.
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
    window.LocalCdrChart.draw($('chart'), items, state.sector);
    setHistoryWindowUi(items);
    updateHero(finalRows, items);
    if (state.sector === 'banks' && items && items.kind === 'bank-history') {
      $('chart-status').textContent = `${num(finalRows.length)} current rows / ${num(items.totalHistoryRows)} historical rows`;
    } else if (state.sector === 'energy' && items && items.kind === 'energy-counts') {
      $('chart-status').textContent = `${num(finalRows.length)} plans / ${num(items.items.length)} providers in chart`;
    } else {
      $('chart-status').textContent = `${num(finalRows.length)} local ${state.sector === 'banks' ? 'rate rows' : 'plans'} loaded`;
    }
  }

  function redrawChart() {
    drawChartFromState(chartSliceRows(normalizeRows(rateRows())));
  }

  function render() {
    const allRows = normalizeRows(rateRows());
    const focused = applyFocusFilter(allRows);
    setLinks();
    renderStats(focused);
    // renderTable runs the hierarchy, which sets state.focusedProductKeys via its
    // onFocusChange callback (state only — no redraw inside the callback).
    renderTable(focused);
    drawChartFromState(chartSliceRows(allRows));
    renderSelectedLogos();
  }

  async function loadSection(section) {
    if (state.section !== section) {
      state.hierarchyPath = '';
      state.focusProvider = '';
      state.hoverProvider = '';
      state.focusedProductKeys = null;
    }
    state.section = section;
    state.sector  = section === 'Energy' ? 'energy' : 'banks';
    state.descending = preferredDescending(section);
    setSectionUi();
    $('chart-status').textContent = 'Loading local CDR data';
    $('table-count').textContent = '';
    clear($('table'));
    clear($('hierarchy'));
    if (!state[state.sector]) state[state.sector] = await getJson(`/api/${state.sector}?date=${state.manifest.run_date}`);
    if (state.sector === 'banks') {
      await loadBankHistory();
      refreshBankHistoryIndex();
    }
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
      redrawChart();
    });
    logoWrap.addEventListener('mouseleave', () => {
      if (!state.hoverProvider) return;
      state.hoverProvider = '';
      logoWrap.querySelectorAll('.local-provider-logo-btn.is-hover').forEach((el) => el.classList.remove('is-hover'));
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
        redrawChart();
      }
    });
    $('hierarchy').addEventListener('mouseleave', () => {
      if (state.hoverProvider) {
        state.hoverProvider = '';
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
    await loadSection('Mortgage');
  }

  init().catch((error) => {
    clear(document.body);
    const pre = child(document.body, 'pre', 'panel', error.stack || error.message || error);
    pre.style.margin = '20px';
  });
})();
