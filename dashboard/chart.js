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
  const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function canonicalYmd(value) {
    const raw = String(value == null ? '' : value).trim();
    if (!raw) return '';
    const match = raw.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:$|[T\s])/);
    if (!match) return '';
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return '';
    const ts = Date.UTC(year, month - 1, day);
    const check = new Date(ts);
    if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return '';
    const yyyy = String(year).padStart(4, '0');
    const mm = String(month).padStart(2, '0');
    const dd = String(day).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }

  function parseYmdParts(value) {
    const text = canonicalYmd(value);
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    return { year, month, day };
  }

  function formatAxisDateLabel(value) {
    const parts = parseYmdParts(value);
    if (!parts) return '';
    return String(parts.day) + ' ' + MONTH_SHORT[parts.month - 1] + ' ' + String(parts.year);
  }

  function axisLabelIntervalForCount(count) {
    const n = Number(count) || 0;
    if (n <= 0) return 0;
    const width = window.innerWidth || 1280;
    let target = 10;
    if (width < 640) target = 4;
    else if (width < 960) target = 6;
    else if (width < 1280) target = 8;
    const shown = Math.max(1, Math.min(target, n));
    return Math.max(0, Math.ceil(n / shown) - 1);
  }

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

  function normalizeTimelineDates(rawDates) {
    const seen = new Set();
    const dates = [];
    (rawDates || []).forEach((value) => {
      const date = String(value == null ? '' : value).slice(0, 10);
      if (!parseYmdParts(date) || seen.has(date)) return;
      seen.add(date);
      dates.push(date);
    });
    dates.sort();
    return dates;
  }

  function finiteOrNull(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function sanitizeRibbonPoint(date, point) {
    const source = point || {};
    let min = finiteOrNull(source.min);
    let max = finiteOrNull(source.max);
    let mean = finiteOrNull(source.mean);
    if (min != null && max != null && min > max) {
      const swap = min;
      min = max;
      max = swap;
    }
    if (mean != null && min != null && max != null) {
      mean = Math.min(Math.max(mean, min), max);
    } else if (mean == null && min != null && max != null) {
      mean = (min + max) / 2;
    }
    if (min == null || max == null) {
      min = null;
      max = null;
    }
    const countRaw = Number(source.count);
    const count = Number.isFinite(countRaw) && countRaw > 0 ? Math.round(countRaw) : 0;
    return { date, min, max, mean, count };
  }

  function alignPointsToTimeline(dates, rawPoints) {
    const byDate = {};
    (rawPoints || []).forEach((point, index) => {
      const fallback = dates[index] || '';
      const date = String((point && point.date) || fallback).slice(0, 10);
      if (!date || !parseYmdParts(date)) return;
      if (!byDate[date]) byDate[date] = point;
    });
    return dates.map((date) => sanitizeRibbonPoint(date, byDate[date]));
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
    // On narrow viewports, "+25 bps" centred over the leftmost band extends
    // left of the plot area and collides with the y-axis tick labels. Anchor
    // left-aligned inside the band's top-left so the text grows away from
    // the y-axis gutter, and reduce the arrow stack so the annotation block
    // doesn't dominate the chart height.
    const isNarrow = (window.innerWidth || 1280) < 520;
    const arrowCount = isNarrow ? 2 : 5;
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
        const arrowBlock = Array(arrowCount).fill(arrowGlyph).join('\n');
        const labelAlign = isNarrow ? 'left' : 'center';
        const labelPosition = isNarrow ? 'insideTopLeft' : 'insideTop';
        start.name = headText;
        start.label = {
          show: true,
          position: labelPosition,
          distance: 2,
          align: labelAlign,
          verticalAlign: 'top',
          padding: isNarrow ? [0, 0, 0, 3] : 0,
          formatter: () => '{head|' + headText + '}\n{arr|' + arrowBlock + '}',
          rich: {
            head: {
              fontSize: isNarrow ? 10 : 11,
              fontWeight: 700,
              color: '#fef9c3',
              lineHeight: 14,
              align: labelAlign,
              textBorderColor: 'rgba(15,23,42,0.75)',
              textBorderWidth: 2,
            },
            arr: {
              fontSize: isNarrow ? 11 : 13,
              fontWeight: 700,
              color: '#fde047',
              lineHeight: 11,
              align: labelAlign,
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
    const dates = normalizeTimelineDates(model.dates || []);
    const focused = resolveFocusedProvider(model);
    const rawPoints = focused ? pointsFromProviderSeries(dates, focused) : (model.points || []);
    const points = alignPointsToTimeline(dates, rawPoints);
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

    const xAxisLabelInterval = axisLabelIntervalForCount(dates.length);
    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      grid: {
        top: rbaMarkPairs.length ? ((window.innerWidth || 1280) < 520 ? 44 : 36) : 14,
        bottom: 28,
        left: (window.innerWidth || 1280) < 520 ? 44 : 52,
        right: (window.innerWidth || 1280) < 520 ? 10 : 16,
        containLabel: true,
      },
      axisPointer: {
        link: [{ xAxisIndex: [0] }],
        label: {
          backgroundColor: t.ttBg,
          borderColor: t.ttBorder,
          borderWidth: 1,
          color: t.ttText,
          fontSize: 10,
          padding: [3, 6],
          formatter: (params) => formatAxisDateLabel(params && params.value),
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
          hideOverlap: false,
          interval: xAxisLabelInterval,
          formatter: (v, i) => {
            const candidate = i != null && i >= 0 && i < dates.length ? dates[i] : v;
            return formatAxisDateLabel(candidate);
          },
        },
        axisLine: { lineStyle: { color: t.line } },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        min: (v) => {
          const base = Number.isFinite(v && v.min) ? v.min : 0;
          return Math.max(0, Math.floor((base - 0.003) * 1000) / 1000);
        },
        max: (v) => {
          const base = Number.isFinite(v && v.max) ? v.max : 0;
          return Math.max(0.001, Math.ceil((base + 0.003) * 1000) / 1000);
        },
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

    // Touch scrubbing: ECharts' built-in touch handling moves the axisPointer
    // on tap but NOT during a finger drag, so on mobile the hierarchy slice
    // preview (driven by updateAxisPointer → onHoverDateChange) only updated on
    // tap. Translate touchmove into a showTip dispatch at the finger position;
    // that moves the axisPointer and fires updateAxisPointer, so the existing
    // hover→hierarchy chain runs continuously as the finger drags across slices.
    // A pure tap (no move) still falls through to zr 'click' → onSliceClick (pin).
    const chartDom = typeof chart.getDom === 'function' ? chart.getDom() : null;
    function showTipAtTouch(touch) {
      if (!touch || !chartDom) return false;
      const rect = chartDom.getBoundingClientRect();
      const px = [touch.clientX - rect.left, touch.clientY - rect.top];
      try {
        if (!chart.containPixel({ gridIndex: 0 }, px)) return false;
        chart.dispatchAction({ type: 'showTip', x: px[0], y: px[1] });
      } catch (_e) {
        return false;
      }
      return true;
    }
    // Direction lock: a drag that starts on the plot must still scroll the page
    // when it's primarily vertical. Decide horizontal (scrub) vs vertical
    // (scroll) once the finger passes a small threshold, then stick with it for
    // the gesture. Only horizontal scrubs preventDefault, so vertical swipes
    // that begin over the chart are never stolen from the page (gemini, codex).
    const TOUCH_DECIDE_PX = 8;
    let touchMode = null; // null = undecided, 'h' = scrub, 'v' = page scroll
    let touchStartX = 0;
    let touchStartY = 0;
    function onTouchStartScrub(e) {
      if (!e.touches || e.touches.length !== 1) { touchMode = 'v'; return; }
      touchMode = null;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
    }
    function onTouchMoveScrub(e) {
      if (!e.touches || e.touches.length !== 1) return;
      const touch = e.touches[0];
      if (touchMode === null) {
        const dx = Math.abs(touch.clientX - touchStartX);
        const dy = Math.abs(touch.clientY - touchStartY);
        if (dx < TOUCH_DECIDE_PX && dy < TOUCH_DECIDE_PX) return; // not yet decided
        touchMode = dx > dy ? 'h' : 'v';
      }
      if (touchMode !== 'h') return; // vertical: let the page scroll
      if (showTipAtTouch(touch) && e.cancelable) e.preventDefault();
    }
    if (chartDom) {
      chartDom.addEventListener('touchstart', onTouchStartScrub, { passive: true });
      chartDom.addEventListener('touchmove', onTouchMoveScrub, { passive: false });
    }

    chart._localHoverCleanup = function () {
      chart.off('updateAxisPointer', onAxisPointer);
      zr.off('globalout', onGlobalOut);
      zr.off('click', onChartClick);
      if (chartDom) {
        chartDom.removeEventListener('touchstart', onTouchStartScrub);
        chartDom.removeEventListener('touchmove', onTouchMoveScrub);
      }
      // Do not notifyHoverDate('') here — immediate redraw would flash logo dim state.
      if (hoverBox) hoverBox.style.display = 'none';
    };
    notifyHoverDate(dates.length ? dates[dates.length - 1] : '');
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
    chart.clear();
  }

  window.LocalCdrChart = { draw };
})();
