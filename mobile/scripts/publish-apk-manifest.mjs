#!/usr/bin/env node
/**
 * After a successful EAS preview Android build, publish a rolling GitHub release
 * (tag app-apk-latest) with app-preview.apk + app-apk-latest.json for in-app updates.
 *
 * Usage:
 *   EXPO_TOKEN=… GH_TOKEN=… node scripts/publish-apk-manifest.mjs <buildId> [--repo owner/name]
 */
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const mobileRoot = join(__dirname, '..');
const TAG = 'app-apk-latest';
const APK_ASSET = 'app-preview.apk';
const MANIFEST_ASSET = 'app-apk-latest.json';

const buildId = process.argv[2]?.trim();
const repoArgIdx = process.argv.indexOf('--repo');
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  'yanniedog/AR-local';

if (!buildId) {
  console.error('usage: node scripts/publish-apk-manifest.mjs <buildId> [--repo owner/name]');
  process.exit(1);
}

const expoToken = process.env.EXPO_TOKEN?.trim();
if (!expoToken) {
  console.error('EXPO_TOKEN is not set');
  process.exit(1);
}

const ghToken = process.env.GH_TOKEN?.trim();
if (!ghToken) {
  console.error('GH_TOKEN is not set');
  process.exit(1);
}

const query = `
  query BuildsByIdQuery($buildId: ID!) {
    builds {
      byId(buildId: $buildId) {
        id
        status
        platform
        appVersion
        appBuildVersion
        artifacts { buildUrl applicationArchiveUrl }
      }
    }
  }`;

async function fetchBuild() {
  const res = await fetch('https://api.expo.dev/graphql', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${expoToken}`,
    },
    body: JSON.stringify({ query, variables: { buildId } }),
  });
  const body = await res.json();
  if (!res.ok || body.errors?.length) {
    throw new Error(`EAS GraphQL failed: ${JSON.stringify(body.errors ?? body)}`);
  }
  const build = body.data?.builds?.byId;
  if (!build) {
    throw new Error(`Build not found: ${buildId}`);
  }
  return build;
}

function readAppJsonVersion() {
  const appJson = JSON.parse(readFileSync(join(mobileRoot, 'app.json'), 'utf8'));
  return appJson.expo?.version ?? '1.0.0';
}

function gh(args, opts = {}) {
  return execFileSync('gh', args, {
    encoding: 'utf8',
    env: { ...process.env, GH_TOKEN: ghToken },
    stdio: ['ignore', 'pipe', 'pipe'],
    ...opts,
  });
}

function sha256File(path) {
  const hash = createHash('sha256');
  hash.update(readFileSync(path));
  return hash.digest('hex');
}

async function main() {
  const build = await fetchBuild();
  if (build.status !== 'FINISHED') {
    console.error(`Build ${buildId} status=${build.status} — not publishing`);
    process.exit(1);
  }
  if (build.platform !== 'ANDROID') {
    console.error(`Build ${buildId} platform=${build.platform} — Android-only publish`);
    process.exit(1);
  }

  const apkUrl = build.artifacts?.applicationArchiveUrl || build.artifacts?.buildUrl;
  if (!apkUrl) {
    throw new Error('EAS build has no APK artifact URL');
  }

  const outDir = join(mobileRoot, 'build', 'apk-publish');
  mkdirSync(outDir, { recursive: true });
  const apkPath = join(outDir, APK_ASSET);

  console.log(`Downloading APK from EAS (${buildId})…`);
  const apkRes = await fetch(apkUrl, {
    headers: { Authorization: `Bearer ${expoToken}` },
  });
  if (!apkRes.ok) {
    throw new Error(`APK download HTTP ${apkRes.status}`);
  }
  const apkBuf = Buffer.from(await apkRes.arrayBuffer());
  writeFileSync(apkPath, apkBuf);

  const version = build.appVersion || readAppJsonVersion();
  const buildNumber = String(build.appBuildVersion ?? '0');
  const sha256 = sha256File(apkPath);
  const downloadUrl = `https://github.com/${repo}/releases/download/${TAG}/${APK_ASSET}`;

  const manifest = {
    schema_version: 1,
    version,
    build_number: buildNumber,
    download_url: downloadUrl,
    sha256,
    bytes: apkBuf.length,
    published_at: new Date().toISOString(),
    repo,
    tag: TAG,
    eas_build_id: buildId,
    profile: 'preview',
  };

  const manifestPath = join(outDir, MANIFEST_ASSET);
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

  console.log(`Publishing ${TAG} to ${repo} (v${version} build ${buildNumber}, ${apkBuf.length} bytes)…`);

  const view = spawnSync('gh', ['release', 'view', TAG, '--repo', repo], {
    encoding: 'utf8',
    env: { ...process.env, GH_TOKEN: ghToken },
  });
  if (view.status !== 0) {
    gh([
      'release',
      'create',
      TAG,
      '--repo',
      repo,
      '--title',
      'AR Rates preview APK (rolling)',
      '--notes',
      'Rolling preview APK for in-app self-update. Updated by mobile-eas-build (preview/android).',
      '--latest=false',
    ]);
  }

  gh(['release', 'upload', TAG, apkPath, manifestPath, '--repo', repo, '--clobber']);
  console.log(`Published ${downloadUrl}`);
  console.log(`Manifest: https://github.com/${repo}/releases/download/${TAG}/${MANIFEST_ASSET}`);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
