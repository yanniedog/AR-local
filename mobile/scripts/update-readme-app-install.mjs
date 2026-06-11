#!/usr/bin/env node
/**
 * Refresh README.md Android install section (stable rolling QR URL + current version).
 * Safe to run from GHA: README.md is outside mobile/** path filter so push won't re-trigger APK build.
 *
 * Usage: node scripts/update-readme-app-install.mjs [--repo owner/name] [--readme path]
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  ROLLING_TAG,
  apkDownloadUrl,
  installReleaseUrl,
  qrReleaseUrl,
  readAppJsonBuildNumber,
  readAppJsonVersion,
} from './app-release-meta.mjs';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const mobileRoot = join(__dirname, '..');
const repoRoot = join(mobileRoot, '..');

const repoArgIdx = process.argv.indexOf('--repo');
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  'yanniedog/AR-local';

const readmeArgIdx = process.argv.indexOf('--readme');
const readmePath = resolve(
  readmeArgIdx >= 0 ? process.argv[readmeArgIdx + 1] : join(repoRoot, 'README.md'),
);

const START = '<!-- app-android-install:start -->';
const END = '<!-- app-android-install:end -->';

/** @typedef {{ version: string, buildNumber: string, manifestPath?: string }} ReleaseMeta */

/**
 * @param {string} [manifestPath]
 * @returns {ReleaseMeta}
 */
export function resolveVersionAndBuild(manifestPath) {
  let version = readAppJsonVersion(mobileRoot);
  let buildNumber = readAppJsonBuildNumber(mobileRoot);
  const resolvedManifest = manifestPath?.trim();
  if (resolvedManifest && existsSync(resolvedManifest)) {
    try {
      const manifest = JSON.parse(readFileSync(resolvedManifest, 'utf8'));
      if (manifest.version) version = String(manifest.version);
      if (manifest.build_number != null) buildNumber = String(manifest.build_number);
    } catch (err) {
      console.error(`Error reading or parsing manifest at ${resolvedManifest}:`, err);
    }
  }
  return { version, buildNumber, manifestPath: resolvedManifest };
}

function manifestPathFromArgv() {
  const manifestArgIdx = process.argv.indexOf('--manifest');
  if (manifestArgIdx < 0) return undefined;
  const rawPath = process.argv[manifestArgIdx + 1];
  return rawPath ? resolve(rawPath) : undefined;
}

/**
 * @param {{ repo?: string, manifestPath?: string }} [opts]
 * @returns {string}
 */
export function buildReadmeInstallSection(opts = {}) {
  const ghRepo = opts.repo?.trim() || repo;
  const { version, buildNumber } = resolveVersionAndBuild(opts.manifestPath);
  const qrUrl = qrReleaseUrl(ghRepo, ROLLING_TAG, { bust: buildNumber });
  const apkUrl = apkDownloadUrl(ghRepo, ROLLING_TAG);
  const installUrl = installReleaseUrl(ghRepo, ROLLING_TAG);
  const releasesUrl = `https://github.com/${ghRepo}/releases?q=app-v&expanded=true`;

  return `${START}
### Android preview install

Scan with **Android Chrome** to install the latest preview APK. Asset path is stable (\`${ROLLING_TAG}/app-preview-qr.png\`); the README embed adds \`?v=<build>\` so the image refreshes after each APK publish.

| | |
|---|---|
| Version | **${version}** (build ${buildNumber}) |
| QR | ![Install QR](${qrUrl}) |
| APK | [app-preview.apk](${apkUrl}) |
| Install page | [install.html](${installUrl}) |
| Version history | [app-v* releases](${releasesUrl}) |

In-app self-update uses the rolling manifest \`app-apk-latest.json\` on tag \`${ROLLING_TAG}\`.
${END}`;
}

/**
 * @param {{ readmePath?: string, repo?: string, manifestPath?: string }} [opts]
 * @returns {{ changed: boolean, version: string, buildNumber: string }}
 */
export function updateReadmeInstallSection(opts = {}) {
  const targetReadme = resolve(opts.readmePath || readmePath);
  const readme = readFileSync(targetReadme, 'utf8');
  const meta = resolveVersionAndBuild(opts.manifestPath);
  const section = buildReadmeInstallSection({
    repo: opts.repo || repo,
    manifestPath: opts.manifestPath,
  });

  const hasStart = readme.includes(START);
  const hasEnd = readme.includes(END);
  if (hasStart !== hasEnd) {
    console.error('README.md has mismatched app-android-install markers (need both START and END)');
    process.exit(1);
  }

  let next;
  if (hasStart && hasEnd) {
    const before = readme.slice(0, readme.indexOf(START));
    const after = readme.slice(readme.indexOf(END) + END.length);
    next = `${before}${section}${after}`;
  } else {
    const anchorMatch = readme.match(/^##\s+Mobile app\s*$/m);
    if (!anchorMatch || anchorMatch.index == null) {
      console.error('README.md missing "## Mobile app" anchor — add section manually');
      process.exit(1);
    }
    const insertAt = anchorMatch.index + anchorMatch[0].length;
    next = `${readme.slice(0, insertAt)}\n\n${section}\n${readme.slice(insertAt)}`;
  }

  if (next === readme) {
    console.log('update-readme-app-install: README unchanged');
    return { changed: false, version: meta.version, buildNumber: meta.buildNumber };
  }
  writeFileSync(targetReadme, next, 'utf8');
  console.log(`update-readme-app-install: updated ${targetReadme}`);
  return { changed: true, version: meta.version, buildNumber: meta.buildNumber };
}

function main() {
  updateReadmeInstallSection({ manifestPath: manifestPathFromArgv() });
}

const invoked = process.argv[1]?.replace(/\\/g, '/').endsWith('update-readme-app-install.mjs');
if (invoked) {
  main();
}
