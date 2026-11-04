#!/usr/bin/env node
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const { isProjectionSafeMortgageRate, isProjectionSafeSavingsRate } = require('../dashboard/calculator-eligibility.js');

test('long-horizon mortgage projections reject teaser rates', () => {
  assert.equal(isProjectionSafeMortgageRate({ rate_type: 'VARIABLE' }), true);
  assert.equal(isProjectionSafeMortgageRate({ rate_type: 'INTRODUCTORY' }), false);
  assert.equal(isProjectionSafeMortgageRate({ rate_type: 'INTRO' }), false);
  assert.equal(isProjectionSafeMortgageRate({ rate_type: 'DISCOUNT' }), false);
});

test('long-horizon savings projections reject introductory rates', () => {
  assert.equal(isProjectionSafeSavingsRate({ ribbon_deposit_kind: 'base' }), true);
  assert.equal(isProjectionSafeSavingsRate({ ribbon_deposit_kind: 'bonus' }), true);
  assert.equal(isProjectionSafeSavingsRate({ ribbon_deposit_kind: 'introductory' }), false);
  assert.equal(isProjectionSafeSavingsRate({ ribbon_deposit_kind: 'intro' }), false);
});

function mortgageCandidates() {
  const context = { window: { LocalCdrUtils: {}, AR: { calculatorEligibility: require('../dashboard/calculator-eligibility.js') } } };
  const source = readFileSync(new URL('../dashboard/calculator.js', import.meta.url), 'utf8');
  assert.ok(source.includes('  init();'));
  vm.runInNewContext(source.replace('  init();', '  window.candidates = mortgageCandidates;'), context);
  return context.window.candidates;
}

test('calculator enforces open lower bounds and inclusive/exclusive endpoints', () => {
  const candidates = mortgageCandidates();
  const row = { provider: 'interval-test', rate: '0.06', rate_type: 'VARIABLE' };
  for (const [tier, value, expected] of [
    ['lvr_>=80.01%', 90, true], ['lvr_>=80.01%', 80, false],
    ['lvr_>=80.01%', 80.01, true], ['lvr_>80%', 80, false],
    ['lvr_>80%', 80.01, true], ['lvr_>=80.01-95%', 95, true],
    ['lvr_>=80.01-95%', 95.01, false], ['lvr_>=80.01-95%', 80.005, false],
    ['lvr_80-85%', 80, false], ['lvr_80-85%', 85, true],
    ['lvr_=60%', 60, true], ['lvr_=60%', 60.01, false],
    ['lvr_unspecified', 90, false], ['', 90, false],
    ['lvr_>=bad%', 90, false], ['lvr_>=95-80%', 90, false],
    ['lvr_=101%', 90, false], ['lvr_>=80%', NaN, false],
    ['lvr_>=80%', Infinity, false], ['lvr_>=80%', 101, false],
    ['lvr_=60%', 0, false],
  ]) {
    assert.equal(candidates([{ ...row, lvr_tier: tier }], { lvrPct: value }).length > 0,
      expected, `${tier} at ${value}`);
  }
});

test('calculator selects eligible retained public NAB rows without changing observations', () => {
  const rows = JSON.parse(readFileSync(new URL('../tests/fixtures/nab_lvr_app_contract_2026-10-14.json', import.meta.url))).rates;
  const original = JSON.stringify(rows);
  const candidates = mortgageCandidates();
  for (const value of [80.01, 85, 90, 95]) {
    const result = candidates(rows, { lvrPct: value });
    assert.equal(result.length, 1);
    assert.equal(result[0].row.lvr_tier, 'lvr_>=80.01-95%');
    assert.ok(rows.includes(result[0].row));
  }
  assert.equal(candidates(rows, { lvrPct: 80.005 }).length, 0);
  assert.equal(candidates(rows, { lvrPct: 95.01 }).length, 0);
  assert.equal(JSON.stringify(rows), original);
});
