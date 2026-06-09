#!/usr/bin/env node
/**
 * Monotonic android.versionCode for GHA preview APK builds.
 * Reads build_number from the rolling app-apk-latest manifest (if present) and sets
 * app.json expo.android.versionCode to max(manifest+1, current).
 *
 * Usage: node scripts/bump-android-version-code.mjs [--repo owner/name]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const mobileDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const TAG = 'app-apk-latest';
const MANIFEST_ASSET = 'app-apk-latest.json';

const repoArgIdx = process.argv.indexOf('--repo');
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  'yanniedog/AR-local';

const appJsonPath = join(mobileDir, 'app.json');
const appJson = JSON.parse(readFileSync(appJsonPath, 'utf8'));
const current = Number(appJson.expo?.android?.versionCode ?? 1) || 1;

async function fetchRemoteBuildNumber() {
  const url = `https://github.com/${repo}/releases/download/${TAG}/${MANIFEST_ASSET}`;
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    console.log(`bump-android-version-code: no manifest at ${url} (HTTP ${res.status}); starting from current`);
    return null;
  }
  const manifest = await res.json();
  const n = parseInt(String(manifest.build_number ?? ''), 10);
  return Number.isFinite(n) ? n : null;
}

async function main() {
  const remote = await fetchRemoteBuildNumber();
  const runFloor = Number(process.env.GITHUB_RUN_NUMBER ?? 0) || 0;
  const next = remote != null ? Math.max(remote + 1, current, runFloor) : Math.max(current, runFloor);
  if (next === current && remote == null) {
    console.log(`bump-android-version-code: versionCode stays ${current} (no remote manifest)`);
    return;
  }
  if (next === current) {
    console.log(`bump-android-version-code: versionCode stays ${current} (already ahead of remote)`);
    return;
  }
  appJson.expo.android = { ...appJson.expo.android, versionCode: next };
  writeFileSync(appJsonPath, JSON.stringify(appJson, null, 2) + '\n', 'utf8');
  console.log(`bump-android-version-code: versionCode ${current} → ${next}`);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
