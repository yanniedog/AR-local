(function () {
  'use strict';

  const PALETTE = ['#2563eb', '#16a34a', '#dc2626', '#9333ea', '#0891b2', '#ca8a04', '#db2777', '#64748b'];
  const { pct, rateValue } = window.LocalCdrUtils;

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

  function escHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[ch]);
  }

  function num(value) {
    return Number(value || 0).toLocaleString('en-AU');
  }

  function minMax(rows) {
    let min = null;
    let max = null;
    for (let index = 0; index < rows.length; index += 1) {
      const value = rateValue(rows[index].rate);
      if (!Number.isFinite(value) || value <= 0) continue;
      if (min == null || value < min) min = value;
      if (max == null || value > max) max = value;
    }
    return { min, max };
  }

  function bestRate(rows, descending) {
    const mm = minMax(rows);
    if (mm.min == null) return null;
    return descending ? mm.max : mm.min;
  }

  function rangeText(rows) {
    const mm = minMax(rows);
    if (mm.min == null) return 'no rates';
    return mm.min === mm.max ? pct(mm.min) : `${pct(mm.min)}-${pct(mm.max)}`;
  }

  function hashText(value) {
    const raw = String(value || '');
    let hash = 2166136261;
    for (let index = 0; index < raw.length; index += 1) {
      hash ^= raw.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function swatch(row) {
    return PALETTE[hashText(row && row.provider) % PALETTE.length];
  }

  function fieldLabel(field) {
    const labels = { provider: 'Provider', loan_purpose: 'Purpose', category: 'Category', term: 'Term', rate_type: 'Rate type', repayment_type: 'Repayment', product_name: 'Product' };
    return labels[field] || field;
  }

  function tierFields(section) {
    if (section === 'Mortgage') return ['loan_purpose', 'rate_type', 'repayment_type', 'provider', 'product_name'];
    if (section === 'TD') return ['term', 'provider', 'product_name', 'rate_type'];
    return ['category', 'provider', 'product_name', 'rate_type'];
  }

  function tierValue(row, field) {
    const value = field === 'provider' ? row.provider
      : field === 'term' ? (row.term || row.application_frequency)
        : row[field];
    return String(value || 'Other').replace(/\s+/g, ' ').trim() || 'Other';
  }

  function buildTree(rows, fields, index, descending) {
    if (!rows.length) return { kind: 'empty', rows: [] };
    if (index >= fields.length) return { kind: 'leaves', rows };
    const field = fields[index];
    const grouped = new Map();
    rows.forEach((row) => {
      const value = tierValue(row, field);
      if (!grouped.has(value)) grouped.set(value, []);
      grouped.get(value).push(row);
    });
    const groups = [...grouped.entries()].map(([label, groupRows]) => ({
      label,
      rows: groupRows,
      best: bestRate(groupRows, descending),
      child: buildTree(groupRows, fields, index + 1, descending),
    })).sort((a, b) => {
      if (a.best == null && b.best == null) return a.label.localeCompare(b.label);
      if (a.best == null) return 1;
      if (b.best == null) return -1;
      return descending ? b.best - a.best : a.best - b.best;
    });
    return { kind: 'branch', field, groups, rows };
  }

  function prunePath(tree, activePath) {
    const parts = String(activePath || '').split('>').filter(Boolean);
    const kept = [];
    let node = tree;
    for (let index = 0; index < parts.length; index += 1) {
      const groupIndex = Number(parts[index]);
      if (!node || node.kind !== 'branch' || !Number.isInteger(groupIndex) || !node.groups[groupIndex]) break;
      kept.push(String(groupIndex));
      node = node.groups[groupIndex].child;
    }
    return kept.join('>');
  }

  function parentPath(path) {
    const text = String(path || '');
    const index = text.lastIndexOf('>');
    return index < 0 ? '' : text.slice(0, index);
  }

  function isExpanded(path, activePath) {
    return activePath === path || String(activePath || '').startsWith(path + '>');
  }

  function focusedChildIndex(path, activePath) {
    const active = String(activePath || '');
    if (!active) return -1;
    if (!path) return Number(active.split('>')[0]);
    if (!active.startsWith(path + '>')) return -1;
    return Number(active.slice(path.length + 1).split('>')[0]);
  }

  function formatLabel(field, label) {
    if (field === 'provider') return label;
    return fieldLabel(field) + ': ' + label;
  }

  function renderRateRange(parent, rows, best, descending) {
    const mm = minMax(rows);
    if (mm.min == null) return;
    const showRange = mm.min !== mm.max;
    const bestValue = descending ? mm.max : mm.min;
    const first = child(parent, 'span', best === bestValue ? 'ar-ribbon-best' : '', pct(mm.min));
    if (!showRange) return;
    child(parent, 'span', 'ar-ribbon-rate-sep', '-');
    const last = child(parent, 'span', best === bestValue ? 'ar-ribbon-best' : '', pct(mm.max));
    if (descending) {
      first.className = '';
      last.className = best === bestValue ? 'ar-ribbon-best' : '';
    }
  }

  function renderBreadcrumbs(container, tree, activePath) {
    const bar = child(container, 'div', 'ar-report-underchart-tree-breadcrumbs');
    const root = child(bar, 'button', 'ar-report-underchart-tree-crumb secondary' + (!activePath ? ' is-current' : ''), 'All');
    root.type = 'button';
    root.dataset.localHierarchyAction = 'root';
    root.dataset.localHierarchyPath = '';
    let node = tree;
    let path = '';
    String(activePath || '').split('>').filter(Boolean).forEach((part, index) => {
      const groupIndex = Number(part);
      if (!node || node.kind !== 'branch' || !node.groups[groupIndex]) return;
      const group = node.groups[groupIndex];
      path = path ? path + '>' + groupIndex : String(groupIndex);
      child(bar, 'span', 'ar-report-underchart-tree-crumb-sep', '>');
      const crumb = child(bar, 'button', 'ar-report-underchart-tree-crumb secondary' + (index === String(activePath).split('>').length - 1 ? ' is-current' : ''), formatLabel(node.field, group.label));
      crumb.type = 'button';
      crumb.title = formatLabel(node.field, group.label);
      crumb.dataset.localHierarchyAction = 'crumb';
      crumb.dataset.localHierarchyPath = path;
      node = group.child;
    });
  }

  function renderLeaf(container, row, depth, best, descending) {
    const rateRow = child(container, 'div', 'ar-report-infobox-trow ar-report-infobox-trow--leaf ar-report-infobox-row');
    rateRow.style.setProperty('--ar-ribbon-depth', String(depth));
    const dot = child(rateRow, 'span', 'ar-report-infobox-tsw');
    dot.style.setProperty('--ar-swatch-color', swatch(row));
    const label = child(rateRow, 'span', 'ar-report-infobox-tlabel');
    const bits = [row.rate_type, row.application_type, row.repayment_type || row.loan_purpose].filter(Boolean);
    child(label, 'span', 'ar-ribbon-tleaf-product', bits.join(' - ') || 'Rate');
    const rate = child(rateRow, 'span', 'ar-report-infobox-trate');
    renderRateRange(rate, [row], best, descending);
  }

  function renderBranch(container, node, group, path, depth, activePath, state) {
    const expanded = isExpanded(path, activePath);
    const targetPath = expanded ? parentPath(path) : path;
    const row = child(container, 'div', 'ar-report-infobox-trow ar-report-infobox-trow--branch');
    row.style.setProperty('--ar-ribbon-depth', String(depth));
    row.dataset.localHierarchyAction = 'toggle';
    row.dataset.localHierarchyPath = targetPath;
    row.setAttribute('data-ribbon-tree-path', path);
    row.setAttribute('role', 'button');
    row.setAttribute('aria-expanded', expanded ? 'v' : '>');
    row.setAttribute('aria-label', (expanded ? 'v' : '>') + formatLabel(node.field, group.label));
    row.tabIndex = 0;
    child(row, 'span', 'ar-report-infobox-twist', expanded ? 'v' : '>');
    const label = child(row, 'span', 'ar-report-infobox-tlabel');
    if (node.field === 'provider' && window.LocalCdrBrand) {
      window.LocalCdrBrand.appendProviderBadge(label, group.label, true);
    } else {
      label.textContent = formatLabel(node.field, group.label);
      label.title = formatLabel(node.field, group.label);
    }
    const rate = child(row, 'span', 'ar-report-infobox-trate');
    renderRateRange(rate, group.rows, state.globalBest, state.descending);
  }

  function renderTree(container, node, path, depth, activePath, state) {
    if (!node || node.kind === 'empty') return;
    if (node.kind === 'leaves') {
      const sorted = node.rows.slice().sort((a, b) => state.descending ? rateValue(b.rate) - rateValue(a.rate) : rateValue(a.rate) - rateValue(b.rate));
      sorted.forEach((row) => renderLeaf(container, row, depth, state.globalBest, state.descending));
      return;
    }
    const focusIndex = focusedChildIndex(path, activePath);
    node.groups.forEach((group, index) => {
      if (focusIndex >= 0 && index !== focusIndex) return;
      const subPath = path ? path + '>' + index : String(index);
      renderBranch(container, node, group, subPath, depth, activePath, state);
      if (isExpanded(subPath, activePath)) {
        const nest = child(container, 'div', 'ar-report-infobox-tnest');
        renderTree(nest, group.child, subPath, depth + 1, activePath, state);
      }
    });
  }

  function panelTheme() {
    const cssVar = window.LocalCdrUtils.cssVar;
    return { ttText: cssVar('--ar-text', '#e5e7eb'), ttBg: cssVar('--ar-surface-2', '#111827'), ttBorder: cssVar('--ar-line', '#334155'), muted: cssVar('--ar-text-muted', '#94a3b8') };
  }

  function ensurePanel(container) {
    if (container.__localPanel) {
      if (!container.contains(container.__localPanel.el)) container.appendChild(container.__localPanel.el);
      return container.__localPanel;
    }
    clear(container);
    const creator = window.AR && window.AR.chartReportPlotHierarchyPanel;
    const panel = creator && creator.createRibbonHierarchyPanel
      ? creator.createRibbonHierarchyPanel(panelTheme(), escHtml)
      : null;
    if (!panel) return null;
    container.appendChild(panel.el);
    container.__localPanel = panel;
    return panel;
  }

  function render(container, countEl, rows, state) {
    const visible = rows;
    const productCount = new Set(visible.map((row) => row.product_key || row.product_id || row.product_name)).size;
    const providerCount = new Set(visible.map((row) => row.provider).filter(Boolean)).size;
    countEl.textContent = `${num(visible.length)} rates / ${num(productCount)} products / ${num(providerCount)} providers`;
    const panel = ensurePanel(container);
    if (!panel) return;
    state.rows = visible;
    state.globalBest = bestRate(visible, state.descending);
    const tree = buildTree(visible, tierFields(state.section), 0, state.descending);
    state.hierarchyPath = prunePath(tree, state.hierarchyPath || '');
    if (!visible.length || tree.kind === 'empty') {
      panel.show({
        heading: state.section + ' hierarchy', meta: 'No rows',
        renderBody: (wrap) => child(wrap, 'div', 'chart-series-empty', 'No hierarchy data available.'),
      });
      return;
    }
    panel.show({
      heading: 'Current slice',
      meta: `${state.manifest.run_date} - ${rangeText(visible)} - ${num(productCount)} products - ${num(providerCount)} providers`,
      compact: true,
      renderBody: (wrap) => {
        renderBreadcrumbs(wrap, tree, state.hierarchyPath || '');
        renderTree(wrap, tree, '', 0, state.hierarchyPath || '', state);
      },
    });
  }

window.LocalCdrHierarchy = { render };
})();
