// Fetch-policy controls only: these markers are not financial acceptance data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function dashboard(fetch) {
  const source = fs.readFileSync(path.join(__dirname, '../../dashboard/app.js'), 'utf8');
  const startup = '  init().catch((error) => {';
  assert.equal(source.split(startup).length, 2);
  // Run the whole production closure, exposing its real functions before DOM
  // startup. Production has no test hook or altered fetch implementation.
  const context = vm.createContext({ window: { LocalCdrUtils: {} }, fetch, console });
  vm.runInContext(source.replace(startup,
    '  globalThis.dashboard = { getJson, state, loadCompactHistory }; return;\n' + startup), context);
  return context.dashboard;
}

test('all mutable dashboard API families bypass HTTP cache and retain request options', async () => {
  const requests = [];
  const app = dashboard(async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ marker: 'current' }) };
  });
  const urls = ['/api/latest', '/api/ingest-schedule',
    '/api/banks/section?date=2026-09-13&section=TD',
    '/api/banks/ribbon?date=2026-09-13&section=TD',
    '/api/banks/history/section?date=2026-09-13&section=TD',
    '/api/banks/history/section/compact?date=2026-09-13&section=TD'];
  const options = { signal: new AbortController().signal, headers: { Accept: 'application/json' } };
  for (const url of urls) assert.equal((await app.getJson(url, options)).marker, 'current');
  assert.equal(requests.length, urls.length);
  for (const request of requests) {
    assert.equal(request.options.cache, 'no-store');
    assert.equal(request.options.signal, options.signal);
    assert.equal(request.options.headers, options.headers);
  }
  assert.equal(options.cache, undefined, 'caller options remain unmodified');
});

test('ordinary reload cannot replay an earlier response at the same dated URL', async () => {
  // Model the browser HTTP cache contract, including a still-fresh response:
  // force-cache/default may reuse it; no-store fetches the current origin body.
  // https://developer.mozilla.org/en-US/docs/Web/API/Request/cache
  const url = '/api/banks/section?date=2026-09-13&section=TD';
  const cache = new Map([[url, { marker: 'previous-observation' }]]);
  let networkReads = 0;
  const fetch = async (requestUrl, options) => {
    const usesCache = !['no-store', 'no-cache', 'reload'].includes(options.cache);
    const body = usesCache && cache.has(requestUrl)
      ? cache.get(requestUrl) : (networkReads++, { marker: 'selected-observation' });
    return { ok: true, json: async () => body };
  };
  assert.equal((await dashboard(fetch).getJson(url)).marker, 'selected-observation');
  assert.equal((await dashboard(fetch).getJson(url)).marker, 'selected-observation');
  assert.equal(networkReads, 2);
});

test('failed mutable API requests stay visible instead of returning retained data', async () => {
  const app = dashboard(async () => ({ ok: false, status: 503,
    json: async () => { throw new Error('must not parse an error as cached data'); } }));
  await assert.rejects(app.getJson('/api/latest'), /\/api\/latest returned 503/);
  const offline = dashboard(async () => { throw new Error('network unavailable'); });
  await assert.rejects(offline.getJson('/api/latest'), /network unavailable/);
});

test('compact history still uses its in-memory section and toggle caches', async () => {
  const requests = [];
  const app = dashboard(async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ run_dates: [], points: [], providers: [] }) };
  });
  app.state.manifest = { run_date: '2026-09-13' };
  await app.loadCompactHistory('TD', false);
  await app.loadCompactHistory('TD', false);
  await app.loadCompactHistory('TD', true);
  await app.loadCompactHistory('TD', true);
  await app.loadCompactHistory('TD', false);
  assert.equal(requests.length, 2, 'one fetch per toggle variant, not one per navigation');
  assert.equal(requests[0].options.cache, 'no-store');
  assert.match(requests[1].url, /include_non_standard=1$/);
});
