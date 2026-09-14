// UI/count mechanisms only; these markers are not bank/product acceptance data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const coverage = require('../../dashboard/history-coverage.js');

function metadata(extra = {}) {
  return { schema_version: 1, available_run_file_count: 91, selected_run_file_count: 90,
    omitted_run_file_count: 1, run_file_limit: 90, truncated: true,
    unreadable_selected_run_file_count: 0, empty_selected_run_file_count: 0,
    missing_run_file_count: 0, inventory_error_count: 0, observed_date_count: 2, ...extra };
}

function model(extra = {}) {
  return { kind: 'bank-history', dates: ['2001-01-02'], allDates: ['2001-01-01', '2001-01-02'],
    historyCoverage: metadata(), points: [{ date: '2001-01-02', count: 2,
      observed_count: 1, carry_forward_count: 1 }], ...extra };
}

function dashboard() {
  const source = fs.readFileSync(path.join(__dirname, '../../dashboard/app.js'), 'utf8');
  const startup = '  init().catch((error) => {';
  assert.equal(source.split(startup).length, 2);
  const status = { textContent: '' };
  const button = { dataset: { historyWindow: 'All' }, classList: { toggle() {} }, setAttribute() {} };
  const context = vm.createContext({ window: { LocalCdrUtils: {}, LocalCdrHistoryCoverage: coverage },
    document: { getElementById: () => status, querySelectorAll: () => [button] }, console });
  vm.runInContext(source.replace(startup, '  globalThis.app = { state, setBankHistoryCompact, '
    + 'compactChartItems, buildAggregateRibbon, setHistoryWindowUi, ribbonChartItems }; return;\n' + startup), context);
  context.app.state.historyWindow = 'All';
  return { app: context.app, status };
}

test('loaded dates and the run-file cap are disclosed without retained-completeness claims', () => {
  const status = coverage.status(model());
  assert.match(status, /1 dates in range, 2 loaded/);
  assert.match(status, /90 of 91 available run files selected/);
  assert.match(status, /90-run-file cap; 1 older files omitted/);
  assert.match(status, /Full historical coverage not verified/);
  assert.match(status, /1 observed rate contributions; 1 carried-forward estimates/);
  assert.doesNotMatch(status, /retained/);
});

test('unreadable, empty and missing files remain separate from observed dates', () => {
  const status = coverage.status(model({ historyCoverage: metadata({
    unreadable_selected_run_file_count: 2, empty_selected_run_file_count: 3,
    missing_run_file_count: 4, inventory_error_count: 1 }) }));
  assert.match(status, /2 selected files unreadable/);
  assert.match(status, /3 selected files returned no matching rows/);
  assert.match(status, /4 expected run files missing/);
  assert.match(status, /inventory incomplete/);
});

test('fixed-root counts do not equate one file with one observed date; zero is retained', () => {
  const fixed = metadata({ available_run_file_count: 1, selected_run_file_count: 1,
    omitted_run_file_count: 0, truncated: false });
  assert.match(coverage.status(model({ historyCoverage: fixed })), /1 of 1 available run files/);
  const empty = model({ dates: [], allDates: [], points: [], historyCoverage: metadata({
    available_run_file_count: 0, selected_run_file_count: 0, omitted_run_file_count: 0,
    observed_date_count: 0, truncated: false }) });
  assert.match(coverage.status(empty), /0 dates in range, 0 loaded/);
  assert.match(coverage.status(empty), /0 of 0 available run files/);
  assert.match(coverage.status(empty), /0 observed rate contributions; 0 carried-forward/);
});

test('legacy and current-only payloads explicitly withhold coverage and provenance', () => {
  const legacy = model({ historyCoverage: null, points: [{ date: '2001-01-02', count: 2 }] });
  assert.match(coverage.status(legacy), /Run-file coverage unavailable/);
  assert.match(coverage.status(legacy), /Observed\/carried-forward split unavailable/);
  const current = coverage.status({ ...legacy, currentOnly: true });
  assert.match(current, /Current snapshot only; history not loaded/);
  assert.doesNotMatch(current, /available run files selected/);
});

test('coverage and contribution counts require literal coherent nonnegative integers', () => {
  for (const bad of ['0', null, false, NaN, Infinity, -1, 0.5]) {
    assert.equal(coverage.validCoverage(metadata({ missing_run_file_count: bad })), null);
    assert.equal(coverage.contributions(model({ points: [{ date: '2001-01-02', count: 2,
      observed_count: bad, carry_forward_count: 1 }] })), null);
  }
  assert.equal(coverage.validCoverage(metadata({ omitted_run_file_count: 0 })), null);
  assert.equal(coverage.validCoverage(metadata({ selected_run_file_count: 91 })), null);
  assert.equal(coverage.validCoverage(metadata({ unreadable_selected_run_file_count: 90,
    empty_selected_run_file_count: 1 })), null);
});

test('provenance counts track only visible dates and the displayed focused provider', () => {
  const items = model({ focusProvider: '  Protocol\u00a0bank ', providers: [{ label: 'protocol bank',
    byDate: { '2001-01-01': { count: 9, observed_count: 0, carry_forward_count: 9 },
      '2001-01-02': { count: 1, observed_count: 0, carry_forward_count: 1 } } }] });
  assert.deepEqual(coverage.contributions(items), { observed: 0, carried: 1 });
  assert.deepEqual(coverage.contributions({ ...items, focusProvider: 'absent' }), { observed: 1, carried: 1 });
});

test('actual app compact path retains coverage and renders the new status text', () => {
  const { app, status } = dashboard();
  const meta = metadata();
  app.setBankHistoryCompact('Mortgage', false, { run_dates: ['2001-01-01', '2001-01-02'],
    history_coverage: meta, points: model().points, providers: [] });
  const items = app.compactChartItems([]);
  assert.equal(items.historyCoverage, meta);
  app.setHistoryWindowUi(items);
  assert.match(status.textContent, /90-run-file cap/);
  assert.match(status.textContent, /2 loaded/);
  const current = app.ribbonChartItems({ run_date: '2001-01-02', counts: { rates: 1 } });
  app.setHistoryWindowUi(current);
  assert.match(status.textContent, /Current snapshot only; history not loaded/);
});

test('actual drilldown kernel counts carry string 1 only after numeric acceptance', () => {
  const { app } = dashboard();
  const rows = ['1', '0', 1, true, null].map((flag) => ({ run_date: '2001-01-02',
    provider: 'protocol-only', rate: 0.01, carry_forward: flag }));
  rows.push({ run_date: '2001-01-02', rate: 'bad', carry_forward: '1' });
  rows.push({ run_date: 'not-a-date', rate: 0.01, carry_forward: '1' });
  const result = app.buildAggregateRibbon(rows);
  assert.equal(result.points[0].count, 5);
  assert.equal(result.points[0].carry_forward_count, 1);
  assert.equal(result.points[0].observed_count, 4);
  assert.equal(result.providers[0].byDate['2001-01-02'].carry_forward_count, 1);
  assert.equal(result.points[0].mean, 0.01);
});
