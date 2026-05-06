(function () {
  'use strict';

  const state = {
    section: 'Mortgage',
    sector: 'banks',
    manifest: null,
    banks: null,
    energy: null,
    descending: false,
    hierarchyPath: '',
  };
  const $ = (id) => document.getElementById(id);
  const { bankRateMatchesSection, normalizeRows, pct } = window.LocalCdrUtils;

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
    const q = $('query').value.trim().toLowerCase();
    const provider = $('provider').value.trim().toLowerCase();
    const dataset = state.section === 'Energy' ? '' : $('dataset').value;
    if (state.sector === 'banks') {
      if (!state.banks) return [];
      return state.banks.rates.filter((row) =>
        (!dataset || row.dataset === dataset) &&
        bankRateMatchesSection(row) &&
        (!provider || String(row.provider || '').toLowerCase().includes(provider)) &&
        (!q || String(row.product_name || '').toLowerCase().includes(q))
      );
    }
    if (!state.energy) return [];
    return state.energy.plans.filter((row) =>
      (!provider || String(row.provider || '').toLowerCase().includes(provider)) &&
      (!q || String(row.plan_name || '').toLowerCase().includes(q))
    );
  }

  function chartRows(rows) {
    const mapped = state.sector === 'banks'
      ? rows.map((row) => ({ label: row.provider + ' - ' + row.product_name, value: Number(row.rate), meta: [row.dataset, row.rate_type, row.loan_purpose].filter(Boolean).join(' | ') }))
      : rows.map((row) => ({ label: row.provider + ' - ' + row.plan_name, value: 1, meta: [row.fuel_type, row.last_updated && row.last_updated.slice(0, 10)].filter(Boolean).join(' | ') }));
    return mapped.filter((row) => Number.isFinite(row.value) && (state.sector !== 'banks' || row.value > 0)).sort((a, b) => state.descending ? b.value - a.value : a.value - b.value).slice(0, 40);
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
    const slug = state.section === 'Savings' ? 'savings' : state.section === 'TD' ? 'term-deposits' : state.section === 'Energy' ? 'economic-data' : 'home-loans';
    document.body.classList.toggle('ar-section-home-loans', state.section === 'Mortgage');
    document.body.classList.toggle('ar-section-savings', state.section === 'Savings');
    document.body.classList.toggle('ar-section-term-deposits', state.section === 'TD');
    document.body.classList.toggle('ar-section-economic-data', state.section === 'Energy');
    document.body.dataset.arSection = slug;
    document.querySelectorAll('[data-section]').forEach((button) => {
      const active = button.dataset.section === state.section;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-current', active ? 'page' : 'false');
    });
    const titles = { Mortgage: 'Home loan rates, tracked.', Savings: 'Savings rates, tracked.', TD: 'Term deposit yields, tracked.', Energy: 'Energy plans, tracked.' };
    $('page-title').textContent = titles[state.section] || titles.Mortgage;
    const leaderLabels = { Mortgage: 'Lowest rate', Savings: 'Top yield', TD: 'Top yield', Energy: 'Plans' };
    const focusLabels = { Mortgage: 'Lowest rates', Savings: 'Top yields', TD: 'Top yields', Energy: 'Plan count' };
    $('hero-leader-label').textContent = leaderLabels[state.section] || leaderLabels.Mortgage;
    $('chart-focus').textContent = focusLabels[state.section] || focusLabels.Mortgage;
    $('chart-toggle-sort').textContent = state.descending ? 'Lowest first' : 'Highest first';
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
    if (!state.banks || state.sector !== 'banks' || !window.LocalCdrBrand) { wrap.hidden = true; return; }
    const rows = state.banks.rates.filter((row) => row.dataset === state.section && bankRateMatchesSection(row));
    const providers = [...new Set(rows.map((row) => row.provider).filter(Boolean))].sort(), label = state.section === 'TD' ? 'Term Deposit' : state.section;
    wrap.hidden = false; child(wrap, 'span', 'local-selected-logos-title', `${label} providers`);
    const rail = child(wrap, 'span', 'local-section-logo-rail local-section-logo-rail-full');
    providers.forEach((provider) => window.LocalCdrBrand.appendProviderBadge(rail, provider, false));
  }

  function updateHero(rows, items) {
    $('hero-run').textContent = state.manifest.run_date;
    $('hero-rows').textContent = num(rows.length);
    $('hero-leader').textContent = state.sector === 'banks' && items[0] ? pct(items[0].value) : num(rows.length);
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
    if (state.sector === 'banks') {
      $('table').hidden = true;
      document.querySelector('.local-table-panel').hidden = true;
      $('chart-side-panel').hidden = false;
      $('hierarchy').hidden = false;
      window.LocalCdrHierarchy.render($('hierarchy'), $('table-count'), rows, state);
    } else renderFlatTable(rows);
  }

  function render() {
    const rows = normalizeRows(rateRows());
    const items = chartRows(rows);
    setLinks();
    updateHero(rows, items);
    renderStats(rows);
    renderTable(rows);
    window.LocalCdrChart.draw($('chart'), items, state.sector);
    $('chart-status').textContent = `${num(rows.length)} local ${state.sector === 'banks' ? 'rate rows' : 'plans'} loaded`;
  }

  async function loadSection(section) {
    if (state.section !== section) {
      state.hierarchyPath = '';
    }
    state.section = section;
    state.sector = section === 'Energy' ? 'energy' : 'banks';
    state.descending = preferredDescending(section);
    setSectionUi();
    $('chart-status').textContent = 'Loading local CDR data';
    $('table-count').textContent = '';
    clear($('table'));
    clear($('hierarchy'));
    if (!state[state.sector]) state[state.sector] = await getJson(`/api/${state.sector}?date=${state.manifest.run_date}`);
    setupFilters();
    renderSectionCards();
    renderSelectedLogos();
    render();
    setLastRefreshed();
  }

  function bind() {
    let resizeTimer = 0;
    document.querySelectorAll('[data-section]').forEach((button) => button.addEventListener('click', () => loadSection(button.dataset.section)));
    $('sectionCards').addEventListener('click', (event) => {
      const card = event.target.closest('[data-section-card]');
      if (card) loadSection(card.dataset.sectionCard);
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
    ['dataset', 'provider', 'query'].forEach((id) => $(id).addEventListener('input', render));
    $('dataset').addEventListener('change', render);
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
