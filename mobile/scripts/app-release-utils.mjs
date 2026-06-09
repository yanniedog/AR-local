/**
 * GitHub release + QR install asset helpers (uses qrcode).
 * Naming/changelog: ./app-release-meta.mjs
 */
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import QRCode from 'qrcode';
import {
  INSTALL_HTML,
  MANIFEST_ASSET,
  QR_ASSET,
  ROLLING_TAG,
  installReleaseUrl,
  manifestReleaseUrl,
  qrReleaseUrl,
} from './app-release-meta.mjs';

export * from './app-release-meta.mjs';

/**
 * @param {string} outDir
 * @param {string} downloadUrl
 * @param {string} repo
 * @param {string} tag
 * @param {string} [manifestTag] tag for manifest link in install.html (rolling only)
 */
export async function generateInstallAssets(outDir, downloadUrl, repo, tag, manifestTag = tag) {
  mkdirSync(outDir, { recursive: true });
  const qrPath = join(outDir, QR_ASSET);
  await QRCode.toFile(qrPath, downloadUrl, {
    type: 'png',
    width: 512,
    margin: 2,
    errorCorrectionLevel: 'M',
  });

  const qrUrl = qrReleaseUrl(repo, tag);
  const manifestUrl =
    manifestTag === ROLLING_TAG ? manifestReleaseUrl(repo, manifestTag) : null;
  const manifestLine = manifestUrl
    ? `  <p><small>Manifest: <a href="${manifestUrl}">${MANIFEST_ASSET}</a></small></p>\n`
    : '';

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Install Australian Rates APK</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 32rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.4; }
    img { display: block; width: 16rem; height: 16rem; margin: 1rem auto; }
    a { word-break: break-all; }
    p { margin: 0.75rem 0; }
  </style>
</head>
<body>
  <h1>Install Australian Rates</h1>
  <p>Scan with <strong>Android Chrome</strong> (camera or QR scanner). Chrome downloads the APK directly from GitHub Releases.</p>
  <img src="${qrUrl}" width="512" height="512" alt="QR code for APK download">
  <p><a href="${downloadUrl}">Direct APK download</a></p>
${manifestLine}</body>
</html>
`;
  const installPath = join(outDir, INSTALL_HTML);
  writeFileSync(installPath, html);
  return { qrPath, installPath, qrUrl, installUrl: installReleaseUrl(repo, tag) };
}

/**
 * @param {string} ghToken
 * @param {string} repo
 * @param {string[]} args gh subcommand args (after "gh")
 */
export function gh(ghToken, repo, args, opts = {}) {
  const full = args.includes('--repo') ? args : [...args, '--repo', repo];
  return execFileSync('gh', full, {
    encoding: 'utf8',
    env: { ...process.env, GH_TOKEN: ghToken },
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 60_000,
    ...opts,
  });
}

/**
 * @param {string} ghToken
 * @param {string} repo
 * @param {string} tag
 * @param {string} title
 * @param {string} notes
 * @param {string} [targetRef] commit SHA or branch for new tags
 */
export function ensureGitHubRelease(ghToken, repo, tag, title, notes, targetRef) {
  const view = spawnSync('gh', ['release', 'view', tag, '--repo', repo], {
    encoding: 'utf8',
    env: { ...process.env, GH_TOKEN: ghToken },
    timeout: 30_000,
  });
  if (view.status !== 0) {
    const createArgs = [
      'release',
      'create',
      tag,
      '--title',
      title,
      '--notes',
      notes,
      '--latest=false',
    ];
    if (targetRef?.trim()) {
      createArgs.push('--target', targetRef.trim());
    }
    gh(ghToken, repo, createArgs);
    return 'created';
  }
  gh(ghToken, repo, ['release', 'edit', tag, '--title', title, '--notes', notes]);
  return 'updated';
}
