/* Rate-honesty disclosure for the dashboard hero "best rate".
 *
 * A headline savings/TD rate can be a *conditional* bonus or introductory rate
 * rather than the ongoing rate a typical customer earns. The ribbon tree already
 * separates BASE/BONUS/INTRO branches, but the single hero figure conflates them,
 * so this classifies the leader row and supplies the caveat text.
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

  // The actual best current row (min for loans, max for deposits) so the caveat
  // matches the displayed hero figure.
  function leaderRow(rows, descending) {
    var best = null;
    var bestVal = null;
    (rows || []).forEach(function (row) {
      var v = Number(row.rate);
      if (!Number.isFinite(v) || v <= 0) return;
      if (bestVal == null || (descending ? v > bestVal : v < bestVal)) {
        bestVal = v;
        best = row;
      }
    });
    return best;
  }

  // Caveat text for a conditional leader row, or '' when it is unconditional.
  function describe(row) {
    var kind = conditionalRateKind(row);
    if (kind === 'bonus') return 'bonus rate — conditions apply';
    if (kind === 'intro') return 'introductory rate — reverts';
    return '';
  }

  window.LocalCdrRateHonesty = {
    conditionalRateKind: conditionalRateKind,
    leaderRow: leaderRow,
    describe: describe,
  };
})();
