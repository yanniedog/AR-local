#!/usr/bin/env node
import assert from 'node:assert/strict';
import test from 'node:test';

import { waitForQueueDrain, ensureApkForMainHead } from './mobile-auto-release-on-drain.mjs';

test('waitForQueueDrain refreshes main after a queued PR closes', async () => {
  const openCounts = [1, 0];
  let syncCount = 0;

  const remaining = await waitForQueueDrain({
    countOpen: () => openCounts.shift() ?? 0,
    sleep: async () => {},
    syncAfterDrain: () => {
      syncCount += 1;
    },
  });

  assert.equal(remaining, 0);
  assert.equal(syncCount, 1);
});

test('waitForQueueDrain skips without refreshing when multiple PRs remain', async () => {
  let syncCount = 0;

  const remaining = await waitForQueueDrain({
    countOpen: () => 2,
    sleep: async () => {},
    syncAfterDrain: () => {
      syncCount += 1;
    },
  });

  assert.equal(remaining, 2);
  assert.equal(syncCount, 0);
});

test('ensureApkForMainHead dispatches when the version has no published APK', () => {
  const dispatched = [];
  const did = ensureApkForMainHead({
    readVersion: () => '1.0.40',
    releaseExists: () => false,
    buildInFlight: () => false,
    dispatch: (v) => dispatched.push(v),
  });
  assert.equal(did, true);
  assert.deepEqual(dispatched, ['1.0.40']);
});

test('ensureApkForMainHead is a no-op when the APK is already published', () => {
  let dispatchedCount = 0;
  const did = ensureApkForMainHead({
    readVersion: () => '1.0.29',
    releaseExists: (v) => v === '1.0.29',
    buildInFlight: () => false,
    dispatch: () => {
      dispatchedCount += 1;
    },
  });
  assert.equal(did, false);
  assert.equal(dispatchedCount, 0);
});

test('ensureApkForMainHead skips dispatch when a build is already in flight', () => {
  let dispatchedCount = 0;
  const did = ensureApkForMainHead({
    readVersion: () => '1.0.41',
    releaseExists: () => false,
    buildInFlight: () => true,
    dispatch: () => {
      dispatchedCount += 1;
    },
  });
  assert.equal(did, false);
  assert.equal(dispatchedCount, 0);
});
