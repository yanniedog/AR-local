import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  DAILY_ISSUE_LIMIT,
  evaluateRateLimit,
  isValidKeyHex,
  keyId,
  resolveTier,
  scopesForTier,
} from './core.js';

const KEY_HEX = '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f';

test('every authenticated user is full tier until enforcement flips', () => {
  assert.equal(resolveTier({}), 'full');
  assert.equal(resolveTier({ tier: 'free' }), 'full');
  assert.equal(resolveTier(null), 'full');
});

test('scopes per tier', () => {
  assert.deepEqual(scopesForTier('full'), ['full']);
  assert.deepEqual(scopesForTier('free'), ['current']);
});

test('key id matches the Pi/app derivation', () => {
  // Interop vector from payload_crypto.py / payloadCrypto.test.ts.
  assert.equal(keyId(KEY_HEX), 'f7c55ca3');
});

test('key hex validation', () => {
  assert.equal(isValidKeyHex(KEY_HEX), true);
  assert.equal(isValidKeyHex(KEY_HEX.slice(2)), false);
  assert.equal(isValidKeyHex(KEY_HEX.toUpperCase()), false);
  assert.equal(isValidKeyHex(undefined), false);
});

test('rate limit counts within a day and blocks at the cap', () => {
  const now = Date.parse('2026-06-11T10:00:00Z');
  assert.deepEqual(evaluateRateLimit(null, now), { day: '2026-06-11', count: 1 });
  assert.deepEqual(evaluateRateLimit({ day: '2026-06-11', count: 3 }, now), {
    day: '2026-06-11',
    count: 4,
  });
  assert.equal(evaluateRateLimit({ day: '2026-06-11', count: DAILY_ISSUE_LIMIT }, now), null);
});

test('rate limit window resets on a new day', () => {
  const now = Date.parse('2026-06-12T00:01:00Z');
  assert.deepEqual(evaluateRateLimit({ day: '2026-06-11', count: DAILY_ISSUE_LIMIT }, now), {
    day: '2026-06-12',
    count: 1,
  });
});
