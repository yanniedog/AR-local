#!/usr/bin/env node
/**
 * Exchange a GCP service-account JSON key for a short-lived OAuth access token.
 * Uses Node crypto only (no google-auth-library dependency).
 */
import { createSign } from 'node:crypto';

const TOKEN_URL = 'https://oauth2.googleapis.com/token';
const DEFAULT_SCOPE = 'https://www.googleapis.com/auth/cloud-platform';

/**
 * @param {Record<string, unknown>} serviceAccount
 * @param {string} [scope]
 * @returns {Promise<string>}
 */
export async function getServiceAccountAccessToken(serviceAccount, scope = DEFAULT_SCOPE) {
  const email = String(serviceAccount.client_email || '').trim();
  const privateKey = String(serviceAccount.private_key || '').trim();
  if (!email || !privateKey) {
    throw new Error('service account JSON missing client_email or private_key');
  }

  const now = Math.floor(Date.now() / 1000);
  const header = { alg: 'RS256', typ: 'JWT' };
  const claim = {
    iss: email,
    scope,
    aud: TOKEN_URL,
    exp: now + 3600,
    iat: now,
  };

  const unsigned = `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(claim))}`;
  const signer = createSign('RSA-SHA256');
  signer.update(unsigned);
  signer.end();
  const signature = signer.sign(privateKey, 'base64url');
  const assertion = `${unsigned}.${signature}`;

  const response = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion,
    }),
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.error_description || payload.error || response.statusText;
    throw new Error(`service account token exchange failed (${response.status}): ${detail}`);
  }
  if (!payload.access_token) {
    throw new Error('service account token exchange returned no access_token');
  }
  return String(payload.access_token);
}

/** @param {string} raw */
export function parseServiceAccountJson(raw, source = 'FIREBASE_SERVICE_ACCOUNT_JSON') {
  const text = raw.replace(/^\uFEFF/, '').trim();
  if (!text) {
    throw new Error(`${source} is empty`);
  }
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
  return parsed;
}

/** @param {string} text */
function base64url(text) {
  return Buffer.from(text, 'utf8').toString('base64url');
}
