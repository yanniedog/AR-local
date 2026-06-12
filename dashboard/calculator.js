(function () {
  'use strict';

  /**
   * Benefit calculator: user enters their current (or proposed) home loan,
   * savings account, or term deposit; we model the dollar cost/return over
   * time (fees and offset balance included), compare against every lender's
   * live CDR rate for the same section, and chart the long-term forecast.
   * All modelling is client-side; data comes from /api/latest + /api/banks/section.
   */

  const $ = (id) => document.getElementById(id);
  const { normalizeRows } = window.LocalCdrUtils;

  const AUD0 = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD', maximumFractionDigits: 0 });
  const AUD2 = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const money = (v) => AUD0.format(Math.round(v));
  const money2 = (v) => AUD2.format(v);

  const SIM_CAP_MONTHS = 50 * 12;

  const state = {
    section: 'Mortgage',
    runDate: '',
    rows: { Mortgage: null, Savings: null, TD: null }, // null = not fetched
    selected: { Mortgage: '', Savings: '', TD: '' },   // provider key of chart comparison row
    charts: { projection: null, benefit: null },
    candidatesCache: [],
  };

  // ---------------------------------------------------------------------------
  // Finance engine
  // ---------------------------------------------------------------------------

  /** Standard amortised payment; rate may be 0. */
  function amortisedPayment(principal, monthlyRate, months) {
    if (months <= 0) return principal;
    if (monthlyRate <= 0) return principal / months;
    return principal * monthlyRate / (1 - Math.pow(1 + monthlyRate, -months));
  }

  /**
   * Month-by-month loan simulation. Interest accrues on (balance - offset);
   * account fees are tracked as cost but not capitalised. `paymentMonthly`
   * already includes any accelerated-frequency uplift and extra repayments.
   */
  function simulateLoan(opts) {
    const r = opts.ratePct / 100 / 12;
    let bal = opts.principal;
    let totalInterest = 0;
    let totalFees = opts.upfrontCost || 0;
    let m = 0;
    const series = [{ m: 0, bal, cost: totalFees }];
    while (bal > 0.005 && m < SIM_CAP_MONTHS) {
      m++;
      const interest = r * Math.max(0, bal - (opts.offset || 0));
      totalInterest += interest;
      totalFees += (opts.monthlyFee || 0) + (m % 12 === 0 ? (opts.annualFee || 0) : 0);
      bal = Math.max(0, bal + interest - opts.paymentMonthly);
      series.push({ m, bal, cost: totalInterest + totalFees });
    }
    return {
      months: m,
      totalInterest,
      totalFees,
      totalCost: totalInterest + totalFees,
      series,
      neverRepaid: bal > 0.005,
    };
  }

  /** Cost (interest + fees) accrued by a given month, flatlining after payoff. */
  function costAtMonth(sim, month) {
    const i = Math.min(month, sim.series.length - 1);
    return sim.series[i].cost;
  }

  /** Monthly-compounding savings projection with deposits and account fees. */
  function simulateSavings(opts) {
    const r = opts.ratePct / 100 / 12;
    let bal = opts.balance;
    let earned = 0;
    let fees = 0;
    const series = [{ m: 0, bal }];
    const months = Math.round(opts.years * 12);
    for (let m = 1; m <= months; m++) {
      const interest = bal > 0 ? bal * r : 0;
      earned += interest;
      fees += opts.monthlyFee || 0;
      bal += interest + (opts.monthlyDeposit || 0) - (opts.monthlyFee || 0);
      series.push({ m, bal });
    }
    return { final: bal, earned, fees, series };
  }

  /** Simple-interest TD projection (typical for at-maturity payment). */
  function simulateTd(opts) {
    const interest = opts.principal * (opts.ratePct / 100) * (opts.months / 12);
    const series = [];
    for (let m = 0; m <= opts.months; m++) {
      series.push({ m, bal: opts.principal + interest * (m / opts.months) });
    }
    return { interest, final: opts.principal + interest, series };
  }

  // ---------------------------------------------------------------------------
  // Inputs
  // ---------------------------------------------------------------------------

  function numInput(id, fallback) {
    const v = Number(String($(id).value).replace(/[^0-9.\-]/g, ''));
    return Number.isFinite(v) ? v : fallback;
  }

  function loanInputs() {
    const freq = $('m-freq').value;
    // Accelerated fortnightly/weekly = 26 half-payments (13 monthly payments / year).
    const freqFactor = freq === 'monthly' ? 1 : 13 / 12;
    return {
      principal: numInput('m-balance', 0),
      ratePct: numInput('m-rate', 0),
      termYears: numInput('m-term', 25),
      offset: numInput('m-offset', 0),
      extraMonthly: numInput('m-extra', 0),
      monthlyFee: numInput('m-fee-month', 0),
      annualFee: numInput('m-fee-annual', 0),
      newAnnualFee: numInput('m-new-fee-annual', 0),
      switchCost: numInput('m-switch-cost', 0),
      freqFactor,
      structure: $('m-structure').value,
      purpose: $('m-purpose').value,
      repay: $('m-repay').value,
    };
  }

  function savingsInputs() {
    return {
      balance: numInput('s-balance', 0),
      ratePct: numInput('s-rate', 0),
      monthlyDeposit: numInput('s-deposit', 0),
      monthlyFee: numInput('s-fee', 0),
      years: Math.max(1, numInput('s-years', 5)),
    };
  }

  function tdInputs() {
    return {
      principal: numInput('t-principal', 0),
      ratePct: numInput('t-rate', 0),
      months: Number($('t-term').value) || 12,
    };
  }

  // ---------------------------------------------------------------------------
  // Candidate products from live CDR rows
  // ---------------------------------------------------------------------------

  function plausibleRatePct(ratePct) {
    return Number.isFinite(ratePct) && ratePct > 0.01 && ratePct < 20;
  }

  /** Best rate per provider after the section's filters. */
  function bestPerProvider(rows, lowerIsBetter, accept) {
    const best = new Map();
    rows.forEach((row) => {
      if ((row.account_class || '') === 'non_standard') return;
      const ratePct = Number(row.rate) * 100;
      if (!plausibleRatePct(ratePct)) return;
      if (accept && !accept(row, ratePct)) return;
      const prev = best.get(row.provider);
      if (!prev || (lowerIsBetter ? ratePct < prev.ratePct : ratePct > prev.ratePct)) {
        best.set(row.provider, { row, ratePct });
      }
    });
    return Array.from(best.values()).sort((a, b) => (lowerIsBetter ? a.ratePct - b.ratePct : b.ratePct - a.ratePct));
  }

  function mortgageCandidates(rows, f) {
    return bestPerProvider(rows, true, (row) => {
      if (row.rate_type === 'DISCOUNT') return false;
      if (f.structure && String(row.ribbon_rate_structure || '') !== f.structure) return false;
      if (f.purpose && String(row.loan_purpose || '') && String(row.loan_purpose) !== f.purpose) return false;
      if (f.repay && String(row.ribbon_repayment_type || '') && String(row.ribbon_repayment_type) !== f.repay) return false;
      return true;
    });
  }

  function savingsCandidates(rows) {
    return bestPerProvider(rows, false, null);
  }

  function tdCandidates(rows, months) {
    return bestPerProvider(rows, false, (row) => Number(row.term_months) === months);
  }

  /** Distinct non-empty values of a field, for data-driven filter dropdowns. */
  function distinctValues(rows, field) {
    const seen = new Set();
    rows.forEach((row) => {
      const v = String(row[field] || '').trim();
      if (v) seen.add(v);
    });
    return Array.from(seen).sort();
  }

  function fillSelect(el, values, keep, labels) {
    const prev = keep ? el.value : '';
    while (el.options.length > 1) el.remove(1); // keep the "Any"/first option
    values.forEach((v) => {
      if (el.options[0] && el.options[0].value === v) return;
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = (labels && labels(v)) || v;
      el.appendChild(opt);
    });
    if (prev && values.includes(prev)) el.value = prev;
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function card(parent, label, value, hint) {
    const c = document.createElement('div');
    c.className = 'calc-card';
    const l = document.createElement('span');
    l.className = 'calc-card-label';
    l.textContent = label;
    const v = document.createElement('strong');
    v.className = 'calc-card-value';
    v.textContent = value;
    c.appendChild(l);
    c.appendChild(v);
    if (hint) {
      const h = document.createElement('span');
      h.className = 'calc-card-hint';
      h.textContent = hint;
      c.appendChild(h);
    }
    parent.appendChild(c);
  }

  function chart(slot) {
    if (!state.charts[slot]) {
      state.charts[slot] = echarts.init($(slot === 'projection' ? 'calc-chart-projection' : 'calc-chart-benefit'), null, { renderer: 'canvas' });
    }
    return state.charts[slot];
  }

  function chartTheme() {
    const css = (n, f) => {
      try { return getComputedStyle(document.documentElement).getPropertyValue(n).trim() || f; } catch (_e) { return f; }
    };
    const dark = document.documentElement.getAttribute('data-theme') !== 'light';
    return {
      text: css('--ar-text', dark ? '#e2e8f0' : '#1e293b'),
      muted: css('--ar-text-muted', dark ? '#94a3b8' : '#64748b'),
      grid: dark ? 'rgba(148,163,184,0.10)' : 'rgba(148,163,184,0.18)',
      palette: ['#3b82f6', '#22c55e', '#f59e0b', '#a855f7', '#ef4444'],
    };
  }

  function lineChart(slot, title, seriesDefs, monthsToLabel) {
    const t = chartTheme();
    chart(slot).setOption({
      color: t.palette,
      title: { text: title, left: 8, top: 4, textStyle: { color: t.muted, fontSize: 12, fontWeight: 500 } },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v) => money(Number(v) || 0),
      },
      legend: { bottom: 0, textStyle: { color: t.muted, fontSize: 11 } },
      grid: { left: 70, right: 18, top: 34, bottom: 44 },
      xAxis: {
        type: 'category',
        data: seriesDefs[0].data.map((p) => monthsToLabel(p.m)),
        axisLabel: { color: t.muted, fontSize: 10 },
        axisLine: { lineStyle: { color: t.grid } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: t.muted, fontSize: 10, formatter: (v) => (v >= 1000 ? '$' + Math.round(v / 1000) + 'k' : '$' + v) },
        splitLine: { lineStyle: { color: t.grid } },
      },
      series: seriesDefs.map((d) => ({
        name: d.name,
        type: 'line',
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2 },
        data: d.data.map((p) => Math.round(p.v)),
      })),
    }, true);
  }

  function benefitBarChart(title, items) {
    const t = chartTheme();
    const top = items.slice(0, 10).reverse(); // reversed so the best is at the top of a horizontal bar chart
    chart('benefit').setOption({
      title: { text: title, left: 8, top: 4, textStyle: { color: t.muted, fontSize: 12, fontWeight: 500 } },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v) => money(Number(v) || 0),
      },
      grid: { left: 120, right: 30, top: 34, bottom: 24 },
      xAxis: {
        type: 'value',
        axisLabel: { color: t.muted, fontSize: 10, formatter: (v) => '$' + (Math.abs(v) >= 1000 ? Math.round(v / 1000) + 'k' : v) },
        splitLine: { lineStyle: { color: t.grid } },
      },
      yAxis: {
        type: 'category',
        data: top.map((i) => i.provider),
        axisLabel: { color: t.muted, fontSize: 10, width: 110, overflow: 'truncate' },
        axisLine: { lineStyle: { color: t.grid } },
      },
      series: [{
        name: title,
        type: 'bar',
        data: top.map((i) => ({
          value: Math.round(i.benefit),
          itemStyle: { color: i.benefit >= 0 ? '#22c55e' : '#ef4444' },
        })),
        barMaxWidth: 18,
      }],
    }, true);
  }

  function monthsLabelYears(m) {
    return m % 12 === 0 ? (m / 12) + 'y' : '';
  }

  function renderTable(columns, rows) {
    const table = $('calc-table');
    clear(table);
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    columns.forEach((c) => {
      const th = document.createElement('th');
      th.textContent = c;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    rows.forEach((r) => {
      const tr = document.createElement('tr');
      tr.className = 'calc-row' + (r.selected ? ' is-selected' : '');
      r.cells.forEach((cellValue, idx) => {
        const td = document.createElement('td');
        td.textContent = cellValue;
        if (idx >= r.numericFrom) td.className = 'calc-num';
        tr.appendChild(td);
      });
      tr.addEventListener('click', () => {
        state.selected[state.section] = r.provider;
        recompute();
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    $('calc-table-hint').textContent = rows.length
      ? 'Click a row to chart it against your current product. Dollar figures include the fee assumptions above.'
      : 'No matching live products for the current filters.';
  }

  // ---------------------------------------------------------------------------
  // Section computations
  // ---------------------------------------------------------------------------

  function renderMortgage(rows) {
    const f = loanInputs();
    const enumLabel = (v) => v.toLowerCase().replace(/_/g, ' ');
    fillSelect($('m-purpose'), distinctValues(rows, 'loan_purpose'), true, enumLabel);
    fillSelect($('m-repay'), distinctValues(rows, 'ribbon_repayment_type'), true, enumLabel);

    const summary = $('calc-summary');
    clear(summary);
    if (!(f.principal > 0) || !(f.ratePct > 0) || !(f.termYears > 0)) {
      card(summary, 'Enter your loan', 'Balance, rate and term are required', '');
      renderTable([], []);
      return;
    }

    const basePayment = amortisedPayment(f.principal, f.ratePct / 100 / 12, Math.round(f.termYears * 12));
    const paymentMonthly = basePayment * f.freqFactor + f.extraMonthly;
    const current = simulateLoan({
      principal: f.principal, ratePct: f.ratePct, offset: f.offset,
      monthlyFee: f.monthlyFee, annualFee: f.annualFee, paymentMonthly,
    });
    const noOffset = f.offset > 0
      ? simulateLoan({ principal: f.principal, ratePct: f.ratePct, monthlyFee: f.monthlyFee, annualFee: f.annualFee, paymentMonthly })
      : null;

    card(summary, 'Minimum repayment', money2(basePayment) + '/mo', f.freqFactor > 1 ? 'Accelerated ' + $('m-freq').value + ' modelled as 13 payments/yr' : '');
    card(summary, 'Time to repay', current.neverRepaid ? '50y+ (repayment too low)' : (current.months / 12).toFixed(1) + ' years', '');
    card(summary, 'Total interest + fees', money(current.totalCost), '');
    if (noOffset) card(summary, 'Your offset saves you', money(noOffset.totalCost - current.totalCost), money(f.offset) + ' offset vs none, same repayments');

    // Candidates: each alternative keeps the user's repayment behaviour, offset
    // and extra repayments; switching cost + assumed new annual fee included.
    const candidates = mortgageCandidates(rows, f).map((c) => {
      const sim = simulateLoan({
        principal: f.principal, ratePct: c.ratePct, offset: f.offset,
        monthlyFee: 0, annualFee: f.newAnnualFee, upfrontCost: f.switchCost,
        paymentMonthly: amortisedPayment(f.principal, c.ratePct / 100 / 12, Math.round(f.termYears * 12)) * f.freqFactor + f.extraMonthly,
      });
      return {
        provider: c.row.provider,
        product: String(c.row.product_name || ''),
        detail: [c.row.ribbon_rate_structure, c.row.ribbon_fixed_term, c.row.lvr_tier].filter(Boolean).join(' · '),
        ratePct: c.ratePct,
        sim,
        benefit: current.totalCost - sim.totalCost,
        benefit5y: costAtMonth(current, 60) - costAtMonth(sim, 60),
      };
    }).sort((a, b) => b.benefit - a.benefit);
    state.candidatesCache = candidates;

    const sel = candidates.find((c) => c.provider === state.selected.Mortgage) || candidates[0];
    const projSeries = [
      { name: 'Current loan', data: current.series.map((p) => ({ m: p.m, v: p.bal })) },
    ];
    if (noOffset) projSeries.push({ name: 'Current without offset', data: noOffset.series.map((p) => ({ m: p.m, v: p.bal })) });
    if (sel) projSeries.push({ name: sel.provider + ' @ ' + sel.ratePct.toFixed(2) + '%', data: sel.sim.series.map((p) => ({ m: p.m, v: p.bal })) });
    lineChart('projection', 'Loan balance forecast', projSeries, monthsLabelYears);
    benefitBarChart('Saving over full term vs your loan ($)', candidates);

    renderTable(
      ['Lender', 'Product', 'Rate', 'Repayment/mo', 'Saves in 5y', 'Saves over term'],
      candidates.slice(0, 15).map((c) => ({
        provider: c.provider,
        selected: sel && c.provider === sel.provider,
        numericFrom: 2,
        cells: [
          c.provider,
          (c.product + (c.detail ? ' (' + c.detail + ')' : '')).slice(0, 80),
          c.ratePct.toFixed(2) + '%',
          money2(amortisedPayment(f.principal, c.ratePct / 100 / 12, Math.round(f.termYears * 12))),
          money(c.benefit5y),
          money(c.benefit),
        ],
      })),
    );
  }

  function renderSavings(rows) {
    const f = savingsInputs();
    const summary = $('calc-summary');
    clear(summary);
    if (!(f.balance > 0) && !(f.monthlyDeposit > 0)) {
      card(summary, 'Enter your savings', 'Balance or monthly deposit required', '');
      renderTable([], []);
      return;
    }

    const current = simulateSavings(f);
    card(summary, 'Balance in ' + f.years + 'y', money(current.final), '');
    card(summary, 'Interest earned', money(current.earned), '');
    if (current.fees > 0) card(summary, 'Fees paid', money(current.fees), '');

    const candidates = savingsCandidates(rows).map((c) => {
      const sim = simulateSavings({ ...f, ratePct: c.ratePct, monthlyFee: 0 });
      return {
        provider: c.row.provider,
        product: String(c.row.product_name || ''),
        detail: String(c.row.ribbon_deposit_kind || c.row.rate_type || ''),
        ratePct: c.ratePct,
        sim,
        benefit: sim.final - current.final,
      };
    }).sort((a, b) => b.benefit - a.benefit);
    state.candidatesCache = candidates;

    const sel = candidates.find((c) => c.provider === state.selected.Savings) || candidates[0];
    const projSeries = [{ name: 'Current account', data: current.series.map((p) => ({ m: p.m, v: p.bal })) }];
    if (sel) projSeries.push({ name: sel.provider + ' @ ' + sel.ratePct.toFixed(2) + '%', data: sel.sim.series.map((p) => ({ m: p.m, v: p.bal })) });
    lineChart('projection', 'Savings balance forecast', projSeries, monthsLabelYears);
    benefitBarChart('Extra savings after ' + f.years + ' years ($)', candidates);

    renderTable(
      ['Bank', 'Product', 'Rate', 'Balance in ' + f.years + 'y', 'Extra vs current'],
      candidates.slice(0, 15).map((c) => ({
        provider: c.provider,
        selected: sel && c.provider === sel.provider,
        numericFrom: 2,
        cells: [
          c.provider,
          (c.product + (c.detail ? ' (' + c.detail + ')' : '')).slice(0, 80),
          c.ratePct.toFixed(2) + '%',
          money(c.sim.final),
          money(c.benefit),
        ],
      })),
    );
    $('calc-table-hint').textContent += ' Bonus rates usually require monthly conditions; CDR feeds do not include account fees for other banks.';
  }

  function renderTd(rows) {
    const terms = distinctValues(rows, 'term_months')
      .map(Number).filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
    fillSelect($('t-term'), terms.map(String), true, (v) => v + ' months');
    const termEl = $('t-term');
    if (!terms.includes(Number(termEl.value))) {
      termEl.value = String(terms.includes(12) ? 12 : (terms[0] || 12));
    }
    const f = tdInputs();

    const summary = $('calc-summary');
    clear(summary);
    if (!(f.principal > 0)) {
      card(summary, 'Enter your term deposit', 'Principal is required', '');
      renderTable([], []);
      return;
    }

    const current = simulateTd(f);
    card(summary, 'Interest at maturity', money2(current.interest), f.months + ' months @ ' + f.ratePct.toFixed(2) + '% (simple interest)');
    card(summary, 'Balance at maturity', money2(current.final), '');

    const candidates = tdCandidates(rows, f.months).map((c) => {
      const sim = simulateTd({ ...f, ratePct: c.ratePct });
      return {
        provider: c.row.provider,
        product: String(c.row.product_name || ''),
        detail: String(c.row.interest_payment || ''),
        ratePct: c.ratePct,
        sim,
        benefit: sim.interest - current.interest,
      };
    }).sort((a, b) => b.benefit - a.benefit);
    state.candidatesCache = candidates;

    const sel = candidates.find((c) => c.provider === state.selected.TD) || candidates[0];
    const projSeries = [{ name: 'Current TD', data: current.series.map((p) => ({ m: p.m, v: p.bal })) }];
    if (sel) projSeries.push({ name: sel.provider + ' @ ' + sel.ratePct.toFixed(2) + '%', data: sel.sim.series.map((p) => ({ m: p.m, v: p.bal })) });
    lineChart('projection', 'Term deposit value to maturity', projSeries, (m) => m + 'm');
    benefitBarChart('Extra interest at maturity ($)', candidates);

    renderTable(
      ['Bank', 'Product', 'Rate', 'Interest at maturity', 'Extra vs current'],
      candidates.slice(0, 15).map((c) => ({
        provider: c.provider,
        selected: sel && c.provider === sel.provider,
        numericFrom: 2,
        cells: [
          c.provider,
          (c.product + (c.detail ? ' (' + c.detail + ')' : '')).slice(0, 80),
          c.ratePct.toFixed(2) + '%',
          money2(c.sim.interest),
          money(c.benefit),
        ],
      })),
    );
  }

  // ---------------------------------------------------------------------------
  // Data loading + wiring
  // ---------------------------------------------------------------------------

  async function getJson(url) {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(url + ' returned ' + response.status);
    return response.json();
  }

  async function sectionRows(section) {
    if (state.rows[section]) return state.rows[section];
    if (!state.runDate) {
      const latest = await getJson('/api/latest');
      state.runDate = String(latest.run_date || '');
      $('calc-run-date').textContent = state.runDate || 'unavailable';
    }
    const payload = await getJson(`/api/banks/section?date=${encodeURIComponent(state.runDate)}&section=${encodeURIComponent(section)}`);
    const rows = Array.isArray(payload.rates) ? payload.rates : [];
    rows.forEach((row) => { row.dataset = section; }); // normalizeRows keys its percent heuristics off dataset
    state.rows[section] = normalizeRows(rows);
    return state.rows[section];
  }

  let recomputeTimer = 0;
  function recompute() {
    window.clearTimeout(recomputeTimer);
    recomputeTimer = window.setTimeout(async () => {
      const section = state.section;
      $('calc-status').textContent = 'Loading live rates…';
      try {
        const rows = await sectionRows(section);
        if (state.section !== section) return;
        $('calc-status').textContent = rows.length + ' live rates · run ' + state.runDate;
        if (section === 'Mortgage') renderMortgage(rows);
        else if (section === 'Savings') renderSavings(rows);
        else renderTd(rows);
      } catch (err) {
        $('calc-status').textContent = 'Could not load live rates: ' + (err && err.message ? err.message : err);
      }
    }, 120);
  }

  function setSection(section) {
    state.section = section;
    document.querySelectorAll('[data-calc-tab]').forEach((btn) => {
      btn.classList.toggle('is-active', btn.getAttribute('data-calc-tab') === section);
    });
    document.querySelectorAll('[data-calc-form]').forEach((form) => {
      form.hidden = form.getAttribute('data-calc-form') !== section;
    });
    recompute();
  }

  function init() {
    document.querySelectorAll('[data-calc-tab]').forEach((btn) => {
      btn.addEventListener('click', () => setSection(btn.getAttribute('data-calc-tab')));
    });
    document.querySelectorAll('#calc-forms input, #calc-forms select').forEach((el) => {
      el.addEventListener('input', recompute);
      el.addEventListener('change', recompute);
    });
    window.addEventListener('resize', () => {
      Object.values(state.charts).forEach((c) => { if (c) c.resize(); });
    });
    new MutationObserver(recompute).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    setSection('Mortgage');
  }

  init();
})();
