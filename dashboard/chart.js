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

  function hexToRgba(hex, alpha) {
    const m = String(hex).match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    if (!m) return 'rgba(59, 130, 246, ' + (alpha != null ? alpha : 0.5) + ')';
    const a = alpha != null ? alpha : 0.5;
    return 'rgba(' + parseInt(m[1], 16) + ',' + parseInt(m[2], 16) + ',' + parseInt(m[3], 16) + ',' + a + ')';
  }

  const PALETTE = [
    '#2563eb', '#27c27a', '#f0b90b', '#f97316', '#8b5cf6',
    '#ef4444', '#14b8a6', '#64748b', '#a78bfa', '#fb923c',
  ];

  function getChart(el) {
    if (!window.echarts) return null;
    if (_chart && _chartEl === el) { try { _chart.resize(); } catch (_e) {} return _chart; }
    if (_chart) { try { window.echarts.dispose(_chart); } catch (_e) {} _chart = null; }
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

  function ribbonTooltipHtml(date, point, providers, t, focusProvider) {
    const rows = ['<div style="font-weight:800;margin-bottom:4px;">' + escHtml(date) + '</div>'];
    if (!point || point.min == null) {
      rows.push('<div style="color:' + t.muted + ';">No rates</div>');
      return rows.join('');
    }
    const range = (Math.abs(point.max - point.min) < 0.00001)
      ? pct(point.min)
      : pct(point.min) + ' – ' + pct(point.max);
    const spread = Math.round((point.max - point.min) * 10000);
    rows.push(
      '<div style="display:grid;grid-template-columns:auto auto;gap:2px 12px;font-variant-numeric:tabular-nums;">' +
        '<span style="color:' + t.muted + ';">Range</span><span style="font-weight:700;">' + escHtml(range) + '</span>' +
        '<span style="color:' + t.muted + ';">Mean (μ)</span><span style="font-weight:700;">' + escHtml(pct(point.mean)) + '</span>' +
        '<span style="color:' + t.muted + ';">Spread</span><span>' + spread + 'bp</span>' +
        '<span style="color:' + t.muted + ';">Products</span><span>' + point.count + '</span>' +
      '</div>'
    );
    if (providers && providers.length && !focusProvider) {
      // List the lender best/worst at this date — top 6 by best rate.
      const lenders = providers
        .map((p) => p.byDate[date] ? { label: p.label, pt: p.byDate[date] } : null)
        .filter(Boolean);
      if (lenders.length) {
        lenders.sort((a, b) => a.pt.min - b.pt.min);
        rows.push('<div style="margin-top:6px;padding-top:6px;border-top:1px solid ' + t.ttBorder + ';">');
        rows.push('<div style="color:' + t.muted + ';margin-bottom:2px;">Lender ranges</div>');
        const shown = lenders.slice(0, 6);
        shown.forEach((l) => {
          const r = Math.abs(l.pt.max - l.pt.min) < 0.00001 ? pct(l.pt.min) : pct(l.pt.min) + '–' + pct(l.pt.max);
          rows.push('<div style="display:flex;justify-content:space-between;gap:12px;">' +
            '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px;">' + escHtml(l.label) + '</span>' +
            '<span style="font-variant-numeric:tabular-nums;">' + escHtml(r) + '</span></div>');
        });
        if (lenders.length > shown.length) {
          rows.push('<div style="color:' + t.muted + ';">+' + (lenders.length - shown.length) + ' more</div>');
        }
        rows.push('</div>');
      }
    } else if (focusProvider) {
      rows.push('<div style="margin-top:6px;padding-top:6px;border-top:1px solid ' + t.ttBorder + ';color:' + t.muted + ';">Focused: ' + escHtml(focusProvider) + '</div>');
    }
    return rows.join('');
  }

  function drawBankHistory(chart, model) {
    const t = theme();
    const dates = model.dates || [];
    const points = model.points || [];
    const providers = model.providers || [];
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

    const series = [
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
      // Mean line — thicker.
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

    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      grid: { top: 14, bottom: 28, left: 52, right: 16, containLabel: true },
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
        axisPointer: {
          show: true,
          type: 'line',
          lineStyle: { color: t.crosshair, width: 1.5 },
          label: {
            show: true,
            backgroundColor: t.ttBg,
            borderColor: t.ttBorder,
            color: t.ttText,
            padding: [3, 6],
            fontSize: 11,
          },
          z: 10,
        },
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
        confine: true,
        transitionDuration: 0,
        hideDelay: 60,
        backgroundColor: t.ttBg,
        borderColor: t.ttBorder,
        textStyle: { color: t.ttText, fontSize: 12 },
        extraCssText: 'box-shadow: 0 6px 18px rgba(0,0,0,0.28);',
        axisPointer: { type: 'line', lineStyle: { color: t.crosshair, width: 1.5 } },
        formatter: function (params) {
          const dataIndex = params && params[0] ? params[0].dataIndex : 0;
          const date = dates[dataIndex] || '';
          const point = points[dataIndex];
          return ribbonTooltipHtml(date, point, providers, t, model.focusProvider || '');
        },
      },
      legend: { show: false },
      series: series,
    }, true);
    chart.resize();
  }

  function drawEnergy(chart, items) {
    const t = theme();
    const sorted = items.slice().sort((a, b) => b.value - a.value);
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
      series: [{
        type: 'bar', barWidth: bw,
        data: sorted.map((d, i) => ({ value: d.value, itemStyle: { color: PALETTE[i % PALETTE.length], borderRadius: 2 } })),
        label: { show: true, position: 'right', formatter: '{c}', color: t.muted, fontSize: 10 },
      }],
    }, true);
    chart.resize();
  }

  function draw(container, items, sector) {
    const chart = getChart(container);
    if (!chart) return;
    if (items && items.kind === 'bank-history') {
      drawBankHistory(chart, items);
      return;
    }
    if (!items || !items.length) { chart.clear(); return; }
    if (sector === 'energy') drawEnergy(chart, items);
    else { chart.clear(); }
  }

  window.LocalCdrChart = { draw };
})();
