#!/usr/bin/env node
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

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
