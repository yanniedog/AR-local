#!/usr/bin/env node
/**
 * Bump expo.version patch segment in mobile/app.json (semver x.y.z → x.y.(z+1)).
 *
 * Usage: node scripts/bump-app-patch-version.mjs [--dry-run]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { bumpPatchVersion } from './bump-app-patch-version-pure.cjs';

const mobileDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const appJsonPath = join(mobileDir, 'app.json');
const dryRun = process.argv.includes('--dry-run');

const appJson = JSON.parse(readFileSync(appJsonPath, 'utf8'));
const current = String(appJson.expo?.version ?? '1.0.0').trim();
const next = bumpPatchVersion(current);

if (next === current) {
  console.error(`bump-app-patch-version: cannot bump invalid version "${current}"`);
  process.exit(1);
}

if (dryRun) {
  console.log(`bump-app-patch-version: dry-run ${current} → ${next}`);
  process.exit(0);
}

appJson.expo.version = next;
writeFileSync(appJsonPath, JSON.stringify(appJson, null, 2) + '\n', 'utf8');
console.log(`bump-app-patch-version: ${current} → ${next}`);
