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

  function filterVal(id) {
    const el = $(id);
    return el ? el.value.trim() : '';
  }

  function rateRows() {
    const filters = bankFilterValues();
    if (state.sector === 'banks') {
      if (!state.banks) return [];
      return state.banks.rates.filter((row) => matchesBankFilters(row, filters));
    }
    const provider = filters.provider;
    const q = filters.q;
    if (!state.energy) return [];
    return state.energy.plans.filter((row) =>
      (!provider || String(row.provider || '').toLowerCase().includes(provider)) &&
      (!q        || String(row.plan_name || '').toLowerCase().includes(q))
    );
  }

  function bankFilterValues() {
    return {
      q: filterVal('query').toLowerCase(),
      provider: filterVal('provider').toLowerCase(),
      dataset: state.section === 'Energy' ? '' : filterVal('dataset'),
      purpose: filterVal('filter-purpose'),
      repay: filterVal('filter-repayment'),
      struct: filterVal('filter-structure'),
      term: filterVal('filter-term'),
      rateType: filterVal('filter-rate-type'),
    };
  }

  function matchesBankFilters(row, filters, options) {
    const skipQuery = options && options.skipQuery;
    return (!filters.dataset || row.dataset === filters.dataset) &&
      bankRateMatchesSection(row) &&
      (!filters.provider || String(row.provider || '').toLowerCase().includes(filters.provider)) &&
      (skipQuery || !filters.q || String(row.product_name || '').toLowerCase().includes(filters.q)) &&
      (!filters.purpose || row.security_purpose === filters.purpose) &&
      (!filters.repay || row.ribbon_repayment_type === filters.repay) &&
      (!filters.struct || row.rate_type === filters.struct) &&
      (!filters.term || String(Math.round(Number(row.term_months)) || '') === filters.term) &&
      (!filters.rateType || row.ribbon_deposit_kind === filters.rateType);
  }

  function buildHistoryIndex(rows) {
    const index = {};
    (rows || []).forEach((row) => {
      const key = historyIndexKey(row);
      if (!key || key === '||') return;
      if (!index[key]) index[key] = [];
      index[key].push(row);
    });
    return index;
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
    state.bankHistoryIndex = buildHistoryIndex(rates);
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
      if (key && key !== '||') visibleKeys.add(key);
    });
    if (!visibleKeys.size) return [];
    const filters = bankFilterValues();
    const out = [];
    visibleKeys.forEach((key) => {
      (state.bankHistoryIndex[key] || []).forEach((row) => {
        if (matchesBankFilters(row, filters, { skipQuery: true })) out.push(row);
      });
    });
    return out;
  }

  function chartRows(rows) {
    if (state.sector === 'energy') {
      const counts = {};
      rows.forEach((row) => { if (row.provider) counts[row.provider] = (counts[row.provider] || 0) + 1; });
      return Object.entries(counts)
        .map(([label, value]) => ({ label, value }))
        .sort((a, b) => state.descending ? b.value - a.value : a.value - b.value)
        .slice(0, 30);
    }
    const historyRows = filteredHistoryRows(rows);
    const byProvider = {};
    const allDates = new Set();
    historyRows.forEach((row) => {
      const date = String(row.run_date || '');
      const provider = row.provider || 'Unknown provider';
      const rate = Number(row.rate);
      if (!date || !Number.isFinite(rate) || rate <= 0) return;
      allDates.add(date);
      if (!byProvider[provider]) byProvider[provider] = { label: provider, byDate: {}, count: 0 };
      if (!byProvider[provider].byDate[date]) {
        byProvider[provider].byDate[date] = { min: rate, max: rate, count: 0, productKeys: new Set() };
      }
      const p = byProvider[provider].byDate[date];
      if (rate < p.min) p.min = rate;
      if (rate > p.max) p.max = rate;
      p.count++;
      if (row.product_key || row.product_id || row.product_name) p.productKeys.add(row.product_key || row.product_id || row.product_name);
    });
    const dates = historyDatesInWindow(Array.from(allDates));
    const latestDate = dates[dates.length - 1] || state.manifest.run_date;
    const providers = Object.values(byProvider).map((provider) => {
      const visible = {};
      let count = 0;
      dates.forEach((date) => {
        const point = provider.byDate[date];
        if (!point) return;
        visible[date] = {
          min: point.min,
          max: point.max,
          count: point.count,
          products: point.productKeys.size,
        };
        count += point.count;
      });
      const latest = visible[latestDate] || Object.values(visible).slice(-1)[0] || null;
      return {
        label: provider.label,
        byDate: visible,
        min: latest ? latest.min : null,
        max: latest ? latest.max : null,
        value: latest ? (state.descending ? latest.max : latest.min) : null,
        count,
      };
    }).filter((provider) => provider.value != null)
      .sort((a, b) => state.descending ? b.value - a.value : a.value - b.value)
      .slice(0, 40);
    return {
      kind: 'bank-history',
      section: state.section,
      window: state.historyWindow,
      dates,
      allDates: Array.from(allDates).sort(),
      providers,
      currentRange: currentRateRange(rows),
      totalHistoryRows: historyRows.length,
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
      Energy:   'Australian Economic Data - Daily CDR Data | AustralianRates',
    };
    document.title = pageTitles[state.section] || pageTitles.Mortgage;
    const titles = { Mortgage: 'Home loan rates, tracked.', Savings: 'Savings rates, tracked.', TD: 'Term deposit yields, tracked.', Energy: 'Economic data, tracked.' };
    $('page-title').textContent = titles[state.section] || titles.Mortgage;
    const leaderLabels = { Mortgage: 'Lowest rate', Savings: 'Top yield', TD: 'Top yield', Energy: 'Plans' };
    const focusLabels  = { Mortgage: 'Lowest rates', Savings: 'Top yields', TD: 'Top yields', Energy: 'Plan count' };
    $('hero-leader-label').textContent = leaderLabels[state.section] || leaderLabels.Mortgage;
    $('chart-focus').textContent = focusLabels[state.section] || focusLabels.Mortgage;
    $('chart-toggle-sort').textContent = state.descending ? 'Lowest first' : 'Highest first';

    const isBanks    = state.sector === 'banks';
    const isMortgage = state.section === 'Mortgage';
    const isSavings  = state.section === 'Savings';
    const isTD       = state.section === 'TD';
    document.querySelectorAll('.local-filter-purpose, .local-filter-repayment, .local-filter-structure')
      .forEach((el) => { el.hidden = !isMortgage; });
    document.querySelectorAll('.local-filter-rate-type')
      .forEach((el) => { el.hidden = !isSavings; });
    document.querySelectorAll('.local-filter-term')
      .forEach((el) => { el.hidden = !isTD; });
    document.querySelectorAll('.local-filter-banks-only')
      .forEach((el) => { el.hidden = !isBanks; });
    document.querySelectorAll('.local-history-window, .local-history-window-status')
      .forEach((el) => { el.hidden = !isBanks; });
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

  function setupFilters() {
    const dataset = $('dataset');
    clear(dataset);
    if (state.sector === 'banks') {
      const values = [...new Set(state.banks.products.map((row) => row.dataset).filter(Boolean))].sort();
      child(dataset, 'option', '', 'All banking datasets').value = '';
      values.forEach((value) => child(dataset, 'option', '', value));
      dataset.value = values.includes(state.section) ? state.section : '';
      dataset.disabled = false;
    } else {
      child(dataset, 'option', '', 'Energy plans').value = '';
      dataset.disabled = true;
    }
    ['filter-purpose', 'filter-repayment', 'filter-structure', 'filter-term', 'filter-rate-type'].forEach((id) => {
      const el = $(id);
      if (el) el.value = '';
    });
  }

  function renderSectionCards() {
    const wrap = $('sectionCards');
    clear(wrap);
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
    if (!window.LocalCdrBrand) { wrap.hidden = true; return; }

    let providers, label;
    if (state.sector === 'banks' && state.banks && state.banks.rates) {
      const rows = state.banks.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
      providers = [...new Set(rows.map((row) => row.provider).filter(Boolean))].sort();
      label = state.section === 'TD' ? 'Term Deposit' : state.section;
    } else if (state.sector === 'energy' && state.energy && state.energy.plans) {
      providers = [...new Set(state.energy.plans.map((row) => row.provider).filter(Boolean))].sort();
      label = 'Energy';
    } else {
      wrap.hidden = true;
      return;
    }

    wrap.hidden = false;
    child(wrap, 'span', 'local-selected-logos-title', `${label} providers - click a logo to filter`);
    const rail = child(wrap, 'span', 'local-section-logo-rail local-section-logo-rail-full');
    const providerQuery = filterVal('provider').toLowerCase();
    providers.forEach((provider) => {
      const btn = child(rail, 'button', 'local-provider-logo-btn');
      btn.type = 'button';
      btn.dataset.providerPick = provider;
      btn.title = 'Show products for ' + provider + ' only (click again to clear)';
      if (providerQuery && provider.toLowerCase() === providerQuery) btn.classList.add('is-selected');
      const sample = state.sector === 'banks' && state.banks && state.banks.rates
        ? state.banks.rates.find((r) => r.provider === provider)
        : undefined;
      window.LocalCdrBrand.appendProviderBadge(btn, provider, false, { logoOnly: true, rateRow: sample });
    });
  }

  function updateHero(rows, items) {
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

  function setLastRefreshed() { $('last-refreshed').textContent = new Date().toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' }); }

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
    if (state.sector === 'banks' || hasTaxonomy) {
      $('table').hidden = true;
      document.querySelector('.local-table-panel').hidden = true;
      $('chart-side-panel').hidden = false;
      $('hierarchy').hidden = false;
      window.LocalCdrHierarchy.render($('hierarchy'), $('table-count'), rows, state);
    } else {
      renderFlatTable(rows);
    }
  }

  function render() {
    const rows  = normalizeRows(rateRows());
    const items = chartRows(rows);
    setLinks();
    updateHero(rows, items);
    renderStats(rows);
    renderTable(rows);
    window.LocalCdrChart.draw($('chart'), items, state.sector);
    setHistoryWindowUi(items);
    if (state.sector === 'banks' && items && items.kind === 'bank-history') {
      $('chart-status').textContent = `${num(rows.length)} current rows / ${num(items.totalHistoryRows)} historical rows loaded`;
    } else {
      $('chart-status').textContent = `${num(rows.length)} local ${state.sector === 'banks' ? 'rate rows' : 'plans'} loaded`;
    }
    renderSelectedLogos();
  }

  async function loadSection(section) {
    if (state.section !== section) {
      state.hierarchyPath = '';
      $('provider').value = '';
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
    if (state.sector === 'banks') await loadBankHistory();
    setupFilters();
    renderSectionCards();
    render();
    setLastRefreshed();
  }

  function bind() {
    let resizeTimer = 0;
    document.querySelectorAll('[data-section]').forEach((el) => el.addEventListener('click', (e) => { e.preventDefault(); loadSection(el.dataset.section); }));
    $('sectionCards').addEventListener('click', (event) => {
      const card = event.target.closest('[data-section-card]');
      if (card) loadSection(card.dataset.sectionCard);
    });
    $('selectedLogos').addEventListener('click', (event) => {
      const btn = event.target.closest('[data-provider-pick]');
      if (!btn) return;
      const pick = btn.dataset.providerPick || '';
      const input = $('provider');
      const cur = input.value.trim();
      if (cur && pick.toLowerCase() === cur.toLowerCase()) input.value = '';
      else input.value = pick;
      state.hierarchyPath = '';
      render();
    });
    $('hierarchy').addEventListener('click', (event) => {
      const action = event.target.closest('[data-local-hierarchy-action]');
      if (!action) return;
      state.hierarchyPath = action.dataset.localHierarchyPath || '';
      renderTable(normalizeRows(rateRows()));
    });
    $('hierarchy').addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      if (event.target.closest('button')) return;
      const action = event.target.closest('[data-local-hierarchy-action]');
      if (!action) return;
      event.preventDefault();
      state.hierarchyPath = action.dataset.localHierarchyPath || '';
      renderTable(normalizeRows(rateRows()));
    });
    ['dataset', 'provider', 'query',
      'filter-purpose', 'filter-repayment', 'filter-structure',
      'filter-term', 'filter-rate-type',
    ].forEach((id) => {
      const el = $(id);
      if (el) {
        el.addEventListener('input', render);
        el.addEventListener('change', render);
      }
    });
    $('refresh-page-btn').addEventListener('click', () => window.location.reload());
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
    window.addEventListener('resize', () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => window.LocalCdrChart.draw($('chart'), chartRows(normalizeRows(rateRows())), state.sector), 120);
    });
    window.addEventListener('ar:theme-changed', () => window.LocalCdrChart.draw($('chart'), chartRows(normalizeRows(rateRows())), state.sector));
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
