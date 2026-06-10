#!/usr/bin/env node
import assert from 'node:assert/strict';
import {
  buildRecentIntervalFilter,
  flattenMessageQueryParams,
} from './crashlytics-client.mjs';

const filter = buildRecentIntervalFilter(7);
const flat = flattenMessageQueryParams('filter', filter);

assert.equal(flat['filter.issue.state'], 'OPEN');
assert.match(flat['filter.interval.startTime'], /^\d{4}-\d{2}-\d{2}T/);
assert.match(flat['filter.interval.endTime'], /^\d{4}-\d{2}-\d{2}T/);
assert.equal(flat.filter, undefined, 'must not emit a JSON blob filter key');

const nested = flattenMessageQueryParams('filter', {
  issue: { errorTypes: ['FATAL', 'ANR'] },
});
assert.deepEqual(nested['filter.issue.errorTypes'], ['FATAL', 'ANR']);

console.log('crashlytics-client.test.mjs: ok');
