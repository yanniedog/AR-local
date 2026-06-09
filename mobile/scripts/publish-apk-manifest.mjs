#!/usr/bin/env node
/**
 * Publish a rolling GitHub release (tag app-apk-latest) with app-preview.apk +
 * app-apk-latest.json + app-preview-qr.png + install.html for in-app self-update
 * and scan-to-install (EAS-style QR on desktop).
 *
 * Usage:
 *   GH_TOKEN=… node scripts/publish-apk-manifest.mjs --apk <path> [--repo owner/name]
 *   EXPO_TOKEN=… GH_TOKEN=… node scripts/publish-apk-manifest.mjs --eas-build-id <id> [--repo owner/name]
 *   GH_TOKEN=… node scripts/publish-apk-manifest.mjs --qr-only [--repo owner/name]
 */
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import QRCode from 'qrcode';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const mobileRoot = join(__dirname, '..');
const TAG = 'app-apk-latest';
const APK_ASSET = 'app-preview.apk';
const MANIFEST_ASSET = 'app-apk-latest.json';
const QR_ASSET = 'app-preview-qr.png';
const INSTALL_HTML = 'install.html';

const repoArgIdx = process.argv.indexOf('--repo');
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  'yanniedog/AR-local';

const qrOnly = process.argv.includes('--qr-only');
const apkArgIdx = process.argv.indexOf('--apk');
const easArgIdx = process.argv.indexOf('--eas-build-id');
const legacyBuildId = process.argv[2]?.trim();
const localApkPath = apkArgIdx >= 0 ? process.argv[apkArgIdx + 1]?.trim() : '';
const easBuildId =
  (easArgIdx >= 0 ? process.argv[easArgIdx + 1]?.trim() : '') ||
  (legacyBuildId && !legacyBuildId.startsWith('-') && legacyBuildId !== '--apk' ? legacyBuildId : '');

const ghToken = process.env.GH_TOKEN?.trim();
if (!ghToken) {
  console.error('GH_TOKEN is not set');
  process.exit(1);
}

function apkDownloadUrl() {
  return `https://github.com/${repo}/releases/download/${TAG}/${APK_ASSET}`;
}

function qrReleaseUrl() {
  return `https://github.com/${repo}/releases/download/${TAG}/${QR_ASSET}`;
}

function installReleaseUrl() {
  return `https://github.com/${repo}/releases/download/${TAG}/${INSTALL_HTML}`;
}

function manifestReleaseUrl() {
  return `https://github.com/${repo}/releases/download/${TAG}/${MANIFEST_ASSET}`;
}

function readAppJson() {
  return JSON.parse(readFileSync(join(mobileRoot, 'app.json'), 'utf8'));
}

function readAppJsonVersion() {
  return readAppJson().expo?.version ?? '1.0.0';
}

function readAppJsonBuildNumber() {
  const code = readAppJson().expo?.android?.versionCode;
  return code != null ? String(code) : '0';
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

async function fetchEasApk(buildId) {
  const expoToken = process.env.EXPO_TOKEN?.trim();
  if (!expoToken) {
    throw new Error('EXPO_TOKEN is not set (required for --eas-build-id)');
  }
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
  if (build.status !== 'FINISHED') {
    throw new Error(`Build ${buildId} status=${build.status} — not publishing`);
  }
  if (build.platform !== 'ANDROID') {
    throw new Error(`Build ${buildId} platform=${build.platform} — Android-only publish`);
  }
  const apkUrl = build.artifacts?.applicationArchiveUrl || build.artifacts?.buildUrl;
  if (!apkUrl) {
    throw new Error('EAS build has no APK artifact URL');
  }
  console.log(`Downloading APK from EAS (${buildId})…`);
  const apkRes = await fetch(apkUrl, {
    headers: { Authorization: `Bearer ${expoToken}` },
  });
  if (!apkRes.ok) {
    throw new Error(`APK download HTTP ${apkRes.status}`);
  }
  const apkBuf = Buffer.from(await apkRes.arrayBuffer());
  return {
    apkBuf,
    version: build.appVersion || readAppJsonVersion(),
    buildNumber: String(build.appBuildVersion ?? '0'),
    source: 'eas',
    easBuildId: buildId,
  };
}

function resolveLocalApk(path) {
  if (!path) {
    console.error(
      'usage: node scripts/publish-apk-manifest.mjs --apk <path> [--repo owner/name]\n' +
        '   or: node scripts/publish-apk-manifest.mjs --eas-build-id <id> [--repo owner/name]\n' +
        '   or: node scripts/publish-apk-manifest.mjs --qr-only [--repo owner/name]',
    );
    process.exit(1);
  }
  if (!existsSync(path)) {
    throw new Error(`APK not found: ${path}`);
  }
  const apkBuf = readFileSync(path);
  return {
    apkBuf,
    version: readAppJsonVersion(),
    buildNumber: readAppJsonBuildNumber(),
    source: 'gha',
    easBuildId: null,
  };
}

async function generateInstallAssets(outDir, downloadUrl) {
  const qrPath = join(outDir, QR_ASSET);
  await QRCode.toFile(qrPath, downloadUrl, {
    type: 'png',
    width: 512,
    margin: 2,
    errorCorrectionLevel: 'M',
  });

  const qrUrl = qrReleaseUrl();
  const installUrl = installReleaseUrl();
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Install AR Rates preview APK</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 32rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.4; }
    img { display: block; width: 16rem; height: 16rem; margin: 1rem auto; }
    a { word-break: break-all; }
    p { margin: 0.75rem 0; }
  </style>
</head>
<body>
  <h1>Install preview APK</h1>
  <p>Scan with <strong>Android Chrome</strong> (camera or QR scanner). Chrome downloads the APK directly from GitHub Releases.</p>
  <img src="${qrUrl}" width="512" height="512" alt="QR code for APK download">
  <p><a href="${downloadUrl}">Direct APK download</a></p>
  <p><small>Manifest: <a href="${manifestReleaseUrl()}">${MANIFEST_ASSET}</a></small></p>
</body>
</html>
`;
  const installPath = join(outDir, INSTALL_HTML);
  writeFileSync(installPath, html);
  return { qrPath, installPath, qrUrl, installUrl };
}

function releaseAssetNames() {
  const raw = gh(['release', 'view', TAG, '--repo', repo, '--json', 'assets']);
  const data = JSON.parse(raw);
  return (data.assets ?? []).map((asset) => asset.name);
}

function assertApkReleaseAssetExists() {
  const names = releaseAssetNames();
  if (!names.includes(APK_ASSET)) {
    throw new Error(
      `${APK_ASSET} not found on ${TAG} release — publish an APK first (omit --qr-only)`,
    );
  }
}

function ensureReleaseExists() {
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
      'Rolling preview APK for in-app self-update. Updated by mobile-android-apk (GHA) or mobile-eas-build.',
      '--latest=false',
    ]);
  }
}

function writeJobSummary({ downloadUrl, qrUrl, installUrl, version, buildNumber }) {
  const summaryPath = process.env.GITHUB_STEP_SUMMARY?.trim();
  if (!summaryPath) {
    return;
  }
  const lines = [
    '### Preview APK — scan to install',
    '',
    'Point **Android Chrome** at the QR (direct APK download URL):',
    '',
    `![Install QR](${qrUrl})`,
    '',
    version != null && buildNumber != null ? `Version **${version}** (build ${buildNumber})` : '',
    '',
    '| Asset | URL |',
    '|---|---|',
    `| APK | ${downloadUrl} |`,
    `| QR PNG | ${qrUrl} |`,
    `| Install page | ${installUrl} |`,
    '',
  ].filter((line) => line !== '');
  writeFileSync(summaryPath, `${lines.join('\n')}\n`, { flag: 'a' });
}

async function publishQrOnly() {
  const outDir = join(mobileRoot, 'build', 'apk-publish');
  mkdirSync(outDir, { recursive: true });
  ensureReleaseExists();
  assertApkReleaseAssetExists();
  const downloadUrl = apkDownloadUrl();
  console.log(`Generating install QR for ${downloadUrl}…`);
  const { qrPath, installPath, qrUrl, installUrl } = await generateInstallAssets(outDir, downloadUrl);
  gh(['release', 'upload', TAG, qrPath, installPath, '--repo', repo, '--clobber']);
  console.log(`QR PNG: ${qrUrl}`);
  console.log(`Install page: ${installUrl}`);
  writeJobSummary({ downloadUrl, qrUrl, installUrl });
}

async function publishRelease({ apkBuf, version, buildNumber, source, easBuildId }) {
  const outDir = join(mobileRoot, 'build', 'apk-publish');
  mkdirSync(outDir, { recursive: true });
  const apkPath = join(outDir, APK_ASSET);
  writeFileSync(apkPath, apkBuf);

  const sha256 = sha256File(apkPath);
  const downloadUrl = apkDownloadUrl();

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
    profile: 'preview',
    build_source: source,
    ...(easBuildId ? { eas_build_id: easBuildId } : {}),
  };

  const manifestPath = join(outDir, MANIFEST_ASSET);
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

  const { qrPath, installPath, qrUrl, installUrl } = await generateInstallAssets(outDir, downloadUrl);

  console.log(`Publishing ${TAG} to ${repo} (v${version} build ${buildNumber}, ${apkBuf.length} bytes)…`);

  ensureReleaseExists();
  gh(['release', 'upload', TAG, apkPath, manifestPath, qrPath, installPath, '--repo', repo, '--clobber']);
  console.log(`Published ${downloadUrl}`);
  console.log(`Manifest: ${manifestReleaseUrl()}`);
  console.log(`QR PNG: ${qrUrl}`);
  console.log(`Install page: ${installUrl}`);
  writeJobSummary({ downloadUrl, qrUrl, installUrl, version, buildNumber });
}

async function main() {
  if (qrOnly) {
    await publishQrOnly();
    return;
  }
  const payload = localApkPath
    ? resolveLocalApk(localApkPath)
    : easBuildId
      ? await fetchEasApk(easBuildId)
      : (() => {
          console.error('Provide --apk <path>, --eas-build-id <id>, or --qr-only');
          process.exit(1);
        })();
  await publishRelease(payload);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
