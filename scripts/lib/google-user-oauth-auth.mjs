#!/usr/bin/env node
/**
 * Exchange Google authorized_user JSON for a short-lived OAuth access token.
 */
const TOKEN_URL = 'https://oauth2.googleapis.com/token';

/** @param {string} raw */
export function parseAuthorizedUserJson(raw, source = 'FIREBASE_USER_OAUTH_JSON') {
  const text = raw.replace(/^\uFEFF/, '').trim();
  if (!text) throw new Error(`${source} is empty`);

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`${source}: invalid JSON (${message})`);
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${source}: expected JSON object`);
  }
  for (const field of ['client_id', 'client_secret', 'refresh_token']) {
    if (!String(parsed[field] || '').trim()) {
      throw new Error(`${source}: missing ${field}`);
    }
  }
  return parsed;
}

/** @param {Record<string, unknown>} credentials */
export async function getAuthorizedUserAccessToken(credentials) {
  const response = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: String(credentials.client_id),
      client_secret: String(credentials.client_secret),
      refresh_token: String(credentials.refresh_token),
    }),
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.error_description || payload.error || response.statusText;
    throw new Error(`authorized_user token exchange failed (${response.status}): ${detail}`);
  }
  if (!payload.access_token) {
    throw new Error('authorized_user token exchange returned no access_token');
  }
  return String(payload.access_token);
}
