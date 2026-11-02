import test from 'node:test';
import { readFileSync } from 'node:fs';
import { gzipSync, gunzipSync } from 'node:zlib';
import assert from 'node:assert/strict';
import { MAX_BYTES, PAYLOAD, decodeRelease, handleRequest, releaseRoute } from './worker.mjs';

const keyBytes = new Uint8Array(32).fill(31);
const hex = b => Buffer.from(b).toString('hex');
const id = hex(await crypto.subtle.digest('SHA-256', Buffer.concat([Buffer.from('ar-local-payload-key:'), keyBytes]))).slice(0, 32);
const secret = JSON.stringify({ [id]: hex(keyBytes) });
const key = await crypto.subtle.importKey('raw', keyBytes, 'AES-GCM', false, ['encrypt']);
const content = Buffer.from('verified domain bytes');
async function envelope(plain = content, legacy = false) {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const head = legacy ? Buffer.from('ARE1') : Buffer.alloc(44);
  if (!legacy) { head.write('ARE2'); head.write(id, 4); head.writeUInt32BE(plain.length, 40); }
  const body = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce, additionalData: head }, key, plain);
  return new Uint8Array(Buffer.concat([head, nonce, Buffer.from(body)]));
}
const wire = await envelope();
const url = 'https://service.example/v1/release/app-payload-2026-09-19-r000003/core-2026-09-19-123456789abc.json.gz';
const env = { RELEASE_KEYS: secret, RATE_LIMITER: { limit: async () => ({ success: true }) } };
const context = { waitUntil: promise => promise };
const request = (target = url, method = 'GET') => new Request(target, { method });
const fetcher = async () => new Response(wire);

test('asset allowlist matches the producer encryption classification contract', () => {
  const source = readFileSync(new URL('../../app_payload_secure_upload.py', import.meta.url), 'utf8');
  const block = source.split('ASSET = re.compile(')[1].split(/\r?\n\)/)[0];
  const pattern = [...block.matchAll(/r"([^"]*)"/g)].map(match => match[1]).join('');
  assert.ok(pattern.length > 100);
  assert.equal(PAYLOAD.source, new RegExp(`^${pattern}$`).source);
});

test('mutable aliases bypass stale upstream redirects while revisions remain stable', async () => {
  const seen = [];
  const origin = async target => { seen.push(new URL(target)); return new Response(wire); };
  for (const tag of ['app-payload-latest', 'app-payload-2026-09-19', 'app-payload-2026-09-19-r000003']) {
    assert.equal((await handleRequest(request(url.replace('app-payload-2026-09-19-r000003', tag)), env, context, origin, null)).status, 200);
  }
  assert.match(seen[0].searchParams.get('_'), /^\d+$/);
  assert.match(seen[1].searchParams.get('_'), /^\d+$/);
  assert.equal(seen[2].search, '');
});

test('legacy decode has distinct cache identities and downstream Vary in both directions', async () => {
  const legacy = await envelope(content, true);
  const wrapped = await envelope(legacy);
  const digest = hex(await crypto.subtle.digest('SHA-256', legacy));
  const entries = new Map();
  let calls = 0;
  const cache = { match: async key => entries.get(key)?.clone(), put: async (key, value) => { entries.set(key, value); } };
  const origin = async () => { calls++; return new Response(wrapped); };
  for (const decode of [false, true, false, true]) {
    const req = new Request(url, { headers: decode ? { 'X-AR-Legacy-SHA256': digest } : {} });
    const response = await handleRequest(req, env, context, origin, cache);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('vary'), 'X-AR-Legacy-SHA256');
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), decode ? content : Buffer.from(legacy));
  }
  assert.equal(calls, 2);
  assert.equal(entries.size, 2);
  for (const key of entries.keys()) assert.equal(new URL(key).searchParams.get('__delivery'), '2');
});

test('authenticates source and emits exact domain bytes without key material', async () => {
  const response = await handleRequest(request(), env, context, fetcher, null);
  assert.equal(response.status, 200);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), content);
  assert.equal(response.headers.get('content-encoding'), null);
  assert.equal(response.headers.get('access-control-allow-origin'), '*');
  assert.equal(JSON.stringify([...response.headers]).includes(hex(keyBytes)), false);
});
test('current and historical aliases are accepted; cache-busting is normalized', () => {
  for (const tag of ['app-payload-latest', 'app-payload-2026-09-18', 'app-payload-2026-09-18-r000002']) {
    const value = releaseRoute(request(`https://service.example/v1/release/${tag}/manifest.json?_=123`));
    assert.equal(value.canonical.includes('?'), false);
    assert.equal(value.upstream, `https://github.com/yanniedog/AR-local/releases/download/${tag}/manifest.json`);
  }
});
test('historical encrypted suffix and every approved producer payload family route', () => {
  for (const stem of ['core', 'details', 'bank-history', 'bank-rate-history-catalogue', 'bank-rate-history-catalogue-packed', 'bank-rate-history-ready', 'bank-spread-history', 'history-banks',
    'rba-calendar', 'search-index', 'v2-economic-outlook', 'v2-product-history', 'terms-index', 'terms_shard_001', 'executable-index', 'executable_shard_001', 'executable_v2_index', 'executable_v2_shard_000', 'monetary_v3_mortgage_index', 'monetary_v4_savings_activity_shard_000']) {
    for (const suffix of ['.json.gz', '.json.gz.enc']) {
      assert.equal(releaseRoute(request(url.replace('core-2026-09-19-123456789abc.json.gz', `${stem}-2026-09-19-123456789abc${suffix}`))).asset,
        `${stem}-2026-09-19-123456789abc${suffix}`);
    }
  }
});
for (const family of ['bank-rate-history-catalogue', 'bank-rate-history-catalogue-packed', 'bank-rate-history-ready']) test(`${family} route authenticates and preserves exact envelope bytes`, async () => {
  const target = url.replace('core-2026-09-19-123456789abc.json.gz',
    `${family}-2026-09-19-123456789abc.json.gz`);
  const response = await handleRequest(request(target), env, context, fetcher, null);
  assert.equal(response.status, 200);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), content);
  assert.equal((await handleRequest(request(target), env, context,
    async () => new Response(content), null)).status, 502);
});

for (const family of ['bank-rate-history-catalogue-packed', 'bank-rate-history-ready']) for (const legacy of [false, true]) test(`${family} gzip receipt survives encrypted service delivery (legacy=${legacy})`, async () => {
  const fixture = JSON.parse(readFileSync(new URL('../../tests/fixtures/history-dag-v1-interoperability.json', import.meta.url), 'utf8'));
  const innerValue = family === 'bank-rate-history-ready' ? JSON.parse(readFileSync(new URL('../../tests/fixtures/history-ready-real.json', import.meta.url), 'utf8')) : fixture.packed;
  const inner = Buffer.from(JSON.stringify(innerValue));
  const receipt = { schema_version: 1, run_date: '2026-09-19', core_sha256: '1'.repeat(64), catalogue: {
    sha256: hex(await crypto.subtle.digest('SHA-256', inner)), bytes: inner.length,
    gzip_base64: gzipSync(inner).toString('base64'),
  } };
  const compressed = gzipSync(Buffer.from(JSON.stringify(receipt)));
  // New uploads use ARE2 directly. ARE1 coverage verifies the existing frozen
  // migration path, which must preserve its ciphertext digest before decoding.
  const domain = legacy ? Buffer.from(await envelope(compressed, true)) : compressed;
  const sourceHash = hex(await crypto.subtle.digest('SHA-256', domain));
  const target = url.replace('core-2026-09-19-123456789abc.json.gz',
    `${family}-2026-09-19-${sourceHash.slice(0, 12)}.json.gz${legacy ? '.enc' : ''}`);
  const source = await envelope(domain);
  const origin = async () => new Response(source);
  const response = await handleRequest(request(target), env, context, origin, null);
  assert.equal(response.status, 200);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), domain);
  assert.equal(response.headers.get('etag'), `"${sourceHash}"`);
  const delivered = legacy ? await handleRequest(new Request(target, { headers: { 'X-AR-Legacy-SHA256': sourceHash } }), env, context, origin, null)
    : await handleRequest(request(target), env, context, origin, null);
  assert.equal(delivered.status, 200);
  const verified = JSON.parse(gunzipSync(Buffer.from(await delivered.arrayBuffer())));
  assert.deepEqual(verified, receipt);
  const unpackedBytes = gunzipSync(Buffer.from(verified.catalogue.gzip_base64, 'base64'));
  assert.equal(unpackedBytes.length, verified.catalogue.bytes);
  assert.equal(hex(await crypto.subtle.digest('SHA-256', unpackedBytes)), verified.catalogue.sha256);
  assert.deepEqual(JSON.parse(unpackedBytes), innerValue);
  const tampered = source.slice(); tampered[tampered.length - 1] ^= 1;
  assert.equal((await handleRequest(request(target), env, context, async () => new Response(tampered), null)).status, 502);
  if (legacy) assert.equal((await handleRequest(new Request(target, { headers: { 'X-AR-Legacy-SHA256': '0'.repeat(64) } }), env, context, origin, null)).status, 502);
});
for (const path of ['/v1/release/app-payload-latest/../key.json', '/v1/release/other/key.json',
  '/v1/release/app-payload-latest/source.zip', '/v1/release/app-payload-latest/a%2Fb.json',
  '/v1/release/app-payload-latest/..secret.json', '/v1/release/app-payload-latest/a.json?url=http://localhost',
  '/v1/release/app-payload-latest/a.json?legacy_sha256=no',
  '/v1/release/app-payload-latest/key.json', '/v1/release/app-payload-latest/preservation.json',
  '/v1/release/app-payload-latest/publication-provenance.json', '/v1/release/app-payload-latest/core-secret.json.gz',
  ...['core.json.gz', 'core-2026-09-19.json.gz', 'core-2026-09-19-12345678.json.gz',
    `core-2026-09-19-${'a'.repeat(64)}.json.gz`].map(name => `/v1/release/app-payload-latest/${name}`)]) {
  test(`rejects unsafe request ${path}`, async () => {
    let calls = 0;
    assert.equal((await handleRequest(request('https://service.example' + path), env, context, async () => { calls++; }, null)).status, 400);
    assert.equal(calls, 0);
  });
}
test('method and preflight handling do not fetch data', async () => {
  assert.equal((await handleRequest(request(url, 'POST'), env, context, fetcher, null)).status, 405);
  assert.equal((await handleRequest(request(url, 'OPTIONS'), env, context, fetcher, null)).status, 204);
});
test('rate limiting is mandatory and fails closed', async () => {
  assert.equal((await handleRequest(request(), { RELEASE_KEYS: secret }, context, fetcher, null)).status, 429);
  assert.equal((await handleRequest(request(), { ...env, RATE_LIMITER: { limit: async () => ({ success: false }) } }, context, fetcher, null)).status, 429);
});
test('missing, wrong, malformed and unknown keys never fall back to plaintext', async () => {
  for (const value of [undefined, '{}', 'bad', JSON.stringify({ [id]: 'ff'.repeat(32) })]) {
    const response = await handleRequest(request(), { ...env, RELEASE_KEYS: value }, context, fetcher, null);
    assert.equal(response.status, 502);
    assert.equal(await response.text(), 'Data service temporarily unavailable.');
  }
});
test('rejects tampering, plaintext and oversized declared sizes', async () => {
  const tampered = wire.slice(); tampered[tampered.length - 1] ^= 1;
  const oversized = wire.slice(); new DataView(oversized.buffer).setUint32(40, MAX_BYTES + 1);
  for (const input of [tampered, content, oversized]) await assert.rejects(decodeRelease(input, secret));
});
test('rejects nested ARE2 and verifies frozen ARE1 hash before server decode', async () => {
  await assert.rejects(decodeRelease(await envelope(wire), secret));
  const legacy = await envelope(content, true);
  const wrapped = await envelope(legacy);
  assert.deepEqual(Buffer.from(await decodeRelease(wrapped, secret)), Buffer.from(legacy));
  const digest = hex(await crypto.subtle.digest('SHA-256', legacy));
  assert.deepEqual(Buffer.from(await decodeRelease(wrapped, secret, digest)), content);
  await assert.rejects(decodeRelease(wrapped, secret, '0'.repeat(64)));
});
test('unsafe redirects and redirect loops fail before following unsafe hosts', async () => {
  let calls = 0;
  const response = await handleRequest(request(), env, context, async () => {
    calls++; return new Response(null, { status: 302, headers: { location: 'http://127.0.0.1/private' } });
  }, null);
  assert.equal(response.status, 502); assert.equal(calls, 1);
  calls = 0;
  const loop = await handleRequest(request(), env, context, async () => {
    calls++; return new Response(null, { status: 302, headers: { location: 'https://release-assets.githubusercontent.com/again' } });
  }, null);
  assert.equal(loop.status, 502); assert.equal(calls, 3);
});
test('bounded stream rejects missing or dishonest length before decrypting', async () => {
  for (const declared of [false, true]) {
    const body = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(MAX_BYTES + 73)); controller.close(); } });
    const response = await handleRequest(request(), env, context, async () => new Response(body,
      { headers: declared ? { 'content-length': String(MAX_BYTES + 73) } : {} }), null);
    assert.equal(response.status, 502);
  }
});
test('only successful authenticated responses enter cache with correct lifetime', async () => {
  const saved = [];
  const cache = { match: async () => null, put: async (key, value) => { saved.push([key, value]); } };
  await handleRequest(request(), env, context, fetcher, cache);
  assert.match(saved[0][1].headers.get('cache-control'), /immutable/);
  await handleRequest(request(url.replace('-2026-09-19-r000003', '-latest')), env, context, fetcher, cache);
  assert.equal(saved[1][1].headers.get('cache-control'), 'public, max-age=30');
  await handleRequest(request(), env, context, async () => new Response(content), cache);
  assert.equal(saved.length, 2);
});
test('successful cache bypasses origin but still requires rate limit', async () => {
  const response = await handleRequest(request(), env, context, () => { throw new Error('must not fetch'); },
    { match: async () => new Response(content) });
  assert.equal(response.status, 200);
});

// Transport controls only: these bytes are not an observed-population data fixture.
const observedPrefix = 'https://service.example/v1/capabilities/observed-population-v1/release/';
const observedTag = 'app-payload-observed-v1-2026-11-02-r000001';
const observedIndex = `${observedPrefix}app-payload-observed-v1-candidate/dates-index.json`;
const observedManifest = `${observedPrefix}${observedTag}/manifest.json`;

test('explicit capability admits only its index and immutable approved assets', () => {
  assert.equal(releaseRoute(request(observedIndex)).tag, 'app-payload-observed-v1-candidate');
  for (const asset of ['manifest.json', 'manifest-v2.json', 'dates-index.json', 'revision-delta.json',
    'base-manifest.json', 'source-manifest.json', 'core-2026-11-02-123456789abc.json.gz',
    'details-2026-11-02-123456789abc.json.gz.enc', 'bank-history-2026-11-02-123456789abc.json.gz']) {
    const target = `${observedPrefix}${observedTag}/${asset}`;
    const route = releaseRoute(request(target));
    assert.equal(route.canonical, target);
    assert.equal(route.legacySha, null);
    assert.equal(route.upstream, `https://github.com/yanniedog/AR-local/releases/download/${observedTag}/${asset}`);
  }
  assert.equal(releaseRoute(request(observedManifest.replace('2026-11-02-r000001', '2024-02-29-r999999'))).tag,
    'app-payload-observed-v1-2024-02-29-r999999');
  // Fetch's Request rejects credentials itself; verify the parser independently too.
  assert.throws(() => releaseRoute({ url: observedManifest.replace('service.example', 'user:password@service.example'),
    headers: new Headers() }), /Invalid capability route/);
});

const invalidObserved = [
  `${observedPrefix}app-payload-observed-v1-candidate/manifest.json`,
  `${observedPrefix}app-payload-observed-v1-candidate/core-2026-11-02-123456789abc.json.gz`,
  `${observedPrefix}app-payload-latest/manifest.json`,
  `${observedPrefix}app-payload-2026-11-02-r000001/manifest.json`,
  observedManifest.replace('observed-population-v1', 'observed-population-v2'),
  observedManifest.replace('observed-population-v1', 'unknown'),
  observedManifest.replace('/capabilities/observed-population-v1', ''),
  observedIndex.replace('/capabilities/observed-population-v1', ''),
  observedManifest.replace('-r000001', '-r000000'),
  observedManifest.replace('-r000001', '-r1'),
  observedManifest.replace('-r000001', '-r1000000'),
  observedManifest.replace('2026-11-02', '2026-02-30'),
  observedManifest.replace('2026-11-02', '2026-13-02'),
  observedManifest.replace('-r000001', ''),
  observedManifest.replace('manifest.json', 'key.json'),
  observedManifest.replace('manifest.json', 'publication-provenance.json'),
  observedManifest.replace('manifest.json', 'preservation.json'),
  observedManifest.replace('manifest.json', 'core-secret.json.gz'),
  observedManifest.replace('manifest.json', 'core-2026-11-02-xyz.json.gz'),
  observedManifest.replace('manifest.json', 'a%2Fb.json'),
  observedManifest.replace('manifest.json', '%6danifest.json'),
  observedManifest.replace('manifest.json', '../manifest.json'),
  observedManifest.replace('manifest.json', 'manifest.json/extra'),
  observedManifest.replace('https:', 'http:'),
  ...['?_=123', '?legacy_sha256=' + 'a'.repeat(64), '?url=https://example.org', '?', '#fragment', '#']
    .map(suffix => observedManifest + suffix),
];
for (const target of invalidObserved) test(`capability rejects invalid or cross-channel request ${target}`, async () => {
  let calls = 0;
  const forbidden = async () => { calls++; throw new Error('must reject before dependencies'); };
  const response = await handleRequest(request(target), { RATE_LIMITER: { limit: forbidden } }, context,
    forbidden, { match: forbidden, put: forbidden });
  assert.equal(response.status, 400);
  assert.equal(calls, 0);
});

test('capability does not negotiate with version headers or legacy decode hints', async () => {
  const rejected = new Request(observedManifest, { headers: { 'X-AR-Legacy-SHA256': 'a'.repeat(64) } });
  assert.equal((await handleRequest(rejected, env, context, fetcher, null)).status, 400);
  for (const version of ['', '1', 'observed-population-v1']) {
    const req = new Request(url, { headers: { 'X-App-Version': version, 'X-AR-Capability': version } });
    assert.equal(releaseRoute(req).upstream, releaseRoute(request(url)).upstream);
    assert.equal((await handleRequest(req, env, context, fetcher, null)).status, 200);
  }
});

for (const reverse of [false, true]) test(`legacy/capability cold and warm cache isolation (reverse=${reverse})`, async () => {
  const legacyIndex = 'https://service.example/v1/release/app-payload-latest/dates-index.json';
  const legacyManifest = 'https://service.example/v1/release/app-payload-2026-11-02-r000001/manifest.json';
  const targets = [legacyIndex, observedIndex, legacyManifest, observedManifest];
  if (reverse) targets.reverse();
  const domain = new Map(targets.map(target => [target, Buffer.from('isolated protocol control: ' + target)]));
  const encrypted = new Map(await Promise.all(targets.map(async target => [releaseRoute(request(target)).upstream, await envelope(domain.get(target))])));
  const entries = new Map();
  const calls = [];
  const pending = [];
  const cache = { match: async key => entries.get(key)?.clone(), put: async (key, value) => { entries.set(key, value); } };
  const origin = async target => {
    calls.push(target);
    const upstream = new URL(target); upstream.search = '';
    assert.ok(encrypted.has(upstream.toString()));
    return new Response(encrypted.get(upstream.toString()));
  };
  for (let pass = 0; pass < 2; pass++) for (const target of targets) {
    const response = await handleRequest(request(target), env, { waitUntil: p => pending.push(p) }, origin, cache);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('location'), null);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), domain.get(target));
    assert.equal(response.headers.get('etag'), `"${hex(await crypto.subtle.digest('SHA-256', domain.get(target)))}"`);
    assert.equal(response.headers.get('content-encoding'), null);
    assert.equal(response.headers.get('cache-control'), target.includes('r000001') ? 'public, max-age=31536000, immutable' : 'public, max-age=30');
    await Promise.all(pending);
  }
  assert.equal(calls.length, 4);
  assert.equal(entries.size, 4);
  assert.deepEqual(new Set([...entries.keys()].map(k => new URL(k).pathname)), new Set(targets.map(k => new URL(k).pathname)));
  for (const target of calls) assert.equal(new URL(target).searchParams.has('_'), target.includes('latest') || target.includes('candidate'));
  for (const bad of [observedManifest.replace('/capabilities/observed-population-v1', ''),
    observedManifest.replace(observedTag, 'app-payload-2026-11-02-r000001'),
    observedManifest.replace('observed-population-v1', 'unknown')]) {
    assert.equal((await handleRequest(request(bad), env, context, origin, cache)).status, 400);
  }
  assert.equal(calls.length, 4);
});

test('capability retains encrypted, redirect, rate, size and secret boundaries', async () => {
  let calls = 0;
  const redirected = await handleRequest(request(observedManifest), env, context, async target => {
    calls++;
    if (calls === 1) {
      assert.equal(target, releaseRoute(request(observedManifest)).upstream);
      return new Response(null, { status: 302, headers: { location: 'https://release-assets.githubusercontent.com/controlled' } });
    }
    return new Response(wire);
  }, null);
  assert.equal(redirected.status, 200); assert.equal(calls, 2);
  assert.deepEqual(Buffer.from(await redirected.arrayBuffer()), content);
  assert.equal(redirected.headers.get('location'), null);
  assert.equal(JSON.stringify([...redirected.headers]).includes(hex(keyBytes)), false);
  const tampered = wire.slice(); tampered[tampered.length - 1] ^= 1;
  for (const upstream of [() => new Response(content), () => new Response(tampered),
    () => new Response(null, { status: 404 }),
    () => new Response(null, { status: 302, headers: { location: url } }),
    () => new Response(wire, { headers: { 'content-length': String(MAX_BYTES + 73) } })]) {
    assert.equal((await handleRequest(request(observedManifest), env, context, upstream, null)).status, 502);
  }
  assert.equal((await handleRequest(request(observedManifest), { RELEASE_KEYS: secret }, context, fetcher, null)).status, 429);
  assert.equal((await handleRequest(request(observedManifest), { ...env, RELEASE_KEYS: '{}' }, context, fetcher, null)).status, 502);
});
