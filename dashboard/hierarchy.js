(function () {
  'use strict';

  const PALETTE = ['#2563eb', '#16a34a', '#dc2626', '#9333ea', '#0891b2', '#ca8a04', '#db2777', '#64748b'];
  const { historyIndexKey, pct, rateValue } = window.LocalCdrUtils;

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

  function shortBank(name) {
    const brand = window.AR && window.AR.bankBrand;
    if (brand && brand.shortLabel) {
      const short = brand.shortLabel(name);
      if (short && short !== '-') return short;
    }
    return String(name || '').slice(0, 12);
  }

  function rowProductKey(row) {
    return row.product_key || row.product_id || row.plan_id || row.product_name || row.plan_name || '';
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

  /** Deposit sections highlight highest yield; mortgage highlights lowest rate. */
  function highlightMaxForSection(section) {
    return section === 'Savings' || section === 'TD';
  }

  function bestRate(rows, highlightMax) {
    const mm = minMax(rows);
    if (mm.min == null) return null;
    return highlightMax ? mm.max : mm.min;
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

  function chartDatePair(state) {
    const dates = Array.isArray(state.chartDates) ? state.chartDates.filter(Boolean) : [];
    if (dates.length < 2) return { anchor: '', previous: '' };
    const pinned = String(state.chartPinnedDate || '').slice(0, 10);
    const anchor = pinned || String(dates[dates.length - 1] || '').slice(0, 10);
    const ix = dates.indexOf(anchor);
    const anchorIx = ix >= 0 ? ix : dates.length - 1;
    const previous = dates[anchorIx - 1] || '';
    return { anchor: dates[anchorIx] || '', previous };
  }

  function historyRowsFor(rows, state) {
    if (!state || !state.bankHistoryIndex) return [];
    const seenKeys = new Set();
    const out = [];
    rows.forEach((row) => {
      const key = historyIndexKey(row);
      if (!key || key === '||' || seenKeys.has(key)) return;
      seenKeys.add(key);
      (state.bankHistoryIndex[key] || []).forEach((historyRow) => out.push(historyRow));
    });
    return out;
  }

  function bestHistoryValue(rows, highlightMax) {
    const best = bestRate(rows, highlightMax);
    return Number.isFinite(best) ? best : null;
  }

  function historyCompare(rows, state) {
    const pair = chartDatePair(state);
    if (!pair.anchor || !pair.previous) return null;
    const historyRows = historyRowsFor(rows, state);
    const byDate = {};
    historyRows.forEach((row) => {
      const date = String(row.run_date || '');
      if (!date) return;
      if (!byDate[date]) byDate[date] = [];
      byDate[date].push(row);
    });
    const highlightMax = highlightMaxForSection(state.section);
    const latest = bestHistoryValue(byDate[pair.anchor] || [], highlightMax);
    const previous = bestHistoryValue(byDate[pair.previous] || [], highlightMax);
    if (latest == null || previous == null) return null;
    const deltaBp = Math.round((latest - previous) * 10000);
    const deltaText = deltaBp > 0 ? '+' + deltaBp + 'bp' : deltaBp + 'bp';
    const isDeposit = state.section === 'Savings' || state.section === 'TD';
    const favorable = isDeposit ? deltaBp > 0 : deltaBp < 0;
    const tone = deltaBp === 0 ? 'flat' : favorable ? 'down' : 'up';
    return {
      text: `${pct(previous)} \u2192 ${pct(latest)} (${deltaText})`,
      tone,
    };
  }

  function appendHistoryCompare(parent, rows, state) {
    const compare = historyCompare(rows, state);
    if (!compare || !compare.text) return;
    const el = child(parent, 'span', 'local-hierarchy-history local-hierarchy-history--' + compare.tone);
    el.textContent = compare.text;
  }

  function collectRowsUnder(node) {
    if (!node || node.kind === 'empty') return [];
    if (node.kind === 'leaves') return node.rows.slice();
    return node.groups.flatMap((g) => collectRowsUnder(g.child));
  }

  function productKeysForRows(rows) {
    const keys = new Set();
    (rows || []).forEach((row) => {
      const key = rowProductKey(row);
      if (key) keys.add(key);
    });
    return keys.size ? keys : null;
  }

  function productKeysAtPath(tree, activePath) {
    const node = nodeAtPath(tree, activePath);
    if (!node) return null;
    return productKeysForRows(collectRowsUnder(node));
  }

  /** Provider → plan leaves when energy rows lack taxonomy_path. */
  function buildEnergyProviderTree(rows) {
    if (!rows.length) return { kind: 'empty', rows: [] };
    const byProvider = {};
    rows.forEach((row) => {
      const provider = row.provider || 'Unknown';
      if (!byProvider[provider]) byProvider[provider] = [];
      byProvider[provider].push(row);
    });
    const providers = Object.keys(byProvider).sort((a, b) => a.localeCompare(b));
    return {
      kind: 'branch',
      field: 'bank_name',
      groups: providers.map((label) => ({
        label,
        rows: byProvider[label],
        best: null,
        child: { kind: 'leaves', rows: byProvider[label] },
      })),
      rows: rows.slice(),
    };
  }

  function singleProviderUnder(node) {
    const rows = collectRowsUnder(node);
    if (!rows.length) return '';
    const first = rows[0].provider || '';
    for (let i = 1; i < rows.length; i += 1) {
      if ((rows[i].provider || '') !== first) return '';
    }
    return first;
  }

  /** Adapt AustralianRates ribbon tier tree to this panel's shape (groups carry rows + best rate). */
  function annotateRibbonBranch(node, highlightMax) {
    if (!node || node.kind === 'empty') return { kind: 'empty', rows: [] };
    if (node.kind === 'leaves') {
      const rows = node.products.map((p) => p.__cdrRate).filter(Boolean);
      return { kind: 'leaves', rows };
    }
    const field = node.field;
    const groups = node.groups.map((g) => {
      const child = annotateRibbonBranch(g.child, highlightMax);
      const rows = collectRowsUnder(child);
      return {
        label: g.label,
        rows,
        best: bestRate(rows, highlightMax),
        child,
      };
    });
    const rows = groups.flatMap((g) => g.rows);
    return { kind: 'branch', field, groups, rows };
  }

  function formatBranchLabel(field, label, mode) {
    if (String(field || '').startsWith('taxonomy_') && window.LocalCdrTaxonomyTree) {
      return window.LocalCdrTaxonomyTree.formatLabel(label);
    }
    if (field === 'bank_name') {
      const s = shortBank(label);
      return s || String(label || '');
    }
    const ribbon = window.AR && window.AR.ribbon;
    if (ribbon && ribbon.ribbonCompactBranchLabel) {
      return ribbon.ribbonCompactBranchLabel(field, label, mode || 'branch');
    }
    return String(label || '');
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

  function nodeAtPath(tree, activePath) {
    const parts = String(activePath || '').split('>').filter(Boolean);
    let node = tree;
    for (let i = 0; i < parts.length; i += 1) {
      if (!node || node.kind !== 'branch') return node;
      const idx = Number(parts[i]);
      if (!node.groups || !node.groups[idx]) return node;
      node = node.groups[idx].child;
    }
    return node;
  }

  function renderRateRange(parent, rows, best, highlightMax) {
    const mm = minMax(rows);
    if (mm.min == null) return;
    const showRange = mm.min !== mm.max;
    const bestValue = highlightMax ? mm.max : mm.min;
    const first = child(parent, 'span', best === bestValue ? 'ar-ribbon-best' : '', pct(mm.min));
    if (!showRange) return;
    child(parent, 'span', 'ar-ribbon-rate-sep', '-');
    const last = child(parent, 'span', best === bestValue ? 'ar-ribbon-best' : '', pct(mm.max));
    if (highlightMax) {
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
    const pathParts = String(activePath || '').split('>').filter(Boolean);
    pathParts.forEach((part, index) => {
      const groupIndex = Number(part);
      if (!node || node.kind !== 'branch' || !node.groups[groupIndex]) return;
      const group = node.groups[groupIndex];
      path = path ? path + '>' + groupIndex : String(groupIndex);
      child(bar, 'span', 'ar-report-underchart-tree-crumb-sep', '›');
      const crumbText = formatBranchLabel(node.field, group.label, 'crumb');
      const crumb = child(bar, 'button', 'ar-report-underchart-tree-crumb secondary' + (index === pathParts.length - 1 ? ' is-current' : ''), crumbText);
      crumb.type = 'button';
      crumb.title = formatBranchLabel(node.field, group.label, 'branch');
      crumb.dataset.localHierarchyAction = 'crumb';
      crumb.dataset.localHierarchyPath = path;
      node = group.child;
    });
  }

  function renderLeaf(container, row, depth, best, highlightMax, state) {
    const rateRow = child(container, 'div', 'ar-report-infobox-trow ar-report-infobox-trow--leaf ar-report-infobox-row');
    rateRow.style.setProperty('--ar-ribbon-depth', String(depth));
    rateRow.dataset.localHierarchyHover = 'leaf';
    const productKey = rowProductKey(row);
    if (productKey) rateRow.dataset.localHierarchyProductKey = productKey;
    if (row.provider) rateRow.dataset.localHierarchyProvider = row.provider;
    const dot = child(rateRow, 'span', 'ar-report-infobox-tsw');
    dot.style.setProperty('--ar-swatch-color', swatch(row));
    const label = child(rateRow, 'span', 'ar-report-infobox-tlabel local-hierarchy-leaf-label');
    const isEnergy = Boolean(row.plan_name && !row.product_name);
    const metaBits = isEnergy
      ? [row.fuel_type, row.last_updated && row.last_updated.slice(0, 10)].filter(Boolean)
      : [row.rate_type, row.application_type, row.repayment_type || row.loan_purpose].filter(Boolean);
    if (window.LocalCdrBrand && row.provider) {
      const brandSlot = child(label, 'span', 'local-hierarchy-leaf-brand');
      const badge = window.LocalCdrBrand.appendProviderBadge(brandSlot, row.provider, false, {
        logoOnly: true,
        rateRow: row,
      });
      if (state.isProviderDimmed && state.isProviderDimmed(row.provider)) {
        badge.classList.add('is-logo-dim');
      }
    }
    const textCol = child(label, 'span', 'local-hierarchy-leaf-text');
    child(textCol, 'span', 'ar-ribbon-tleaf-product', row.product_name || row.plan_name || metaBits.join(' - ') || 'Rate');
    if (row.product_name && metaBits.length) {
      child(textCol, 'span', 'local-hierarchy-leaf-meta', metaBits.join(' · '));
    }
    const rate = child(rateRow, 'span', 'ar-report-infobox-trate');
    if (isEnergy && minMax([row]).min == null) {
      if (row.fuel_type) child(rate, 'span', '', row.fuel_type);
    } else {
      renderRateRange(rate, [row], best, highlightMax);
    }
    appendHistoryCompare(rate, [row], state);
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
    row.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    const fullLabel = formatBranchLabel(node.field, group.label, 'branch');
    row.setAttribute('aria-label', (expanded ? 'Collapse ' : 'Expand ') + fullLabel);
    row.tabIndex = 0;
    if (node.field === 'bank_name') {
      row.dataset.localHierarchyProvider = String(group.label || '');
    } else {
      const singleProvider = singleProviderUnder(group.child);
      if (singleProvider) row.dataset.localHierarchyProvider = singleProvider;
    }
    child(row, 'span', 'ar-report-infobox-twist', expanded ? '▾' : '▸');
    const label = child(row, 'span', 'ar-report-infobox-tlabel');
    label.textContent = fullLabel;
    label.title = fullLabel;
    const rate = child(row, 'span', 'ar-report-infobox-trate');
    const mm = minMax(group.rows);
    if (mm.min != null) {
      renderRateRange(rate, group.rows, state.globalBest, state.highlightMax);
    } else {
      child(rate, 'span', '', num(group.rows.length));
    }
    appendHistoryCompare(rate, group.rows, state);
  }

  function renderTree(container, node, path, depth, activePath, state) {
    if (!node || node.kind === 'empty') return;
    if (node.kind === 'leaves') {
      const sorted = node.rows.slice().sort((a, b) => {
        if (state.sector === 'energy') {
          return String(a.plan_name || '').localeCompare(String(b.plan_name || ''));
        }
        return state.descending ? rateValue(b.rate) - rateValue(a.rate) : rateValue(a.rate) - rateValue(b.rate);
      });
      sorted.forEach((row) => renderLeaf(container, row, depth, state.globalBest, state.highlightMax, state));
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

  function setRibbonHierarchyLayoutActive(container, isActive) {
    if (!container || !container.classList) return;
    container.classList.toggle('has-ribbon-hierarchy', !!isActive);
    const side = container.closest('#chart-side-panel');
    if (side && side.classList) {
      side.classList.toggle('has-ribbon-hierarchy', !!isActive);
    }
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

  function emitFocus(options, tree, activePath) {
    if (!options || typeof options.onFocusChange !== 'function') return;
    const focused = nodeAtPath(tree, activePath);
    if (!focused) {
      options.onFocusChange(null);
      return;
    }
    const rows = collectRowsUnder(focused);
    if (!rows.length || !activePath) {
      options.onFocusChange(null);
      return;
    }
    const keys = new Set();
    rows.forEach((row) => {
      const k = rowProductKey(row);
      if (k) keys.add(k);
    });
    options.onFocusChange(keys);
  }

  function scrollContainer(container) {
    return container && container.querySelector('.ar-report-underchart-tree-scroll');
  }

  function restoreScrollTop(el, scrollTop) {
    if (!el || scrollTop <= 0) return;
    el.scrollTop = scrollTop;
    window.requestAnimationFrame(() => {
      if (el.isConnected) el.scrollTop = scrollTop;
    });
  }

  /** Toggle provider dim on existing rows without rebuilding the tree (hover / chart slice). */
  function applyProviderHighlight(container, state) {
    if (!container || !state || typeof state.isProviderDimmed !== 'function') return;
    container.querySelectorAll('.local-hierarchy-leaf-brand .bank-badge').forEach((badge) => {
      const row = badge.closest('[data-local-hierarchy-provider]');
      const provider = row ? row.getAttribute('data-local-hierarchy-provider') || '' : '';
      badge.classList.toggle('is-logo-dim', state.isProviderDimmed(provider));
    });
  }

  function render(container, countEl, rows, state, options) {
    const scrollEl = scrollContainer(container);
    const savedScrollTop = scrollEl ? scrollEl.scrollTop : 0;
    const visible = rows;
    const isEnergy = state.sector === 'energy';
    const providerCount = new Set(visible.map((row) => row.provider).filter(Boolean)).size;
    const productCount = isEnergy ? 0 : new Set(visible.map((row) => row.product_key || row.product_id || row.plan_id || row.product_name)).size;
    if (isEnergy) {
      countEl.textContent = `${num(visible.length)} plans / ${num(providerCount)} providers`;
    } else {
      countEl.textContent = `${num(visible.length)} rates / ${num(productCount)} products / ${num(providerCount)} providers`;
    }
    const panel = ensurePanel(container);
    if (!panel) {
      setRibbonHierarchyLayoutActive(container, false);
      return;
    }
    state.rows = visible;
    state.highlightMax = highlightMaxForSection(state.section);
    state.globalBest = isEnergy ? null : bestRate(visible, state.highlightMax);
    let tree = { kind: 'empty', rows: [] };
    const ribbon = window.AR && window.AR.ribbon;
    const hasTaxonomyPath = visible.length > 0 && visible.some((r) => r.taxonomy_path);
    if (isEnergy && hasTaxonomyPath && window.LocalCdrTaxonomyTree) {
      tree = window.LocalCdrTaxonomyTree.buildAnnotatedTree(visible, state.highlightMax);
    } else if (isEnergy) {
      tree = buildEnergyProviderTree(visible);
    } else if (!isEnergy && ribbon && ribbon.buildRibbonTierTree && window.LocalCdrRibbonMap) {
      const slug = window.LocalCdrRibbonMap.sectionSlug(state.section);
      const tierFieldsFn = ribbon.ribbonInitialTierFieldsForSection || ribbon.ribbonTierFieldsForSection;
      if (tierFieldsFn) {
        const tierFields = tierFieldsFn(slug);
        const products = window.LocalCdrRibbonMap.toRibbonProducts(visible, state.section);
        const ribbonRoot = ribbon.buildRibbonTierTree(products, tierFields, 0);
        tree = annotateRibbonBranch(ribbonRoot, state.highlightMax);
      }
    } else if (hasTaxonomyPath && window.LocalCdrTaxonomyTree) {
      tree = window.LocalCdrTaxonomyTree.buildAnnotatedTree(visible, state.highlightMax);
    }
    state.hierarchyPath = prunePath(tree, state.hierarchyPath || '');
    if (!visible.length || tree.kind === 'empty') {
      setRibbonHierarchyLayoutActive(container, false);
      panel.show({
        heading: state.section + ' hierarchy', meta: 'No rows',
        renderBody: (wrap) => child(wrap, 'div', 'chart-series-empty', 'No hierarchy data available.'),
      });
      emitFocus(options, tree, '');
      return;
    }
    setRibbonHierarchyLayoutActive(container, true);
    emitFocus(options, tree, state.hierarchyPath || '');
    const metaParts = isEnergy
      ? [`${num(visible.length)} plans`, `${num(providerCount)} providers`]
      : [`${rangeText(visible)}`, `${num(productCount)} products`, `${num(providerCount)} providers`];
    panel.show({
      heading: 'Current slice',
      meta: `${state.manifest.run_date} • ${metaParts.join(' • ')}`,
      compact: true,
      renderBody: (wrap) => {
        renderBreadcrumbs(wrap, tree, state.hierarchyPath || '');
        renderTree(wrap, tree, '', 0, state.hierarchyPath || '', state);
      },
    });
    restoreScrollTop(scrollContainer(container), savedScrollTop);
    container.__localHierarchyTree = tree;
    delete container.__localHierarchyPathKeys;
  }

  window.LocalCdrHierarchy = { render, applyProviderHighlight, productKeysAtPath, productKeysForRows };
})();
