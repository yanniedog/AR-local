(function () {
  'use strict';

  let _chartEl = null;
  let _chart = null;

  function cssVar(name, fallback) {
    try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback; }
    catch (_e) { return fallback; }
  }

  function isDarkTheme() {
    const t = document.documentElement.getAttribute('data-theme');
    return t !== 'light';
  }

  function theme() {
    const dark = isDarkTheme();
    return {
      text:   cssVar('--ar-text',       dark ? '#e2e8f0' : '#1e293b'),
      muted:  cssVar('--ar-text-muted', dark ? '#94a3b8' : '#64748b'),
      line:   cssVar('--ar-line',       dark ? 'rgba(148,163,184,0.20)' : 'rgba(148,163,184,0.35)'),
      grid:   dark ? 'rgba(148,163,184,0.08)' : 'rgba(148,163,184,0.16)',
      bg:     cssVar('--ar-surface-2',  dark ? '#0f172a' : '#ffffff'),
      ribbon: cssVar('--ar-section-accent', cssVar('--ar-accent', '#3b82f6')),
      crosshair: dark ? 'rgba(99,179,237,0.60)' : 'rgba(37,99,235,0.55)',
      ttBg:   dark ? 'rgba(15,23,42,0.96)' : 'rgba(255,255,255,0.97)',
      ttBorder: dark ? 'rgba(100,116,139,0.30)' : 'rgba(100,116,139,0.20)',
      ttText: dark ? '#e2e8f0' : '#1e293b',
    };
  }

  function hexToRgba(input, alpha) {
    const a = alpha != null ? alpha : 0.5;
    const fallback = 'rgba(59, 130, 246, ' + a + ')';
    if (typeof input !== 'string') return fallback;
    const raw = input.trim();
    if (!raw) return fallback;
    // Pass through existing rgb()/rgba() strings — CSS vars can return any form.
    if (/^rgba?\s*\(/i.test(raw)) return raw;
    let r;
    let g;
    let b;
    const m6 = raw.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    if (m6) {
      r = parseInt(m6[1], 16);
      g = parseInt(m6[2], 16);
      b = parseInt(m6[3], 16);
    } else {
      const m3 = raw.match(/^#?([0-9a-f])([0-9a-f])([0-9a-f])$/i);
      if (!m3) return fallback;
      r = parseInt(m3[1] + m3[1], 16);
      g = parseInt(m3[2] + m3[2], 16);
      b = parseInt(m3[3] + m3[3], 16);
    }
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  const PALETTE = [
    '#2563eb', '#27c27a', '#f0b90b', '#f97316', '#8b5cf6',
    '#ef4444', '#14b8a6', '#64748b', '#a78bfa', '#fb923c',
  ];

  function getChart(el) {
    if (!window.echarts) return null;
    if (_chart && _chartEl === el) { try { _chart.resize(); } catch (_e) {} return _chart; }
    if (_chart) {
      if (_chart._localHoverCleanup) {
        try { _chart._localHoverCleanup(); } catch (_e) {}
        _chart._localHoverCleanup = null;
      }
      try { window.echarts.dispose(_chart); } catch (_e) {}
      _chart = null;
    }
    _chartEl = el;
    _chart = window.echarts.init(el, null, { renderer: 'canvas' });
    return _chart;
  }

  function pct(v) { return (v * 100).toFixed(2) + '%'; }
  function pctAxis(v) { return (Number(v) * 100).toFixed(1) + '%'; }
  function pct2(v) { return (Number(v) * 100).toFixed(2); }

  function escHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[ch]);
  }

  /** AustralianRates ar-chart-report-plot-utils.js */
  function fmtReportDateYmd(ymd) {
    const s = String(ymd || '').slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    const p = s.split('-');
    const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return m[+p[1] - 1] + ' ' + (+p[2]) + ', ' + p[0];
  }

  /** Rates in chart data are decimal fractions; production hover uses percentage points. */
  function fmtHoverRate(value) {
    const n = Number(value);
    return Number.isFinite(n) ? (n * 100).toFixed(2) + '%' : 'n/a';
  }

  function ensureReportHoverBox(mount, t) {
    let box = mount.querySelector('.ar-report-hoverbox');
    if (box) return box;
    if (getComputedStyle(mount).position === 'static') mount.style.position = 'relative';
    box = document.createElement('div');
    box.className = 'ar-report-hoverbox';
    box.setAttribute('aria-hidden', 'true');
    box.style.cssText = [
      'position:absolute',
      'top:8px',
      'left:10px',
      'z-index:20',
      'display:none',
      'max-width:min(520px, calc(100vw - 28px))',
      'padding:7px 9px',
      'border:1px solid ' + t.ttBorder,
      'border-radius:6px',
      'background:' + t.ttBg,
      'color:' + t.ttText,
      'font:11px/1.45 "Space Grotesk",system-ui,sans-serif',
      'box-shadow:0 14px 28px rgba(0,0,0,0.16)',
      'pointer-events:none',
      'font-variant-numeric:tabular-nums',
    ].join(';');
    mount.appendChild(box);
    return box;
  }

  function showReportHoverBox(hoverBox, input, t) {
    if (!hoverBox || !input) return;
    const rows = input.rows || [];
    if (!rows.length) {
      hoverBox.style.display = 'none';
      return;
    }
    hoverBox.innerHTML =
      '<div style="font-weight:800;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;">' +
        escHtml(input.heading || 'Chart') +
      '</div>' +
      '<div style="color:' + t.muted + ';font-size:10px;margin-bottom:5px;white-space:nowrap;">' +
        escHtml(input.date || '') +
      '</div>' +
      rows.map((row) =>
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:14px;border-top:1px solid rgba(148,163,184,0.14);padding-top:2px;margin-top:2px;white-space:nowrap;">' +
          '<span style="color:' + escHtml(row.color || t.muted) + ';">' + escHtml(row.label) + '</span>' +
          '<strong style="white-space:nowrap;">' + escHtml(row.value) + '</strong>' +
        '</div>'
      ).join('');
    hoverBox.style.display = 'block';
  }

  function resolveDateFromAxisValue(xRaw, dates) {
    if (xRaw == null) return '';
    if (typeof xRaw === 'number' && Number.isFinite(xRaw)) {
      const i = Math.round(xRaw);
      if (i >= 0 && i < dates.length) return dates[i];
    }
    const s = String(xRaw).slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(s) && dates.indexOf(s) >= 0) return s;
    return '';
  }

  function clickPointFromEvent(event) {
    if (!event) return null;
    if (event.point && Array.isArray(event.point) && event.point.length >= 2) {
      return [event.point[0], event.point[1]];
    }
    if (event.offsetX != null && event.offsetY != null) {
      return [event.offsetX, event.offsetY];
    }
    const inner = event.event;
    if (inner && inner.offsetX != null && inner.offsetY != null) {
      return [inner.offsetX, inner.offsetY];
    }
    return null;
  }

  function resolveDateFromPixel(chart, dates, pixel) {
    if (!chart || !pixel || !dates.length) return '';
    try {
      if (!chart.containPixel({ gridIndex: 0 }, pixel)) return '';
      const coord = chart.convertFromPixel({ gridIndex: 0 }, pixel);
      if (!coord || !coord.length) return '';
      return resolveDateFromAxisValue(coord[0], dates);
    } catch (_e) {
      return '';
    }
  }

  function sliceDateFromClick(chart, dates, points, event) {
    const pixel = clickPointFromEvent(event);
    if (!pixel) return '';
    const date = resolveDateFromPixel(chart, dates, pixel);
    if (!date) return '';
    const idx = dates.indexOf(date);
    const point = idx >= 0 ? points[idx] : null;
    if (!point || point.min == null || point.max == null) return '';
    return date;
  }

  function normProviderKey(name) {
    return String(name || '')
      .trim()
      .replace(/[\u00A0\u2000-\u200B\uFEFF]/g, ' ')
      .replace(/\s+/g, ' ')
      .toLowerCase();
  }

  function resolveFocusedProvider(model) {
    const focus = normProviderKey(model && model.focusProvider);
    if (!focus || !model || !Array.isArray(model.providers)) return null;
    return model.providers.find((p) => normProviderKey(p.label) === focus) || null;
  }

  function pointsFromProviderSeries(dates, providerSeries) {
    if (!providerSeries || !providerSeries.byDate) return [];
    return (dates || []).map((date) => {
      const point = providerSeries.byDate[date];
      if (!point) return { date, min: null, max: null, mean: null, count: 0 };
      return {
        date,
        min: point.min,
        max: point.max,
        mean: point.mean,
        count: point.count || 0,
      };
    });
  }

  function ribbonHeadingForModel(model) {
    const focus = String(model && model.focusProvider || '').trim();
    if (!focus) return 'Visible ribbon';
    const brand = window.LocalCdrBrand;
    if (brand && brand.providerMeta) {
      const meta = brand.providerMeta(focus);
      if (meta && meta.short) return String(meta.short);
    }
    return focus;
  }

  function syncReportHoverBox(hoverBox, anchorYmd, dates, points, t, rbaContext, heading) {
    const anchor = String(anchorYmd || '').slice(0, 10);
    if (!anchor || dates.indexOf(anchor) < 0) {
      if (hoverBox) hoverBox.style.display = 'none';
      return;
    }
    const idx = dates.indexOf(anchor);
    const point = points[idx];
    const emDash = '\u2014';
    const rows = [];
    if (!point || point.min == null || point.max == null) {
      rows.push(
        { label: 'Min', value: emDash },
        { label: 'Mean', value: emDash },
        { label: 'Max', value: emDash },
      );
    } else {
      rows.push(
        { label: 'Min', value: fmtHoverRate(point.min) },
        { label: 'Mean', value: fmtHoverRate(point.mean) },
        { label: 'Max', value: fmtHoverRate(point.max) },
      );
    }
    const ctx = rbaContext || {};
    const rbaChanges = ctx.changes || [];
    const rbaStep = ctx.step || [];
    const rbaColor = ctx.color || '#eab308';
    const rbaToday = rbaChanges.filter((c) => c.snap === anchor);
    if (rbaToday.length) {
      rbaToday.forEach((c) => {
        const prior = c.priorRate != null ? c.priorRate.toFixed(2) + '%' : emDash;
        const arrow = c.priorRate != null && c.rate > c.priorRate ? '\u2191'
          : c.priorRate != null && c.rate < c.priorRate ? '\u2193' : '\u2192';
        rows.push({
          label: 'RBA ' + c.date,
          value: prior + ' ' + arrow + ' ' + c.rate.toFixed(2) + '%',
          color: rbaColor,
        });
      });
    } else {
      const stepRate = rbaStep[idx];
      if (stepRate != null) {
        rows.push({ label: 'RBA target', value: fmtHoverRate(stepRate), color: rbaColor });
      }
    }
    showReportHoverBox(hoverBox, {
      heading: heading || 'Visible ribbon',
      date: fmtReportDateYmd(anchor),
      rows,
    }, t);
  }

  function rbaChangeBp(change) {
    if (!change || change.priorRate == null) return NaN;
    const rate = Number(change.rate);
    const prior = Number(change.priorRate);
    if (!Number.isFinite(rate) || !Number.isFinite(prior)) return NaN;
    return Math.round((rate - prior) * 100);
  }

  /** Snap RBA decision dates to plotted run-dates (first run on/after the decision). */
  function rbaMarkData(dates) {
    const api = window.AR && window.AR.rbaCashRate;
    if (!api || !dates.length) return [];
    const first = dates[0];
    const last = dates[dates.length - 1];
    let changes = (api.changesWithinWindow(first, last) || []).filter((change) => {
      const bp = rbaChangeBp(change);
      return Number.isFinite(bp) && bp !== 0;
    });
    if (
      !changes.length
      && typeof api.latestChangeOnOrBefore === 'function'
    ) {
      const latest = api.latestChangeOnOrBefore(last);
      if (latest) {
        const bp = rbaChangeBp(latest);
        if (Number.isFinite(bp) && bp !== 0 && latest.date < first) {
          changes = [latest];
        }
      }
    }
    if (!changes.length) return [];
    const dateSet = {};
    dates.forEach((d) => { dateSet[d] = true; });
    return changes.map((change) => {
      let snap = change.date;
      if (!dateSet[snap]) {
        for (let i = 0; i < dates.length; i += 1) {
          if (dates[i] >= change.date) { snap = dates[i]; break; }
          snap = dates[i];
        }
      }
      return { ...change, snap };
    });
  }

  /** Cash rate stepped line — one value per plotted run date (AustralianRates parity). */
  function rbaStepData(dates) {
    const api = window.AR && window.AR.rbaCashRate;
    if (!api || typeof api.rateAsOf !== 'function') return dates.map(() => null);
    return dates.map((date) => {
      const rate = api.rateAsOf(date);
      return Number.isFinite(rate) ? rate / 100 : null;
    });
  }

  /**
   * Amber vertical bands + bps labels on category axis (site ar-chart-report-plot-series-builders.js).
   */
  function buildRbaChangeMarkAreaPairs(dates, changes) {
    const out = [];
    (changes || []).forEach((row) => {
      const d = String(row.snap || row.date || '').slice(0, 10);
      const ix = dates.indexOf(d);
      if (ix < 0) return;
      const d2 = ix + 1 < dates.length ? dates[ix + 1] : d;
      const change = rbaChangeBp(row);
      const start = { xAxis: d };
      if (Number.isFinite(change) && change !== 0) {
        const bps = Math.abs(change);
        const sign = change > 0 ? '+' : '-';
        const headText = sign + bps + ' bps';
        const arrowGlyph = change > 0 ? '\u25b2' : '\u25bc';
        const arrowBlock = Array(5).fill(arrowGlyph).join('\n');
        start.name = headText;
        start.label = {
          show: true,
          position: 'insideTop',
          distance: 2,
          align: 'center',
          verticalAlign: 'top',
          formatter: () => '{head|' + headText + '}\n{arr|' + arrowBlock + '}',
          rich: {
            head: {
              fontSize: 11,
              fontWeight: 700,
              color: '#fef9c3',
              lineHeight: 16,
              align: 'center',
              textBorderColor: 'rgba(15,23,42,0.75)',
              textBorderWidth: 2,
            },
            arr: {
              fontSize: 13,
              fontWeight: 700,
              color: '#fde047',
              lineHeight: 12,
              align: 'center',
              textBorderColor: 'rgba(15,23,42,0.65)',
              textBorderWidth: 1,
            },
          },
        };
      }
      out.push([start, { xAxis: d2 }]);
    });
    return out;
  }

  function drawBankHistory(chart, model) {
    const t = theme();
    const dates = model.dates || [];
    const focused = resolveFocusedProvider(model);
    const points = focused ? pointsFromProviderSeries(dates, focused) : (model.points || []);
    const hoverHeading = ribbonHeadingForModel(model);
    if (!dates.length || !points.length) {
      chart.clear();
      return;
    }
    const minData = points.map((p) => p.min);
    const maxData = points.map((p) => p.max);
    const deltaData = points.map((p) => (p.min != null && p.max != null) ? Math.max(0, p.max - p.min) : null);
    const meanData = points.map((p) => p.mean);

    const ribbonColor = t.ribbon;
    const fillColor = hexToRgba(ribbonColor, 0.5);
    const rbaColor = '#f59e0b';
    const rbaChanges = rbaMarkData(dates);
    const rbaMarkPairs = buildRbaChangeMarkAreaPairs(dates, rbaChanges);
    const rbaStep = rbaStepData(dates);
    const bandYMin = minData.reduce((acc, v) => {
      if (v == null || !Number.isFinite(v)) return acc;
      return acc == null || v < acc ? v : acc;
    }, null);

    const series = [
      {
        name: 'RBA',
        type: 'line',
        data: rbaStep,
        showSymbol: false,
        connectNulls: false,
        step: 'end',
        lineStyle: { color: rbaColor, width: 2, type: 'dashed', opacity: 0.85 },
        itemStyle: { color: rbaColor },
        tooltip: { show: false },
        emphasis: { disabled: true },
        z: 1,
      },
      // Min as transparent base for stacked area fill.
      {
        name: 'Min (base)',
        type: 'line',
        stack: 'ribbon',
        data: minData,
        showSymbol: false,
        connectNulls: false,
        silent: true,
        lineStyle: { opacity: 0, width: 0 },
        areaStyle: { opacity: 0 },
        emphasis: { disabled: true },
        z: 2,
      },
      // Fill between min and max.
      {
        name: 'Range',
        type: 'line',
        stack: 'ribbon',
        data: deltaData,
        showSymbol: false,
        connectNulls: false,
        silent: true,
        lineStyle: { opacity: 0, width: 0 },
        areaStyle: { color: fillColor, opacity: 1 },
        emphasis: { disabled: true },
        z: 2.01,
      },
      // Visible min line.
      {
        name: 'Min',
        type: 'line',
        data: minData,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: ribbonColor, width: 0.8, opacity: 0.45 },
        itemStyle: { color: ribbonColor },
        tooltip: { show: false },
        emphasis: { disabled: true },
        z: 3,
      },
      // Visible max line.
      {
        name: 'Max',
        type: 'line',
        data: maxData,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: ribbonColor, width: 0.8, opacity: 0.45 },
        itemStyle: { color: ribbonColor },
        tooltip: { show: false },
        emphasis: { disabled: true },
        z: 3,
      },
      // Mean line — thicker ribbon centre.
      {
        name: 'Mean',
        type: 'line',
        data: meanData,
        showSymbol: false,
        connectNulls: false,
        smooth: true,
        lineStyle: { color: ribbonColor, width: 2.0, opacity: 0.9, cap: 'round', join: 'round' },
        itemStyle: { color: ribbonColor },
        tooltip: { show: false },
        emphasis: { focus: 'self', lineStyle: { width: 2.6 } },
        z: 4,
      },
    ];

    if (rbaMarkPairs.length && bandYMin != null) {
      series.push({
        name: 'RBA change',
        type: 'line',
        data: dates.map(() => bandYMin),
        showSymbol: false,
        silent: true,
        lineStyle: { width: 0, opacity: 0 },
        tooltip: { show: false },
        emphasis: { disabled: true },
        markArea: {
          silent: true,
          itemStyle: {
            color: 'rgba(234, 179, 8, 0.42)',
            borderWidth: 1,
            borderColor: 'rgba(202, 138, 4, 0.55)',
          },
          data: rbaMarkPairs,
        },
        z: 5,
      });
    }

    const hoverBox = ensureReportHoverBox(_chartEl, t);

    if (chart._localHoverCleanup) {
      try { chart._localHoverCleanup(); } catch (_e) {}
      chart._localHoverCleanup = null;
    }

    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      grid: { top: rbaMarkPairs.length ? 36 : 14, bottom: 28, left: 52, right: 16, containLabel: true },
      axisPointer: {
        link: [{ xAxisIndex: [0] }],
        label: {
          backgroundColor: t.ttBg,
          borderColor: t.ttBorder,
          borderWidth: 1,
          color: t.ttText,
          fontSize: 10,
          padding: [3, 6],
        },
        lineStyle: { color: t.crosshair, width: 1.4, type: 'dashed' },
      },
      xAxis: {
        type: 'category',
        boundaryGap: dates.length < 2,
        data: dates,
        axisLabel: {
          color: t.muted,
          fontSize: 11,
          hideOverlap: true,
          formatter: (v) => String(v).slice(5),
        },
        axisLine: { lineStyle: { color: t.line } },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        min: (v) => Math.max(0, Math.floor((v.min - 0.003) * 1000) / 1000),
        max: (v) => Math.ceil((v.max + 0.003) * 1000) / 1000,
        axisLabel: { formatter: pctAxis, color: t.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: t.grid } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      tooltip: {
        trigger: 'axis',
        showContent: false,
        axisPointer: { type: 'line' },
      },
      legend: { show: false },
      series: series,
    }, true);

    function notifyHoverDate(anchorYmd) {
      if (typeof model.onHoverDateChange === 'function') {
        model.onHoverDateChange(String(anchorYmd || '').slice(0, 10));
      }
    }

    function onAxisPointer(ev) {
      const ax0 = ev && ev.axesInfo && ev.axesInfo[0];
      if (!ax0) return;
      const anchor = resolveDateFromAxisValue(ax0.value, dates);
      if (!anchor) return;
      notifyHoverDate(anchor);
      syncReportHoverBox(hoverBox, anchor, dates, points, t, {
        changes: rbaChanges,
        step: rbaStep,
        color: rbaColor,
      }, hoverHeading);
    }
    function onGlobalOut() {
      notifyHoverDate('');
      if (hoverBox) hoverBox.style.display = 'none';
    }

    function onChartClick(event) {
      if (typeof model.onSliceClick !== 'function') return;
      const date = sliceDateFromClick(chart, dates, points, event);
      model.onSliceClick(date);
    }

    chart.on('updateAxisPointer', onAxisPointer);
    const zr = chart.getZr();
    zr.on('globalout', onGlobalOut);
    zr.on('click', onChartClick);
    chart._localHoverCleanup = function () {
      chart.off('updateAxisPointer', onAxisPointer);
      zr.off('globalout', onGlobalOut);
      zr.off('click', onChartClick);
      notifyHoverDate('');
      if (hoverBox) hoverBox.style.display = 'none';
    };
    notifyHoverDate(dates.length ? dates[dates.length - 1] : '');
    chart.resize();
  }

  function drawEnergy(chart, payload) {
    const t = theme();
    const rows = (payload && payload.items) || [];
    const focus = String((payload && payload.focusProvider) || '').trim().toLowerCase();
    const mount = chart.getDom();
    const hoverBox = ensureReportHoverBox(mount, t);
    if (!rows.length) {
      chart.clear();
      if (hoverBox) hoverBox.style.display = 'none';
      return;
    }
    if (chart._localHoverCleanup) {
      try { chart._localHoverCleanup(); } catch (_e) {}
      chart._localHoverCleanup = null;
    }
    const sorted = rows.slice();
    const bw = Math.max(6, Math.min(20, Math.floor(380 / Math.max(sorted.length, 1))));
    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      grid: { top: 8, bottom: 44, left: 8, right: 60, containLabel: true },
      xAxis: {
        type: 'value',
        axisLabel: { color: t.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: t.line } },
        axisLine: { show: false }, axisTick: { show: false },
      },
      yAxis: {
        type: 'category',
        data: sorted.map((d) => d.label),
        inverse: false,
        axisLabel: {
          color: t.text, fontSize: 11,
          formatter: (v) => v.length > 24 ? v.slice(0, 22) + '…' : v,
        },
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      },
      tooltip: { trigger: 'item', showContent: false },
      series: [{
        type: 'bar', barWidth: bw,
        data: sorted.map((d, i) => {
          const dimmed = focus && String(d.label || '').toLowerCase() !== focus;
          const color = PALETTE[i % PALETTE.length];
          return {
            value: d.value,
            name: d.label,
            itemStyle: {
              color: dimmed ? hexToRgba(color, 0.28) : color,
              borderRadius: 2,
            },
          };
        }),
        label: { show: true, position: 'right', formatter: '{c}', color: t.muted, fontSize: 10 },
      }],
    }, true);

    function onBarHover(params) {
      if (!params || params.componentType !== 'series') return;
      const label = String(params.name || sorted[params.dataIndex]?.label || '');
      const value = params.value;
      showReportHoverBox(hoverBox, {
        heading: label || 'Provider',
        date: 'Plan count',
        rows: [{ label: 'Plans', value: String(value), color: t.text }],
      }, t);
    }
    function onGlobalOut() {
      if (hoverBox) hoverBox.style.display = 'none';
    }
    chart.on('mouseover', onBarHover);
    chart.on('globalout', onGlobalOut);
    const zr = chart.getZr();
    zr.on('globalout', onGlobalOut);
    chart._localHoverCleanup = function () {
      chart.off('mouseover', onBarHover);
      chart.off('globalout', onGlobalOut);
      zr.off('globalout', onGlobalOut);
      if (hoverBox) hoverBox.style.display = 'none';
    };
    chart.resize();
  }

  function draw(container, items, sector) {
    const chart = getChart(container);
    if (!chart) return;
    if (items && items.kind === 'bank-history') {
      drawBankHistory(chart, items);
      return;
    }
    if (items && items.kind === 'energy-counts') {
      drawEnergy(chart, items);
      return;
    }
    if (!items || !items.length) { chart.clear(); return; }
    if (sector === 'energy') drawEnergy(chart, { items: items, focusProvider: '' });
    else { chart.clear(); }
  }

  window.LocalCdrChart = { draw };
})();
