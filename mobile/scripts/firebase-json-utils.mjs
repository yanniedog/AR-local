#!/usr/bin/env node
/**
 * Normalize and validate google-services.json text from secrets / EAS env.
 * Fixes common GitHub-secret mistakes without logging secret values.
 */
import { readFileSync } from 'node:fs';

const PLACEHOLDER_PROJECT_ID = 'ar-local-rates-placeholder';

/**
 * @param {string} raw
 * @returns {string}
 */
export function normalizeJsonText(raw) {
  let text = raw.replace(/^\uFEFF/, '').trim();
  if (!text) return text;

  if (text.startsWith("'") && text.endsWith("'") && text.length >= 2) {
    text = text.slice(1, -1).trim();
  }

  if (text.startsWith('"') && text.endsWith('"')) {
    try {
      const unwrapped = JSON.parse(text);
      if (typeof unwrapped === 'string') {
        text = unwrapped.trim();
      }
    } catch {
      // keep original — parseGoogleServicesJson will report the error
    }
  }

  if (text.includes('\\n') || text.includes('\\"')) {
    text = text
      .replace(/\\n/g, '\n')
      .replace(/\\r/g, '\r')
      .replace(/\\t/g, '\t')
      .replace(/\\"/g, '"')
      .replace(/\\\\/g, '\\');
  }

  return text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
}

/**
 * @param {string} text
 * @param {string} source
 * @returns {Record<string, unknown>}
 */
export function parseGoogleServicesJson(text, source) {
  const normalized = normalizeJsonText(text);
  if (!normalized) {
    throw new Error(`${source}: empty google-services.json content`);
  }
  if (!normalized.startsWith('{')) {
    const preview = normalized.slice(0, 40).replace(/\s+/g, ' ');
    throw new Error(
      `${source}: expected JSON object starting with "{" (got ${JSON.stringify(preview)}…). ` +
        'Paste the raw Firebase file body into GOOGLE_SERVICES_JSON — no outer quotes, no base64.',
    );
  }

  let parsed;
  try {
    parsed = JSON.parse(normalized);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const line = normalized.split('\n');
    const hint =
      line.length > 1 && line[1]?.includes('\\')
        ? ' Hint: secret may contain literal \\n instead of newlines.'
        : '';
    throw new Error(`${source}: invalid JSON (${message}).${hint}`);
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${source}: google-services.json must be a JSON object`);
  }
  if (!Array.isArray(parsed.client) || parsed.client.length === 0) {
    throw new Error(`${source}: google-services.json missing non-empty "client" array`);
  }

  return parsed;
}

/** @param {Record<string, unknown>} parsed */
export function isPlaceholderGoogleServices(parsed) {
  const projectId = parsed.project_info?.project_id;
  return projectId === PLACEHOLDER_PROJECT_ID;
}

/**
 * @param {string} text
 * @param {string} source
 * @returns {string} canonical JSON (2-space indent)
 */
export function canonicalGoogleServicesJson(text, source) {
  const parsed = parseGoogleServicesJson(text, source);
  return `${JSON.stringify(parsed, null, 2)}\n`;
}

/**
 * @param {string} path
 * @param {string} source
 * @returns {string}
 */
export function readCanonicalGoogleServicesFile(path, source) {
  return canonicalGoogleServicesJson(readFileSync(path, 'utf8'), source);
}

/**
 * @param {string} raw
 * @returns {string | undefined}
 */
export function decodeB64Json(raw, name) {
  const trimmed = raw?.trim();
  if (!trimmed) return undefined;
  if (!/^[A-Za-z0-9+/_\-=\s]+$/.test(trimmed)) {
    throw new Error(`${name}: invalid base64 characters`);
  }
  return Buffer.from(trimmed, 'base64').toString('utf8');
}
