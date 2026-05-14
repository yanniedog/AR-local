(function () {
  'use strict';

  var _chartEl = null;
  var _chart = null;

  function cssVar(name, fallback) {
    try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback; }
    catch (_e) { return fallback; }
  }

  function theme() {
    return {
      text:   cssVar('--ar-text',         '#e2e8f0'),
      muted:  cssVar('--ar-text-muted',   '#94a3b8'),
      line:   cssVar('--ar-line',         '#1e293b'),
      bg:     cssVar('--ar-surface-2',    '#0f172a'),
      accent: cssVar('--ar-section-accent', cssVar('--ar-accent', '#2563eb')),
    };
  }

  var PALETTE = [
    '#2563eb','#27c27a','#f0b90b','#f97316','#8b5cf6',
    '#ef4444','#14b8a6','#64748b','#a78bfa','#fb923c',
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

  function drawBankHistory(chart, model) {
    var t = theme();
    var dates = model.dates || [];
    var providers = model.providers || [];
    if (!dates.length || !providers.length) {
      chart.clear();
      return;
    }
    var series = [];
    providers.forEach(function (provider, providerIndex) {
      var color = PALETTE[providerIndex % PALETTE.length];
      var baseData = dates.map(function (date) {
        var point = provider.byDate && provider.byDate[date];
        return point ? point.min : null;
      });
      var bandData = dates.map(function (date) {
        var point = provider.byDate && provider.byDate[date];
        return point ? Math.max(0, point.max - point.min) : null;
      });
      var lineData = dates.map(function (date) {
        var point = provider.byDate && provider.byDate[date];
        if (!point) return null;
        return (point.min + point.max) / 2;
      });
      var stack = 'provider-' + providerIndex;
      series.push({
        type: 'line',
        name: provider.label + ' base',
        stack: stack,
        data: baseData,
        showSymbol: false,
        connectNulls: true,
        silent: true,
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0 },
        emphasis: { disabled: true },
      });
      series.push({
        type: 'line',
        name: provider.label,
        stack: stack,
        data: bandData,
        showSymbol: dates.length < 3,
        connectNulls: true,
        lineStyle: { width: 1.3, color: color },
        itemStyle: { color: color },
        areaStyle: { opacity: 0.28, color: color },
        emphasis: { focus: 'series' },
      });
      series.push({
        type: 'line',
        name: provider.label + ' midpoint',
        data: lineData,
        showSymbol: dates.length < 3,
        connectNulls: true,
        symbolSize: 5,
        lineStyle: { width: 1.1, color: color, opacity: 0.8 },
        itemStyle: { color: color },
        tooltip: { show: false },
        emphasis: { disabled: true },
      });
    });
    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      color: PALETTE,
      grid: { top: 14, bottom: 42, left: 44, right: 16, containLabel: false },
      xAxis: {
        type: 'category',
        boundaryGap: dates.length < 2,
        data: dates,
        axisLabel: {
          color: t.muted,
          fontSize: 11,
          hideOverlap: true,
          formatter: function (v) { return String(v).slice(5); },
        },
        axisLine: { lineStyle: { color: t.line } },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        min: function (v) { return Math.max(0, Math.floor((v.min - 0.003) * 1000) / 1000); },
        max: function (v) { return Math.ceil((v.max + 0.003) * 1000) / 1000; },
        axisLabel: { formatter: pctAxis, color: t.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: t.line } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: t.muted, opacity: 0.45 } },
        backgroundColor: t.bg,
        borderColor: t.line,
        textStyle: { color: t.text },
        formatter: function (params) {
          var dataIndex = params && params[0] ? params[0].dataIndex : 0;
          var date = dates[dataIndex] || '';
          var lines = ['<b>' + date + '</b>'];
          providers.slice(0, 18).forEach(function (provider) {
            var point = provider.byDate && provider.byDate[date];
            if (!point) return;
            var rate = Math.abs(point.max - point.min) < 0.00001
              ? pct(point.min)
              : pct(point.min) + ' - ' + pct(point.max);
            lines.push(provider.label + ': ' + rate + ' (' + point.count + ' rates)');
          });
          if (providers.length > 18) lines.push('<small>+' + (providers.length - 18) + ' more providers</small>');
          return lines.join('<br>');
        },
      },
      legend: { show: false },
      series: series,
    }, true);
    chart.resize();
  }

  function drawBanks(chart, items) {
    var t = theme();
    var sorted = items.slice().sort(function (a, b) { return a.min - b.min; });
    var names  = sorted.map(function (d) { return d.label; });
    var baseData  = sorted.map(function (d) { return d.min; });
    var rangeData = sorted.map(function (d, i) {
      return { value: d.max - d.min, itemStyle: { color: PALETTE[i % PALETTE.length], borderRadius: 2 } };
    });
    var rateLabels = sorted.map(function (d) {
      return d.max - d.min < 0.0001 ? pct(d.min) : pct(d.min) + '–' + pct(d.max);
    });
    var bw = Math.max(6, Math.min(20, Math.floor(380 / Math.max(sorted.length, 1))));

    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      grid: { top: 8, bottom: 44, left: 8, right: 80, containLabel: true },
      xAxis: {
        type: 'value',
        min: function (v) { return Math.max(0, Math.floor((v.min - 0.003) * 1000) / 1000); },
        max: function (v) { return Math.ceil((v.max + 0.003) * 1000) / 1000; },
        axisLabel: { formatter: function (v) { return (v * 100).toFixed(1) + '%'; }, color: t.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: t.line } },
        axisLine: { show: false }, axisTick: { show: false },
      },
      yAxis: {
        type: 'category', data: names, inverse: false,
        axisLabel: {
          color: t.text, fontSize: 11,
          formatter: function (v) {
            var short = window.AR && window.AR.ribbon && window.AR.ribbon.ribbonBankShortName;
            var s = short ? short(v) : v;
            return s.length > 24 ? s.slice(0, 22) + '…' : s;
          },
        },
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        backgroundColor: t.bg, borderColor: t.line, textStyle: { color: t.text },
        formatter: function (params) {
          var idx = params[0] && params[0].dataIndex;
          var d = sorted[idx];
          if (!d) return '';
          var r = d.max - d.min > 0.0001 ? pct(d.min) + ' – ' + pct(d.max) : pct(d.min);
          return '<b>' + d.label + '</b><br>' + r + (d.count ? '<br><small>' + d.count + ' products</small>' : '');
        },
      },
      series: [
        { type: 'bar', name: '_base', stack: 'r', barWidth: bw, silent: true, data: baseData, itemStyle: { color: 'transparent' } },
        {
          type: 'bar', name: 'range', stack: 'r', barWidth: bw, data: rangeData,
          label: { show: true, position: 'right', formatter: function (p) { return rateLabels[p.dataIndex] || ''; }, color: t.muted, fontSize: 10 },
        },
      ],
    }, true);
    chart.resize();
  }

  function drawEnergy(chart, items) {
    var t = theme();
    var sorted = items.slice().sort(function (a, b) { return b.value - a.value; });
    var bw = Math.max(6, Math.min(20, Math.floor(380 / Math.max(sorted.length, 1))));
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
        data: sorted.map(function (d) { return d.label; }),
        inverse: false,
        axisLabel: {
          color: t.text, fontSize: 11,
          formatter: function (v) { return v.length > 24 ? v.slice(0, 22) + '…' : v; },
        },
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      },
      series: [{
        type: 'bar', barWidth: bw,
        data: sorted.map(function (d, i) { return { value: d.value, itemStyle: { color: PALETTE[i % PALETTE.length], borderRadius: 2 } }; }),
        label: { show: true, position: 'right', formatter: '{c}', color: t.muted, fontSize: 10 },
      }],
    }, true);
    chart.resize();
  }

  function draw(container, items, sector) {
    var chart = getChart(container);
    if (!chart) return;
    if (items && items.kind === 'bank-history') {
      drawBankHistory(chart, items);
      return;
    }
    if (!items || !items.length) { chart.clear(); return; }
    if (sector === 'energy') drawEnergy(chart, items);
    else drawBanks(chart, items);
  }

  window.LocalCdrChart = { draw };
})();
