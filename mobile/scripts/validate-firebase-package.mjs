#!/usr/bin/env node
/** Fail fast when google-services.json package_name != app.json android.package */
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

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

const gs = JSON.parse(readFileSync(gsPath, 'utf8'));
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
