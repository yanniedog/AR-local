import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_BYTES, decodeRelease, handleRequest, releaseRoute } from './worker.mjs';

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
const url = 'https://service.example/v1/release/app-payload-2026-09-19-r000003/core.json.gz';
const env = { RELEASE_KEYS: secret, RATE_LIMITER: { limit: async () => ({ success: true }) } };
const context = { waitUntil: promise => promise };
const request = (target = url, method = 'GET') => new Request(target, { method });
const fetcher = async () => new Response(wire);

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
for (const path of ['/v1/release/app-payload-latest/../key.json', '/v1/release/other/key.json',
  '/v1/release/app-payload-latest/source.zip', '/v1/release/app-payload-latest/a%2Fb.json',
  '/v1/release/app-payload-latest/..secret.json', '/v1/release/app-payload-latest/a.json?url=http://localhost',
  '/v1/release/app-payload-latest/a.json?legacy_sha256=no']) {
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
