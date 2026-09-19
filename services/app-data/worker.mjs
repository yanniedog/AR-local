// Public app data, private release keys. Never serve a key or accept an arbitrary URL.
export const MAX_BYTES = 8 * 1024 * 1024;
const MAGIC = new TextEncoder().encode('ARE2');
const encoder = new TextEncoder();
const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
let active = 0;
const DOCUMENTS = new Set(['manifest.json', 'manifest-v2.json', 'dates-index.json',
  'revision-delta.json', 'base-manifest.json', 'source-manifest.json']);
export const PAYLOAD = /^(?:core|details|search-index|history-banks|bank-history|bank-spread-history|rba-calendar|v2-product-history|v2-economic-outlook|terms-index|terms_shard_\d{3}|executable-index|executable_shard_\d{3}|executable_v2_(?:index|shard_\d{3})|monetary_v[34]_[a-z_]+_(?:index|shard_\d{3}))-\d{4}-\d{2}-\d{2}-[a-f0-9]{12}\.json\.gz(?:\.enc)?$/;

function headers() {
  return { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'X-AR-Legacy-SHA256',
    'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' };
}
function failure(status) {
  return new Response('Data service temporarily unavailable.', { status,
    headers: { ...headers(), ...(status === 429 || status === 503 ? { 'Retry-After': '2' } : {}) } });
}
export function releaseRoute(request) {
  const url = new URL(request.url);
  const match = /^\/v1\/release\/(app-payload-(?:latest|\d{4}-\d{2}-\d{2}(?:-r\d{6})?))\/([A-Za-z0-9][A-Za-z0-9_.-]*)$/.exec(url.pathname);
  if (!match || !(DOCUMENTS.has(match[2]) || PAYLOAD.test(match[2]))) throw new Error('Invalid route');
  for (const name of url.searchParams.keys()) if (!['_', 'legacy_sha256'].includes(name)) throw new Error('Invalid query');
  const legacySha = url.searchParams.get('legacy_sha256') ?? request.headers.get('X-AR-Legacy-SHA256');
  if (legacySha !== null && !/^[a-f0-9]{64}$/.test(legacySha)) throw new Error('Invalid digest');
  const canonical = new URL(url.origin + url.pathname);
  if (legacySha) canonical.searchParams.set('legacy_sha256', legacySha);
  return { tag: match[1], asset: match[2], legacySha, canonical: canonical.toString(),
    upstream: `https://github.com/yanniedog/AR-local/releases/download/${match[1]}/${match[2]}` };
}
async function readBounded(response) {
  const size = Number(response.headers.get('content-length'));
  if (size > MAX_BYTES + 72 || !response.body) {
    await response.body?.cancel();
    throw new Error('Invalid upstream size');
  }
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BYTES + 72) throw new Error('Upstream too large');
      chunks.push(value);
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}
async function fetchSource(url, fetcher, signal) {
  for (let hop = 0; hop < 3; hop++) {
    const response = await fetcher(url, { redirect: 'manual', signal });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get('location');
      await response.body?.cancel();
      if (!location) throw new Error('Missing redirect');
      const next = new URL(location, url);
      if (next.protocol !== 'https:' || next.username || next.password || next.port ||
          !['release-assets.githubusercontent.com', 'objects.githubusercontent.com'].includes(next.hostname)) {
        throw new Error('Unsafe redirect');
      }
      url = next.toString();
      continue;
    }
    if (!response.ok) { await response.body?.cancel(); throw new Error('Upstream failed'); }
    return readBounded(response);
  }
  throw new Error('Redirect limit');
}
async function keyring(secret) {
  const source = JSON.parse(secret);
  if (!source || Array.isArray(source) || typeof source !== 'object') throw new Error('Missing keys');
  const rows = Object.entries(source);
  if (!rows.length || rows.length > 8) throw new Error('Invalid key count');
  const keys = new Map();
  for (const [id, value] of rows) {
    if (!/^[a-f0-9]{32}$/.test(id) || typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw new Error('Invalid key');
    const bytes = Uint8Array.from(value.match(/../g), x => parseInt(x, 16));
    const prefix = encoder.encode('ar-local-payload-key:');
    const material = new Uint8Array(prefix.length + bytes.length);
    material.set(prefix); material.set(bytes, prefix.length);
    if (hex(await crypto.subtle.digest('SHA-256', material)).slice(0, 32) !== id) throw new Error('Key mismatch');
    keys.set(id, await crypto.subtle.importKey('raw', bytes, 'AES-GCM', false, ['decrypt']));
  }
  return keys;
}
export async function decodeRelease(bytes, secret, legacySha = null) {
  if (bytes.length < 72 || MAGIC.some((b, i) => b !== bytes[i])) throw new Error('Encrypted transport required');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const size = view.getUint32(40, false);
  if (view.getUint32(36, false) !== 0 || size > MAX_BYTES || bytes.length !== size + 72) throw new Error('Invalid size');
  const id = new TextDecoder().decode(bytes.subarray(4, 36));
  const keys = await keyring(secret);
  const key = keys.get(id);
  if (!key) throw new Error('Key unavailable');
  let plain = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM',
    iv: bytes.subarray(44, 56), additionalData: bytes.subarray(0, 44) }, key, bytes.subarray(56)));
  const kind = new TextDecoder().decode(plain.subarray(0, 4));
  if (kind === 'ARE2') throw new Error('Nested transport');
  // Frozen ARE1 domain hashes must remain verifiable before this optional decode.
  if (legacySha) {
    if (kind !== 'ARE1' || plain.length < 32 || hex(await crypto.subtle.digest('SHA-256', plain)) !== legacySha) throw new Error('Legacy identity mismatch');
    let decoded;
    for (const retained of keys.values()) {
      try { decoded = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM',
        iv: plain.subarray(4, 16), additionalData: plain.subarray(0, 4) }, retained, plain.subarray(16))); break; }
      catch { /* Try retained historical keys without exposing errors or material. */ }
    }
    if (!decoded) throw new Error('Legacy authentication failed');
    plain = decoded;
    if (['ARE1', 'ARE2'].includes(new TextDecoder().decode(plain.subarray(0, 4)))) throw new Error('Nested domain');
  }
  return plain;
}
export async function handleRequest(request, env, ctx, fetcher = fetch, cache = globalThis.caches?.default) {
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: headers() });
  if (request.method !== 'GET') return failure(405);
  if (new URL(request.url).pathname === '/health') return new Response('app-data-v1', { headers: headers() });
  let route;
  try { route = releaseRoute(request); } catch { return failure(400); }
  try {
    if (!env.RATE_LIMITER || !(await env.RATE_LIMITER.limit({ key: request.headers.get('cf-connecting-ip') || 'unknown' })).success) return failure(429);
    const cacheKey = new URL(route.canonical);
    cacheKey.searchParams.set('__delivery', '2'); // Do not reuse pre-Vary responses.
    const cached = await cache?.match(cacheKey.toString());
    if (cached) return cached;
    if (active >= 2) return failure(503);
    active++;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    try {
      const immutable = /-r\d{6}$/.test(route.tag);
      const upstream = immutable ? route.upstream : `${route.upstream}?_=${Date.now()}`;
      const bytes = await fetchSource(upstream, fetcher, controller.signal);
      const plain = await decodeRelease(bytes, env.RELEASE_KEYS, route.legacySha);
      const digest = hex(await crypto.subtle.digest('SHA-256', plain));
      const response = new Response(plain, { headers: { ...headers(),
        'Content-Type': 'application/octet-stream', 'Content-Length': String(plain.length),
        'Vary': 'X-AR-Legacy-SHA256',
        'ETag': `"${digest}"`, 'Cache-Control': immutable ? 'public, max-age=31536000, immutable' : 'public, max-age=30',
        ...(route.legacySha ? { 'X-AR-Source-SHA256': route.legacySha } : {}) } });
      if (cache) ctx.waitUntil(cache.put(cacheKey.toString(), response.clone()).catch(() => {}));
      return response;
    } finally { clearTimeout(timeout); active--; }
  } catch { return failure(502); }
}
export default { fetch: handleRequest };
