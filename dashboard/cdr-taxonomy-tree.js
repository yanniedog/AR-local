(function () {
  'use strict';

  /**
   * Builds a collapsible tree from rows that carry a dot-separated
   * taxonomy_path column, e.g. "HOME_LOAN.OO.PI.FIXED.24M.LVR_70_80".
   *
   * The produced tree shape is identical to the annotated ribbon branch
   * used by hierarchy.js, so renderTree() works unchanged on both.
   *
   *   { kind: 'branch', field: 'taxonomy_L1', groups: [
   *       { label: 'HOME_LOAN', rows: [...], best: <number|null>, child: … }
   *     ], rows: [...] }
   *
   *   { kind: 'leaves', rows: [...] }
   *
   * Branch field names begin with "taxonomy_" so formatBranchLabel() in
   * hierarchy.js can route them here for human-readable labels.
   */

  // ── Label map ──────────────────────────────────────────────────────────────

  var LABEL = {
    // Product classes
    HOME_LOAN: 'Home Loans', BUSINESS_LOAN: 'Business Loans',
    PERSONAL_LOAN: 'Personal Loans', CREDIT_CARD: 'Credit Cards',
    SAVINGS: 'Savings Accounts', TERM_DEPOSIT: 'Term Deposits',
    OVERDRAFT: 'Overdrafts',
    // Security purpose
    OO: 'Owner-occupied', INV: 'Investment',
    // Repayment type
    PI: 'Principal & interest', IO: 'Interest only',
    // Rate types (banking)
    VARIABLE: 'Variable', FIXED: 'Fixed', INTRO: 'Introductory',
    DISCOUNT: 'Discount', BUNDLE: 'Bundle', FLOATING: 'Floating',
    PURCHASE: 'Purchase', CASH_ADVANCE: 'Cash advance',
    BAL_TRANSFER: 'Balance transfer', INTEREST_FREE: 'Interest free',
    // LVR tiers
    LVR_UNSP: 'LVR unspecified (no tier resolved)', LVR_LE60: 'LVR <= 60%',
    LVR_60_70: 'LVR 60-70%', LVR_70_80: 'LVR 70-80%',
    LVR_80_85: 'LVR 80-85%', LVR_85_90: 'LVR 85-90%',
    LVR_90_95: 'LVR 90-95%',
    // Savings account types
    SAVINGS_ACCT: 'Savings account', TRANSACTION: 'Transaction account',
    AT_CALL: 'At call',
    // Deposit rate kinds
    BASE: 'Base rate', BONUS: 'Bonus', TOTAL: 'Total rate',
    // Balance tiers
    FLAT: 'Flat', TIERED: 'Tiered by balance',
    // Interest payment
    AT_MATURITY: 'At maturity', MONTHLY: 'Monthly',
    QUARTERLY: 'Quarterly', ANNUALLY: 'Annually',
    // Energy fuel
    ELECTRICITY: 'Electricity', GAS: 'Gas', DUAL: 'Dual fuel',
    // Customer type
    RESIDENTIAL: 'Residential', BUSINESS: 'Business',
    // Offer type
    STANDING: 'Standing offer', MARKET: 'Market offer',
    // Energy pricing models
    FLAT_CL: 'Single rate + controlled load',
    TOU: 'Time of use', TOU_CL: 'Time of use + controlled load',
    DEMAND: 'Demand / flexible', DEMAND_CL: 'Demand + controlled load',
    CL_ONLY: 'Controlled load only', WHOLESALE: 'Wholesale',
    // Solar
    SOLAR: 'Solar export (FiT)', NO_SOLAR: 'No solar export',
    // Fallbacks
    OTHER_TERM: 'Other term', OTHER: 'Other', UNKNOWN: 'Unknown',
  };

  function formatLabel(token) {
    if (!token) return '';
    // Term-month tokens: "12M", "24M", ...
    var termMatch = String(token).match(/^(\d+)M$/);
    if (termMatch) return termMatch[1] + ' month' + (Number(termMatch[1]) === 1 ? '' : 's');
    return LABEL[token] || String(token);
  }

  // ── Tree builder ───────────────────────────────────────────────────────────

  function rateValue(rate) {
    var n = Number(rate);
    return Number.isFinite(n) ? n : 0;
  }

  function bestRate(rows, descending) {
    var best = null;
    for (var i = 0; i < rows.length; i += 1) {
      var v = rateValue(rows[i].rate);
      if (v <= 0) continue;
      if (best === null || (descending ? v > best : v < best)) best = v;
    }
    return best;
  }

  function buildLevel(rows, depth) {
    if (!rows.length) return { kind: 'empty', rows: [] };

    // Collect distinct tokens at this depth; order of first appearance preserved.
    var tokenOrder = [];
    var tokenRows = {};
    for (var i = 0; i < rows.length; i += 1) {
      var parts = String(rows[i].taxonomy_path || '').split('.');
      var token = depth < parts.length ? parts[depth] : '';
      if (!Object.prototype.hasOwnProperty.call(tokenRows, token)) {
        tokenOrder.push(token);
        tokenRows[token] = [];
      }
      tokenRows[token].push(rows[i]);
    }

    // If every row has the same depth (or we are past the deepest level), leaf.
    var allAtLeaf = rows.every(function (r) {
      return String(r.taxonomy_path || '').split('.').length <= depth + 1;
    });
    if (allAtLeaf) return { kind: 'leaves', rows: rows.slice() };

    return {
      kind: 'branch',
      field: 'taxonomy_L' + (depth + 1),
      groups: tokenOrder.map(function (token) {
        return { token: token, rows: tokenRows[token] };
      }),
      rows: rows,
    };
  }

  function annotate(node, descending) {
    if (!node || node.kind === 'empty') return { kind: 'empty', rows: [] };
    if (node.kind === 'leaves') return node;
    var groups = node.groups.map(function (g) {
      var child = annotate(buildLevel(g.rows, depthOf(node.field)), descending);
      return {
        label: g.token,
        rows: g.rows,
        best: bestRate(g.rows, descending),
        child: child,
      };
    });
    return { kind: 'branch', field: node.field, groups: groups, rows: node.rows };
  }

  function depthOf(field) {
    // "taxonomy_L1" → depth 1 (children split at depth 1)
    var m = String(field || '').match(/taxonomy_L(\d+)/);
    return m ? Number(m[1]) : 0;
  }

  function buildAnnotatedTree(rows, descending) {
    var root = buildLevel(rows, 0);
    return annotate(root, descending);
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  window.LocalCdrTaxonomyTree = {
    buildAnnotatedTree: buildAnnotatedTree,
    formatLabel: formatLabel,
  };
})();
