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

function resolveVersionAndBuild() {
  let version = readAppJsonVersion(mobileRoot);
  let buildNumber = readAppJsonBuildNumber(mobileRoot);
  const manifestArgIdx = process.argv.indexOf('--manifest');
  if (manifestArgIdx >= 0) {
    const rawPath = process.argv[manifestArgIdx + 1];
    if (rawPath) {
      const manifestPath = resolve(rawPath);
      if (existsSync(manifestPath)) {
        try {
          const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
          if (manifest.version) version = String(manifest.version);
          if (manifest.build_number != null) buildNumber = String(manifest.build_number);
        } catch (err) {
          console.error(`Error reading or parsing manifest at ${manifestPath}:`, err);
        }
      }
    }
  }
  return { version, buildNumber };
}

function buildSection() {
  const { version, buildNumber } = resolveVersionAndBuild();
  const qrUrl = qrReleaseUrl(repo, ROLLING_TAG);
  const apkUrl = apkDownloadUrl(repo, ROLLING_TAG);
  const installUrl = installReleaseUrl(repo, ROLLING_TAG);
  const releasesUrl = `https://github.com/${repo}/releases?q=app-v&expanded=true`;

  return `${START}
### Android preview install

Scan with **Android Chrome** to install the latest preview APK. The QR image URL is stable (\`${ROLLING_TAG}/app-preview-qr.png\`) and updates on each successful build.

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

function main() {
  const readme = readFileSync(readmePath, 'utf8');
  const section = buildSection();

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
    return;
  }
  writeFileSync(readmePath, next, 'utf8');
  console.log(`update-readme-app-install: updated ${readmePath}`);
}

main();
