/* Rate-honesty disclosure for the dashboard hero "best rate".
 *
 * A headline savings/TD rate can be a *conditional* bonus or introductory rate
 * rather than the ongoing rate a typical customer earns. The ribbon tree already
 * separates BASE/BONUS/INTRO branches, but the single hero figure conflates them,
 * so this supplies the caveat text for the leading rate.
 *
 * Extracted from app.js to respect the module-size ceiling (AGENTS.md).
 */
(function () {
  'use strict';

  // Prefer taxonomy_path (the ribbon tree's BASE/BONUS/INTRO branches); fall back
  // to the ribbon facets, which is what a legacy DB without taxonomy_path exposes.
  // Mortgage paths carry no BONUS/INTRO token, so mortgages are never flagged.
  function conditionalRateKind(row) {
    if (!row) return '';
    // Pad with dots so BONUS/INTRO match as whole segments even when terminal
    // (e.g. a path ending in '.BONUS').
    var path = '.' + String(row.taxonomy_path || '').toUpperCase() + '.';
    if (path.indexOf('.BONUS.') >= 0) return 'bonus';
    if (path.indexOf('.INTRO') >= 0) return 'intro';
    var dk = String(row.ribbon_deposit_kind || '').toLowerCase();
    if (dk === 'bonus') return 'bonus';
    if (dk === 'introductory' || dk === 'intro') return 'intro';
    // Legacy DBs lacking ribbon_deposit_kind can normalize the structure to
    // 'introductory'/'bonus' on ribbon_rate_structure (and strip taxonomy_path).
    var rs = String(row.ribbon_rate_structure || '').toLowerCase();
    if (rs === 'bonus') return 'bonus';
    if (rs === 'introductory' || rs === 'intro') return 'intro';
    return '';
  }

  // Caveat for the hero "best rate". Considers EVERY row tied at the leading rate
  // (the section API has no ORDER BY, so picking one row would make the disclosure
  // depend on incidental DB order):
  //  - if any tied leader is unconditional, the headline rate is achievable without
  //    conditions, so show no caveat;
  //  - otherwise every tied leader is conditional — say 'introductory' only when all
  //    of them are intro, else 'bonus'. Deterministic regardless of row order.
  function heroNote(rows, descending) {
    var EPS = 1e-9;
    var list = rows || [];
    var bestVal = null;
    list.forEach(function (row) {
      var v = Number(row.rate);
      if (!Number.isFinite(v) || v <= 0) return;
      if (bestVal == null || (descending ? v > bestVal : v < bestVal)) bestVal = v;
    });
    if (bestVal == null) return '';
    var kinds = [];
    for (var i = 0; i < list.length; i++) {
      var v = Number(list[i].rate);
      if (!Number.isFinite(v) || v <= 0) continue;
      if (Math.abs(v - bestVal) > EPS) continue;
      var kind = conditionalRateKind(list[i]);
      if (kind === '') return ''; // achievable unconditionally → no catch
      kinds.push(kind);
    }
    if (!kinds.length) return '';
    var allIntro = kinds.every(function (k) { return k === 'intro'; });
    return allIntro ? 'introductory rate — reverts' : 'bonus rate — conditions apply';
  }

  window.LocalCdrRateHonesty = {
    conditionalRateKind: conditionalRateKind,
    heroNote: heroNote,
  };
})();
