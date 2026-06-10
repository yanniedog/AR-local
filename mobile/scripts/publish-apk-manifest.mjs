#!/usr/bin/env node
/**
 * Publish Android preview APK to GitHub Releases:
 *   1. Rolling tag app-apk-latest (manifest + in-app self-update)
 *   2. Versioned tag app-v{semver} (immutable install history + per-version QR)
 *
 * Usage:
 *   GH_TOKEN=… node scripts/publish-apk-manifest.mjs --apk <path> [--repo owner/name]
 *   EXPO_TOKEN=… GH_TOKEN=… node scripts/publish-apk-manifest.mjs --eas-build-id <id> [--repo owner/name]
 *   GH_TOKEN=… node scripts/publish-apk-manifest.mjs --qr-only [--repo owner/name]
 *   node scripts/publish-apk-manifest.mjs --dry-run-qr [--repo owner/name]
 */
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  APK_ASSET,
  MANIFEST_ASSET,
  ROLLING_TAG,
  CHANGELOG_SUMMARY_ASSET,
  apkDownloadUrl,
  buildChangelogManifest,
  ensureGitHubRelease,
  ensureVersionEntry,
  generateInstallAssets,
  generateReleaseNotes,
  gh,
  installReleaseUrl,
  manifestReleaseUrl,
  qrReleaseUrl,
  readAppJsonBuildNumber,
  readAppJsonVersion,
  releaseTitle,
  renderRollingReleaseNotes,
  versionTag,
} from './app-release-utils.mjs';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const mobileRoot = join(__dirname, '..');

const repoArgIdx = process.argv.indexOf('--repo');
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  'yanniedog/AR-local';

const qrOnly = process.argv.includes('--qr-only');
const dryRunQr = process.argv.includes('--dry-run-qr');
const apkArgIdx = process.argv.indexOf('--apk');
const easArgIdx = process.argv.indexOf('--eas-build-id');
const legacyBuildId = process.argv[2]?.trim();
const localApkPath = apkArgIdx >= 0 ? process.argv[apkArgIdx + 1]?.trim() : '';
const easBuildId =
  (easArgIdx >= 0 ? process.argv[easArgIdx + 1]?.trim() : '') ||
  (legacyBuildId && !legacyBuildId.startsWith('-') && legacyBuildId !== '--apk' ? legacyBuildId : '');

const ghToken = process.env.GH_TOKEN?.trim();

function rollingApkDownloadUrl() {
  return apkDownloadUrl(repo, ROLLING_TAG);
}

function rollingQrReleaseUrl() {
  return qrReleaseUrl(repo, ROLLING_TAG);
}

function rollingInstallReleaseUrl() {
  return installReleaseUrl(repo, ROLLING_TAG);
}

function rollingManifestReleaseUrl() {
  return manifestReleaseUrl(repo, ROLLING_TAG);
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
    version: build.appVersion || readAppJsonVersion(mobileRoot),
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
        '   or: node scripts/publish-apk-manifest.mjs --qr-only [--repo owner/name]\n' +
        '   or: node scripts/publish-apk-manifest.mjs --dry-run-qr [--repo owner/name]',
    );
    process.exit(1);
  }
  if (!existsSync(path)) {
    throw new Error(`APK not found: ${path}`);
  }
  const apkBuf = readFileSync(path);
  return {
    apkBuf,
    version: readAppJsonVersion(mobileRoot),
    buildNumber: readAppJsonBuildNumber(mobileRoot),
    source: 'gha',
    easBuildId: null,
  };
}

function releaseAssetNames() {
  const raw = gh(ghToken, repo, ['release', 'view', ROLLING_TAG, '--json', 'assets']);
  const data = JSON.parse(raw);
  return (data.assets ?? []).map((asset) => asset.name);
}

function assertApkReleaseAssetExists() {
  const names = releaseAssetNames();
  if (!names.includes(APK_ASSET)) {
    throw new Error(
      `${APK_ASSET} not found on ${ROLLING_TAG} release — publish an APK first (omit --qr-only)`,
    );
  }
}

function ensureRollingReleaseExists() {
  const view = spawnSync('gh', ['release', 'view', ROLLING_TAG, '--repo', repo], {
    encoding: 'utf8',
    env: { ...process.env, GH_TOKEN: ghToken },
  });
  if (view.status !== 0) {
    gh(ghToken, repo, [
      'release',
      'create',
      ROLLING_TAG,
      '--title',
      'Australian Rates app (rolling preview APK)',
      '--notes',
      'Rolling preview APK for in-app self-update. Updated by mobile-android-apk (GHA) or mobile-eas-build.',
      '--latest=false',
    ]);
  }
}

function writeChangelogSummaryArtifact({ version, outDir }) {
  ensureVersionEntry({ version, mobileRoot, repo });
  const manifest = buildChangelogManifest({ repo, mobileRoot });
  const summaryPath = join(outDir, CHANGELOG_SUMMARY_ASSET);
  writeFileSync(summaryPath, JSON.stringify(manifest, null, 2) + '\n', 'utf8');
  return summaryPath;
}

function refreshRollingReleaseNotes({ version, buildNumber }) {
  const title = 'Australian Rates app (rolling preview APK)';
  const notes = renderRollingReleaseNotes({ version, buildNumber, repo, mobileRoot });
  ensureGitHubRelease(ghToken, repo, ROLLING_TAG, title, notes);
}

function writeJobSummary({ downloadUrl, qrUrl, installUrl, version, buildNumber, versionedTag }) {
  const summaryPath = process.env.GITHUB_STEP_SUMMARY?.trim();
  if (!summaryPath) {
    return;
  }
  const versionedUrl = versionedTag
    ? `https://github.com/${repo}/releases/tag/${versionedTag}`
    : '';
  const lines = [
    '### Preview APK — scan to install',
    '',
    'Point **Android Chrome** at the QR (direct APK download URL):',
    '',
    `![Install QR](${qrUrl})`,
    '',
    version != null && buildNumber != null ? `Version **${version}** (build ${buildNumber})` : '',
    versionedTag ? `Versioned release: [\`${versionedTag}\`](${versionedUrl})` : '',
    '',
    '| Asset | URL |',
    '|---|---|',
    `| APK (rolling) | ${downloadUrl} |`,
    `| QR PNG (rolling) | ${qrUrl} |`,
    `| Install page (rolling) | ${installUrl} |`,
    '',
  ].filter((line) => line !== '');
  writeFileSync(summaryPath, `${lines.join('\n')}\n`, { flag: 'a' });
}

async function publishVersionedRelease({ apkBuf, version, buildNumber, outDir, changelogSummaryPath }) {
  const tag = versionTag(version);
  const title = releaseTitle(version);
  const notes = generateReleaseNotes({ version, buildNumber, mobileRoot, repo });
  const versionOutDir = join(outDir, 'versioned');
  mkdirSync(versionOutDir, { recursive: true });

  const apkPath = join(versionOutDir, APK_ASSET);
  writeFileSync(apkPath, apkBuf);

  const downloadUrl = apkDownloadUrl(repo, tag);
  const { qrPath, installPath, qrUrl, installUrl } = await generateInstallAssets(
    versionOutDir,
    downloadUrl,
    repo,
    tag,
    ROLLING_TAG,
  );

  const targetRef = process.env.GITHUB_SHA?.trim() || '';
  const action = ensureGitHubRelease(ghToken, repo, tag, title, notes, targetRef);
  const uploadPaths = [apkPath, qrPath, installPath];
  if (changelogSummaryPath) {
    uploadPaths.push(changelogSummaryPath);
  }
  gh(ghToken, repo, ['release', 'upload', tag, ...uploadPaths, '--clobber']);

  console.log(`Versioned release ${tag} (${action}): https://github.com/${repo}/releases/tag/${tag}`);
  console.log(`  QR PNG: ${qrUrl}`);
  console.log(`  Install page: ${installUrl}`);
  return { tag, qrUrl, installUrl };
}

async function publishQrOnly() {
  if (!ghToken) {
    console.error('GH_TOKEN is not set');
    process.exit(1);
  }
  const outDir = join(mobileRoot, 'build', 'apk-publish');
  mkdirSync(outDir, { recursive: true });
  ensureRollingReleaseExists();
  assertApkReleaseAssetExists();
  const downloadUrl = rollingApkDownloadUrl();
  console.log(`Generating install QR for ${downloadUrl}…`);
  const { qrPath, installPath, qrUrl, installUrl } = await generateInstallAssets(
    outDir,
    downloadUrl,
    repo,
    ROLLING_TAG,
    ROLLING_TAG,
  );
  gh(ghToken, repo, ['release', 'upload', ROLLING_TAG, qrPath, installPath, '--clobber']);
  console.log(`QR PNG: ${qrUrl}`);
  console.log(`Install page: ${installUrl}`);
  writeJobSummary({ downloadUrl, qrUrl, installUrl });
}

async function dryRunQrLocal() {
  const version = readAppJsonVersion(mobileRoot);
  const buildNumber = readAppJsonBuildNumber(mobileRoot);
  const outDir = join(mobileRoot, 'build', 'apk-publish-dry-run');
  mkdirSync(outDir, { recursive: true });

  const rollingUrl = rollingApkDownloadUrl();
  const rolling = await generateInstallAssets(outDir, rollingUrl, repo, ROLLING_TAG, ROLLING_TAG);

  const versionedTag = versionTag(version);
  const versionedUrl = apkDownloadUrl(repo, versionedTag);
  const versionedDir = join(outDir, 'versioned');
  const versioned = await generateInstallAssets(versionedDir, versionedUrl, repo, versionedTag, ROLLING_TAG);

  const notes = generateReleaseNotes({ version, buildNumber, mobileRoot });
  writeFileSync(join(outDir, 'release-notes.md'), notes, 'utf8');

  console.log('dry-run-qr: wrote local assets (no GitHub upload)');
  console.log(`  rolling QR: ${rolling.qrPath}`);
  console.log(`  versioned tag: ${versionedTag}`);
  console.log(`  versioned QR: ${versioned.qrPath}`);
  console.log(`  release notes: ${join(outDir, 'release-notes.md')}`);
  console.log(`  example title: ${releaseTitle(version)}`);
}

async function publishRelease({ apkBuf, version, buildNumber, source, easBuildId }) {
  if (!ghToken) {
    console.error('GH_TOKEN is not set');
    process.exit(1);
  }

  const outDir = join(mobileRoot, 'build', 'apk-publish');
  mkdirSync(outDir, { recursive: true });
  const apkPath = join(outDir, APK_ASSET);
  writeFileSync(apkPath, apkBuf);

  const sha256 = sha256File(apkPath);
  const downloadUrl = rollingApkDownloadUrl();

  const manifest = {
    schema_version: 1,
    version,
    build_number: buildNumber,
    download_url: downloadUrl,
    sha256,
    bytes: apkBuf.length,
    published_at: new Date().toISOString(),
    repo,
    tag: ROLLING_TAG,
    profile: 'preview',
    build_source: source,
    ...(easBuildId ? { eas_build_id: easBuildId } : {}),
  };

  const manifestPath = join(outDir, MANIFEST_ASSET);
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

  const changelogSummaryPath = writeChangelogSummaryArtifact({ version, outDir });

  const { qrPath, installPath, qrUrl, installUrl } = await generateInstallAssets(
    outDir,
    downloadUrl,
    repo,
    ROLLING_TAG,
    ROLLING_TAG,
  );

  console.log(`Publishing ${ROLLING_TAG} to ${repo} (v${version} build ${buildNumber}, ${apkBuf.length} bytes)…`);

  ensureRollingReleaseExists();
  refreshRollingReleaseNotes({ version, buildNumber });
  gh(ghToken, repo, [
    'release',
    'upload',
    ROLLING_TAG,
    apkPath,
    manifestPath,
    changelogSummaryPath,
    qrPath,
    installPath,
    '--clobber',
  ]);
  console.log(`Published ${downloadUrl}`);
  console.log(`Manifest: ${rollingManifestReleaseUrl()}`);
  console.log(`QR PNG: ${qrUrl}`);
  console.log(`Install page: ${installUrl}`);

  const versioned = await publishVersionedRelease({
    apkBuf,
    version,
    buildNumber,
    outDir,
    changelogSummaryPath,
  });

  writeJobSummary({
    downloadUrl,
    qrUrl,
    installUrl,
    version,
    buildNumber,
    versionedTag: versioned.tag,
  });
}

async function main() {
  if (dryRunQr) {
    await dryRunQrLocal();
    return;
  }
  if (qrOnly) {
    await publishQrOnly();
    return;
  }
  const payload = localApkPath
    ? resolveLocalApk(localApkPath)
    : easBuildId
      ? await fetchEasApk(easBuildId)
      : (() => {
          console.error('Provide --apk <path>, --eas-build-id <id>, --qr-only, or --dry-run-qr');
          process.exit(1);
        })();
  await publishRelease(payload);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
