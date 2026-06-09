#!/usr/bin/env node
/**
 * Materialize Firebase config for local export and EAS cloud builds.
 *
 * google-services.json sources (first valid match wins):
 *   1. GOOGLE_SERVICES_JSON_B64 env (normalized + JSON.parse)
 *   2. GOOGLE_SERVICES_JSON env — inline JSON or EAS file-path env
 *   3. Existing file on disk when already valid JSON
 *   4. google-services.json.example placeholder
 *
 * EAS: eas-build-pre-install (package.json; gitignored file is not uploaded).
 * GHA: mobile-eas-build.yml materialize step (single entry point).
 */
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  canonicalGoogleServicesJson,
  decodeB64Json,
  isPlaceholderGoogleServices,
  normalizeJsonText,
  parseGoogleServicesJson,
} from './firebase-json-utils.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const mobileDir = join(root, '..');

/** @param {string} message */
function fail(message) {
  console.error(`ensure-firebase-config: ${message}`);
  process.exit(1);
}

/**
 * @param {string} targetPath
 * @returns {string | undefined}
 */
function readValidGoogleServicesAt(targetPath) {
  if (!existsSync(targetPath)) return undefined;
  try {
    const canonical = canonicalGoogleServicesJson(readFileSync(targetPath, 'utf8'), targetPath);
    return canonical;
  } catch {
    return undefined;
  }
}

/**
 * @returns {string | undefined}
 */
function resolveGoogleServicesFromEnv() {
  const b64Raw = process.env.GOOGLE_SERVICES_JSON_B64;
  if (b64Raw?.trim()) {
    try {
      const decoded = decodeB64Json(b64Raw, 'GOOGLE_SERVICES_JSON_B64');
      return canonicalGoogleServicesJson(decoded, 'GOOGLE_SERVICES_JSON_B64');
    } catch (err) {
      fail(err instanceof Error ? err.message : String(err));
    }
  }

  const envVal = process.env.GOOGLE_SERVICES_JSON?.trim();
  if (!envVal) return undefined;

  const normalized = normalizeJsonText(envVal);
  if (normalized.startsWith('{')) {
    return canonicalGoogleServicesJson(normalized, 'GOOGLE_SERVICES_JSON');
  }

  const srcPath = isAbsolute(envVal) ? envVal : join(mobileDir, envVal);
  if (existsSync(srcPath)) {
    return canonicalGoogleServicesJson(readFileSync(srcPath, 'utf8'), `GOOGLE_SERVICES_JSON path (${srcPath})`);
  }

  fail(
    `GOOGLE_SERVICES_JSON is not inline JSON and path does not exist: ${srcPath}. ` +
      'On EAS, use a file-type GOOGLE_SERVICES_JSON env or GOOGLE_SERVICES_JSON_B64.',
  );
}

function materializeGoogleServices() {
  const target = 'google-services.json';
  const targetPath = join(mobileDir, target);
  const examplePath = join(mobileDir, 'google-services.json.example');

  const fromEnv = resolveGoogleServicesFromEnv();
  if (fromEnv) {
    writeFileSync(targetPath, fromEnv, 'utf8');
    const parsed = parseGoogleServicesJson(fromEnv, target);
    const kind = isPlaceholderGoogleServices(parsed) ? 'placeholder' : 'real';
    console.log(`ensure-firebase-config: wrote ${target} from env (${kind}, ${fromEnv.length} bytes)`);
    return;
  }

  const existing = readValidGoogleServicesAt(targetPath);
  if (existing) {
    console.log(`ensure-firebase-config: ${target} already valid on disk (${existing.length} bytes)`);
    return;
  }

  if (!existsSync(examplePath)) {
    fail(`Missing google-services.json.example — cannot materialize ${target}`);
  }
  copyFileSync(examplePath, targetPath);
  console.log(`ensure-firebase-config: copied google-services.json.example → ${target}`);
}

/**
 * @param {string} target
 * @param {{ envVar: string; b64Var: string; example: string; inlinePrefix: string }} options
 */
function materializePlist(target, options) {
  const { envVar, b64Var, example, inlinePrefix } = options;
  const targetPath = join(mobileDir, target);
  const examplePath = join(mobileDir, example);

  const fromB64 = process.env[b64Var]?.trim()
    ? decodeB64Json(process.env[b64Var], b64Var)
    : undefined;
  if (fromB64) {
    writeFileSync(targetPath, fromB64, 'utf8');
    console.log(`ensure-firebase-config: wrote ${target} from ${b64Var}`);
    return;
  }

  const envVal = process.env[envVar]?.trim();
  if (envVal) {
    if (envVal.startsWith(inlinePrefix)) {
      writeFileSync(targetPath, envVal, 'utf8');
      console.log(`ensure-firebase-config: wrote ${target} from ${envVar} (inline)`);
      return;
    }
    const srcPath = isAbsolute(envVal) ? envVal : join(mobileDir, envVal);
    if (existsSync(srcPath)) {
      writeFileSync(targetPath, readFileSync(srcPath, 'utf8'), 'utf8');
      console.log(`ensure-firebase-config: copied ${envVar} path → ${target}`);
      return;
    }
    fail(`${envVar} is not inline content and path does not exist: ${srcPath}`);
  }

  if (existsSync(targetPath)) {
    console.log(`ensure-firebase-config: ${target} already exists`);
    return;
  }

  if (!existsSync(examplePath)) {
    fail(`Missing ${example} — cannot materialize ${target}`);
  }
  copyFileSync(examplePath, targetPath);
  console.log(`ensure-firebase-config: copied ${example} → ${target}`);
}

materializeGoogleServices();

materializePlist('GoogleService-Info.plist', {
  envVar: 'GOOGLE_SERVICE_INFO_PLIST',
  b64Var: 'GOOGLE_SERVICE_INFO_PLIST_B64',
  example: 'GoogleService-Info.plist.example',
  inlinePrefix: '<',
});

const validate = join(root, 'validate-firebase-package.mjs');
if (existsSync(join(mobileDir, 'google-services.json'))) {
  const result = spawnSync(process.execPath, [validate], { stdio: 'inherit' });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
