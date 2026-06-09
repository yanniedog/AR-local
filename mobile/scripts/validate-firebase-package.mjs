#!/usr/bin/env node
/** Fail fast when google-services.json is malformed or package_name != app.json android.package */
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseGoogleServicesJson } from './firebase-json-utils.mjs';

const mobileDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const appJson = JSON.parse(readFileSync(join(mobileDir, 'app.json'), 'utf8'));
const expected = appJson.expo?.android?.package?.trim();
if (!expected) {
  console.error('validate-firebase-package: missing expo.android.package in app.json');
  process.exit(1);
}

const gsPath = join(mobileDir, 'google-services.json');
if (!existsSync(gsPath)) {
  console.error('validate-firebase-package: google-services.json missing');
  process.exit(1);
}

let gs;
try {
  gs = parseGoogleServicesJson(readFileSync(gsPath, 'utf8'), 'google-services.json');
} catch (err) {
  console.error(err instanceof Error ? err.message : String(err));
  console.error(
    'validate-firebase-package: fix GOOGLE_SERVICES_JSON GitHub secret — paste raw Firebase JSON (no outer quotes).',
  );
  process.exit(1);
}

const packages = (gs.client ?? [])
  .map((c) => c?.client_info?.android_client_info?.package_name)
  .filter(Boolean);

if (!packages.includes(expected)) {
  console.error(
    `validate-firebase-package: package mismatch — app.json expects ${expected}, google-services.json has [${packages.join(', ')}]`,
  );
  process.exit(1);
}

console.log(`validate-firebase-package: ok (${expected}, ${packages.length} client(s))`);
