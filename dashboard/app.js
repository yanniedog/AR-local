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
    hierarchyPath: '',
  };
  const $ = (id) => document.getElementById(id);
  const { bankRateMatchesSection, historyIndexKey, normalizeRows, pct } = window.LocalCdrUtils;

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
    const q        = filterVal('query').toLowerCase();
    const provider = filterVal('provider').toLowerCase();
    const dataset  = state.section === 'Energy' ? '' : filterVal('dataset');
    const purpose  = filterVal('filter-purpose');
    const repay    = filterVal('filter-repayment');
    const struct   = filterVal('filter-structure');
    const term     = filterVal('filter-term');
    const rateType = filterVal('filter-rate-type');
    if (state.sector === 'banks') {
      if (!state.banks) return [];
      return state.banks.rates.filter((row) =>
        (!dataset   || row.dataset === dataset) &&
        bankRateMatchesSection(row) &&
        (!provider  || String(row.provider || '').toLowerCase().includes(provider)) &&
        (!q         || String(row.product_name || '').toLowerCase().includes(q)) &&
        (!purpose   || row.security_purpose === purpose) &&
        (!repay     || row.ribbon_repayment_type === repay) &&
        (!struct    || row.rate_type === struct) &&
        (!term      || String(Math.round(Number(row.term_months)) || '') === term) &&
        (!rateType  || row.ribbon_deposit_kind === rateType)
      );
    }
    if (!state.energy) return [];
    return state.energy.plans.filter((row) =>
      (!provider || String(row.provider || '').toLowerCase().includes(provider)) &&
      (!q        || String(row.plan_name || '').toLowerCase().includes(q))
    );
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

  async function loadBankHistory() {
    if (state.bankHistory) return;
    state.bankHistory = await getJson(`/api/banks/history?date=${state.manifest.run_date}`);
    state.bankHistoryIndex = buildHistoryIndex(state.bankHistory.rates || []);
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
    const byProvider = {};
    rows.forEach((row) => {
      const rate = Number(row.rate);
      if (!Number.isFinite(rate) || rate <= 0) return;
      if (!byProvider[row.provider]) byProvider[row.provider] = { min: rate, max: rate, count: 0 };
      const p = byProvider[row.provider];
      if (rate < p.min) p.min = rate;
      if (rate > p.max) p.max = rate;
      p.count++;
    });
    return Object.entries(byProvider)
      .map(([label, d]) => ({ label, min: d.min, max: d.max, value: d.max, count: d.count }))
      .sort((a, b) => state.descending ? b.value - a.value : a.min - b.min)
      .slice(0, 40);
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
    if (state.sector === 'banks' && items[0]) {
      $('hero-leader').textContent = pct(items[0].min);
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
    $('chart-status').textContent = `${num(rows.length)} local ${state.sector === 'banks' ? 'rate rows' : 'plans'} loaded`;
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
